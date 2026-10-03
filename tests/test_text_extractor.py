"""Tests for citation_v2.text_extractor module (PDF text extraction, provenance offsets)."""

import hashlib

import pytest
from pypdf import PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from citation_v2.text_extractor import (
    ExtractedPage,
    PDFEncryptedError,
    PDFExtractionError,
    PDFExtractionResult,
    PDFNoTextError,
    _normalize_input_path,
    extract_pdf_text,
)


def _create_pdf(path, pages_text):
    """Create a real PDF file with the given text content on each page."""
    c = canvas.Canvas(str(path), pagesize=letter)
    for text in pages_text:
        c.drawString(72, 72, text)
        c.showPage()
    c.save()
    return path


def _create_encrypted_pdf(path, text, user_pw, owner_pw=None):
    """Create an encrypted PDF with the given text."""
    tmp_path = path.with_suffix(".tmp.pdf")
    c = canvas.Canvas(str(tmp_path), pagesize=letter)
    c.drawString(72, 72, text)
    c.showPage()
    c.save()

    writer = PdfWriter(clone_from=str(tmp_path))
    writer.encrypt(
        user_password=user_pw,
        owner_password=owner_pw or "owner",
        algorithm="AES-256",
    )
    with open(path, "wb") as f:
        writer.write(f)

    tmp_path.unlink()
    return path


def _create_image_pdf(path):
    """Create a PDF that has a page but no extractable text (image-only approximation)."""
    c = canvas.Canvas(str(path), pagesize=letter)
    c.showPage()
    c.save()
    return path


@pytest.mark.unit
class TestExtractedPageDataclass:
    def test_has_text_true(self):
        page = ExtractedPage(
            page_number=1, text="hello", start_char=0, end_char=5
        )
        assert page.has_text is True

    def test_has_text_false_empty(self):
        page = ExtractedPage(
            page_number=1, text="", start_char=0, end_char=0
        )
        assert page.has_text is False

    def test_has_text_false_whitespace_only(self):
        page = ExtractedPage(
            page_number=1, text="   \n\n  ", start_char=0, end_char=6
        )
        assert page.has_text is False

    def test_to_dict_includes_has_text(self):
        page = ExtractedPage(
            page_number=2, text="content", start_char=10, end_char=17
        )
        d = page.to_dict()
        assert d["page_number"] == 2
        assert d["text"] == "content"
        assert d["start_char"] == 10
        assert d["end_char"] == 17
        assert d["has_text"] is True

    def test_frozen_immutable(self):
        page = ExtractedPage(
            page_number=1, text="abc", start_char=0, end_char=3
        )
        with pytest.raises(AttributeError):
            page.text = "changed"

    def test_end_char_is_exclusive(self):
        page = ExtractedPage(
            page_number=1, text="hello", start_char=0, end_char=5
        )
        assert page.end_char < 5 or page.end_char == 5


@pytest.mark.unit
class TestPDFExtractionResult:
    def _make_result(self, pages_text):
        text = "\n\n".join(pages_text)
        pages = []
        cursor = 0
        for i, pt in enumerate(pages_text):
            start = cursor
            end = cursor + len(pt)
            pages.append(
                ExtractedPage(
                    page_number=i + 1,
                    text=pt,
                    start_char=start,
                    end_char=end,
                )
            )
            cursor = end
            if i > 0:
                cursor += len("\n\n")
        return PDFExtractionResult(
            source_path="/fake/path.pdf",
            page_count=len(pages_text),
            text=text,
            pages=tuple(pages),
        )

    def test_text_char_count(self):
        result = self._make_result(["hello world"])
        assert result.text_char_count == len("hello world")

    def test_pages_with_text_all_have_text(self):
        result = self._make_result(["page one", "page two"])
        assert result.pages_with_text == 2

    def test_pages_with_text_some_blank(self):
        result = self._make_result(["page one", "   "])
        assert result.pages_with_text == 1

    def test_blank_pages_count(self):
        result = self._make_result(["text", "   ", "text2"])
        assert result.blank_pages == 1

    def test_to_dict_structure(self):
        result = self._make_result(["hello", "world"])
        d = result.to_dict()
        assert d["source_path"] == "/fake/path.pdf"
        assert d["page_count"] == 2
        assert d["text"] == "hello\n\nworld"
        assert d["text_char_count"] == len("hello\n\nworld")
        assert d["pages_with_text"] == 2
        assert d["blank_pages"] == 0
        assert d["extraction_method"] == "pdfplumber"
        assert len(d["pages"]) == 2

    def test_to_dict_includes_page_dicts(self):
        result = self._make_result(["hello"])
        d = result.to_dict()
        assert d["pages"][0]["text"] == "hello"
        assert d["pages"][0]["has_text"] is True

    def test_default_extraction_method(self):
        result = PDFExtractionResult(
            source_path="x", page_count=1, text="t", pages=()
        )
        assert result.extraction_method == "pdfplumber"


@pytest.mark.unit
class TestNormalizeInputPath:
    def test_accepts_path_object(self, tmp_path):
        p = tmp_path / "test.pdf"
        p.write_bytes(b"%PDF-1.4")
        result = _normalize_input_path(p)
        assert isinstance(result, type(p))
        assert result.name == "test.pdf"

    def test_accepts_string_path(self, tmp_path):
        p = tmp_path / "test.pdf"
        p.write_bytes(b"%PDF-1.4")
        result = _normalize_input_path(str(p))
        assert result == p.resolve()

    def test_strips_whitespace(self, tmp_path):
        p = tmp_path / "test.pdf"
        p.write_bytes(b"%PDF-1.4")
        result = _normalize_input_path(f"  {p}  ")
        assert result == p.resolve()

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            _normalize_input_path("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            _normalize_input_path("   ")

    def test_type_error_on_int(self):
        with pytest.raises(TypeError, match="path must be"):
            _normalize_input_path(123)

    def test_type_error_on_none(self):
        with pytest.raises(TypeError, match="path must be"):
            _normalize_input_path(None)

    def test_nonexistent_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _normalize_input_path(tmp_path / "nonexistent.pdf")

    def test_directory_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Expected a PDF file"):
            _normalize_input_path(tmp_path)

    def test_empty_file_raises(self, tmp_path):
        p = tmp_path / "empty.pdf"
        p.write_bytes(b"")
        with pytest.raises(PDFExtractionError, match="empty"):
            _normalize_input_path(p)

    def test_resolves_path(self, tmp_path):
        p = tmp_path / "test.pdf"
        p.write_bytes(b"%PDF-1.4")
        result = _normalize_input_path(str(p))
        assert result.is_absolute()


@pytest.mark.unit
class TestExtractPdfTextSuccess:
    def test_single_page_pdf(self, tmp_path):
        pdf = _create_pdf(tmp_path / "single.pdf", ["Hello World"])
        result = extract_pdf_text(pdf)
        assert result.page_count == 1
        assert "Hello World" in result.text
        assert len(result.pages) == 1
        assert result.pages[0].page_number == 1

    def test_multi_page_pdf(self, tmp_path):
        pdf = _create_pdf(
            tmp_path / "multi.pdf",
            ["First page", "Second page", "Third page"],
        )
        result = extract_pdf_text(pdf)
        assert result.page_count == 3
        assert len(result.pages) == 3
        assert "First page" in result.text
        assert "Second page" in result.text
        assert "Third page" in result.text

    def test_page_separator_is_double_newline(self, tmp_path):
        pdf = _create_pdf(
            tmp_path / "two.pdf", ["Page one.", "Page two."],
        )
        result = extract_pdf_text(pdf)
        assert "\n\n" in result.text
        page_texts = result.text.split("\n\n")
        assert len(page_texts) >= 2

    def test_page_offsets_map_correctly(self, tmp_path):
        pdf = _create_pdf(
            tmp_path / "offset.pdf", ["Page one", "Page two"],
        )
        result = extract_pdf_text(pdf)
        for page in result.pages:
            mapped = result.text[page.start_char:page.end_char]
            assert mapped == page.text

    def test_start_char_zero_for_first_page(self, tmp_path):
        pdf = _create_pdf(tmp_path / "first.pdf", ["hello"])
        result = extract_pdf_text(pdf)
        assert result.pages[0].start_char == 0

    def test_end_char_is_exclusive(self, tmp_path):
        pdf = _create_pdf(tmp_path / "single.pdf", ["abc"])
        result = extract_pdf_text(pdf)
        page = result.pages[0]
        assert result.text[page.start_char:page.end_char] == page.text

    def test_source_path_in_result(self, tmp_path):
        pdf = _create_pdf(tmp_path / "src.pdf", ["content"])
        result = extract_pdf_text(pdf)
        assert result.source_path == str(pdf.resolve())

    def test_page_count_in_result(self, tmp_path):
        pdf = _create_pdf(
            tmp_path / "count.pdf", ["a", "b", "c", "d", "e"]
        )
        result = extract_pdf_text(pdf)
        assert result.page_count == 5

    def test_extraction_method_default(self, tmp_path):
        pdf = _create_pdf(tmp_path / "method.pdf", ["text"])
        result = extract_pdf_text(pdf)
        assert result.extraction_method == "pdfplumber"

    def test_text_normalized(self, tmp_path):
        pdf = _create_pdf(
            tmp_path / "norm.pdf", ["hello   world"],
        )
        result = extract_pdf_text(pdf)
        assert "  " not in result.text

    def test_deterministic_extraction(self, tmp_path):
        pdf = _create_pdf(
            tmp_path / "det.pdf", ["stable text"]
        )
        r1 = extract_pdf_text(pdf)
        r2 = extract_pdf_text(pdf)
        assert r1.text == r2.text
        assert r1.text_char_count == r2.text_char_count
        assert hashlib.sha256(r1.text.encode()).hexdigest() == \
            hashlib.sha256(r2.text.encode()).hexdigest()

    def test_string_path_argument(self, tmp_path):
        pdf = _create_pdf(
            tmp_path / "strpath.pdf", ["string path"]
        )
        result = extract_pdf_text(str(pdf))
        assert "string path" in result.text

    def test_path_object_argument(self, tmp_path):
        pdf = _create_pdf(
            tmp_path / "objpath.pdf", ["path object"]
        )
        result = extract_pdf_text(pdf)
        assert "path object" in result.text


@pytest.mark.unit
class TestExtractPdfTextErrors:
    def test_nonexistent_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            extract_pdf_text(tmp_path / "nonexistent.pdf")

    def test_empty_file_raises(self, tmp_path):
        p = tmp_path / "empty.pdf"
        p.write_bytes(b"")
        with pytest.raises(PDFExtractionError, match="empty"):
            extract_pdf_text(p)

    def test_non_pdf_file_raises(self, tmp_path):
        p = tmp_path / "notpdf.txt"
        p.write_bytes(b"this is not a PDF file")
        with pytest.raises(PDFExtractionError, match="not a PDF"):
            extract_pdf_text(p)

    def test_type_error_on_int(self):
        with pytest.raises(TypeError, match="path must be"):
            extract_pdf_text(12345)

    def test_type_error_on_none(self):
        with pytest.raises(TypeError, match="path must be"):
            extract_pdf_text(None)

    def test_type_error_on_list(self):
        with pytest.raises(TypeError, match="path must be"):
            extract_pdf_text([1, 2, 3])

    def test_corrupted_pdf_raises(self, tmp_path):
        p = tmp_path / "corrupt.pdf"
        p.write_bytes(b"%PDF-1.4\nthis is not valid pdf content")
        with pytest.raises(PDFExtractionError, match="Unable to open PDF"):
            extract_pdf_text(p)

    def test_random_bytes_raises(self, tmp_path):
        p = tmp_path / "random.pdf"
        p.write_bytes(b"\x00\x01\x02\x03\x04\x05")
        with pytest.raises(PDFExtractionError, match="Unable to open PDF"):
            extract_pdf_text(p)

    def test_directory_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Expected a PDF file"):
            extract_pdf_text(tmp_path)

    def test_empty_string_path_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            extract_pdf_text("")

    def test_whitespace_string_path_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            extract_pdf_text("   ")


@pytest.mark.unit
class TestExtractPdfTextEncrypted:
    def test_encrypted_without_password_raises(self, tmp_path):
        pdf = _create_encrypted_pdf(
            tmp_path / "encrypted.pdf",
            "secret content",
            user_pw="password123",
        )
        with pytest.raises(PDFEncryptedError, match="encrypted"):
            extract_pdf_text(pdf)

    def test_encrypted_with_correct_password(self, tmp_path):
        pdf = _create_encrypted_pdf(
            tmp_path / "encrypted.pdf",
            "secret content",
            user_pw="password123",
        )
        result = extract_pdf_text(pdf, password="password123")
        assert "secret content" in result.text

    def test_encrypted_with_wrong_password_raises(self, tmp_path):
        pdf = _create_encrypted_pdf(
            tmp_path / "encrypted.pdf",
            "secret content",
            user_pw="password123",
        )
        with pytest.raises(PDFEncryptedError, match="rejected"):
            extract_pdf_text(pdf, password="wrongpassword")


@pytest.mark.unit
class TestExtractPdfTextNoText:
    def test_pdf_without_text_raises(self, tmp_path):
        c = canvas.Canvas(str(tmp_path / "notext.pdf"), pagesize=letter)
        c.showPage()
        c.save()

        with pytest.raises(PDFNoTextError, match="no extractable text"):
            extract_pdf_text(tmp_path / "notext.pdf")

    def test_empty_pdf_raises(self, tmp_path):
        c = canvas.Canvas(str(tmp_path / "empty_pages.pdf"), pagesize=letter)
        c.showPage()
        c.save()

        with pytest.raises(PDFNoTextError, match="no extractable text"):
            extract_pdf_text(tmp_path / "empty_pages.pdf")

    def test_whitespace_only_text_raises(self, tmp_path):
        c = canvas.Canvas(str(tmp_path / "whitespace.pdf"), pagesize=letter)
        c.drawString(72, 72, "   ")
        c.showPage()
        c.save()

        with pytest.raises(PDFNoTextError, match="no extractable text"):
            extract_pdf_text(tmp_path / "whitespace.pdf")


@pytest.mark.unit
class TestExtractPdfTextProvenance:
    def test_page_text_exact_offset_mapping(self, tmp_path):
        pdf = _create_pdf(
            tmp_path / "prov.pdf", ["alpha", "beta", "gamma"]
        )
        result = extract_pdf_text(pdf)
        accumulated = 0
        for i, page in enumerate(result.pages):
            if i > 0:
                assert page.start_char == accumulated + 2
            else:
                assert page.start_char == accumulated
            page_text = result.text[page.start_char:page.end_char]
            assert page_text == page.text
            accumulated = page.end_char

    def test_offsets_within_bounds(self, tmp_path):
        pdf = _create_pdf(tmp_path / "bounds.pdf", ["hello"])
        result = extract_pdf_text(pdf)
        page = result.pages[0]
        assert page.start_char >= 0
        assert page.end_char <= len(result.text)
        assert page.end_char > page.start_char

    def test_consecutive_page_offsets(self, tmp_path):
        pdf = _create_pdf(
            tmp_path / "consec.pdf", ["1", "2", "3"]
        )
        result = extract_pdf_text(pdf)
        for i in range(1, len(result.pages)):
            prev = result.pages[i - 1]
            curr = result.pages[i]
            assert curr.start_char == prev.end_char + 2

    def test_end_char_is_exclusive_in_slice(self, tmp_path):
        pdf = _create_pdf(
            tmp_path / "exclusive.pdf", ["exactmatch"]
        )
        result = extract_pdf_text(pdf)
        page = result.pages[0]
        extracted = result.text[page.start_char:page.end_char]
        assert extracted == page.text

    def test_to_dict_pages_include_offsets(self, tmp_path):
        pdf = _create_pdf(
            tmp_path / "dict.pdf", ["page text"]
        )
        result = extract_pdf_text(pdf)
        d = result.to_dict()
        page_dict = d["pages"][0]
        assert "start_char" in page_dict
        assert "end_char" in page_dict
        assert page_dict["page_number"] == 1

    def test_all_pages_represented(self, tmp_path):
        pdf = _create_pdf(
            tmp_path / "all.pdf", ["a", "b", "c"]
        )
        result = extract_pdf_text(pdf)
        assert len(result.pages) == result.page_count

    def test_canonical_text_equals_joined_parts(self, tmp_path):
        pdf = _create_pdf(
            tmp_path / "join.pdf", ["part1", "part2"]
        )
        result = extract_pdf_text(pdf)
        parts = [p.text for p in result.pages]
        expected = "\n\n".join(parts)
        assert result.text == expected


@pytest.mark.unit
class TestExceptionHierarchy:
    def test_pdf_extraction_error_is_runtime_error(self):
        assert issubclass(PDFExtractionError, RuntimeError)

    def test_pdf_encrypted_error_is_pdf_extraction_error(self):
        assert issubclass(PDFEncryptedError, PDFExtractionError)

    def test_pdf_no_text_error_is_pdf_extraction_error(self):
        assert issubclass(PDFNoTextError, PDFExtractionError)
