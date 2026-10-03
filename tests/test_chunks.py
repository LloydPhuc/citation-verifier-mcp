"""Tests for citation_v2.chunking module (text_extractor + chunker)."""

import pytest

from citation_v2.chunker import (
    TextChunk,
    chunk_text,
    validate_chunks,
)
from citation_v2.text_extractor import (
    ExtractedPage,
    PDFExtractionResult,
)


@pytest.mark.unit
class TestExtractedPage:
    def test_has_text_true(self):
        page = ExtractedPage(
            page_number=1,
            text="hello",
            start_char=0,
            end_char=5,
        )
        assert page.has_text is True

    def test_has_text_empty_string(self):
        page = ExtractedPage(
            page_number=1,
            text="",
            start_char=0,
            end_char=0,
        )
        assert page.has_text is False

    def test_has_text_whitespace_only(self):
        page = ExtractedPage(
            page_number=1,
            text="   \n\t  ",
            start_char=0,
            end_char=7,
        )
        assert page.has_text is False

    def test_to_dict_includes_has_text(self):
        page = ExtractedPage(
            page_number=2,
            text="content",
            start_char=10,
            end_char=17,
        )
        d = page.to_dict()
        assert d["page_number"] == 2
        assert d["text"] == "content"
        assert d["start_char"] == 10
        assert d["end_char"] == 17
        assert d["has_text"] is True


@pytest.mark.unit
class TestPDFExtractionResult:
    def test_properties(self):
        pages = (
            ExtractedPage(
                page_number=1, text="a", start_char=0, end_char=1
            ),
            ExtractedPage(
                page_number=2, text="b", start_char=2, end_char=3
            ),
        )
        result = PDFExtractionResult(
            source_path="/fake/path.pdf",
            page_count=2,
            text="a\nb",
            pages=pages,
        )
        assert result.text_char_count == 3
        assert result.pages_with_text == 2
        assert result.blank_pages == 0

    def test_blank_page_tracking(self):
        pages = (
            ExtractedPage(
                page_number=1, text="hello", start_char=0, end_char=5
            ),
            ExtractedPage(
                page_number=2, text="", start_char=6, end_char=6
            ),
        )
        result = PDFExtractionResult(
            source_path="/fake.pdf",
            page_count=2,
            text="hello",
            pages=pages,
        )
        assert result.pages_with_text == 1
        assert result.blank_pages == 1

    def test_to_dict(self):
        pages = (
            ExtractedPage(
                page_number=1, text="x", start_char=0, end_char=1
            ),
        )
        result = PDFExtractionResult(
            source_path="/p.pdf",
            page_count=1,
            text="x",
            pages=pages,
        )
        d = result.to_dict()
        assert d["source_path"] == "/p.pdf"
        assert d["page_count"] == 1
        assert d["extraction_method"] == "pdfplumber"
        assert len(d["pages"]) == 1


@pytest.mark.unit
class TestChunkText:
    def test_single_chunk_for_short_text(self):
        text = "hello world"
        chunks = chunk_text(text, target_chars=1000, overlap_chars=100)
        assert len(chunks) == 1
        assert chunks[0].text == text
        assert chunks[0].start_char == 0
        assert chunks[0].end_char == len(text)

    def test_chunk_invariant_holds(self):
        text = "first paragraph.\n\nsecond paragraph.\n\n"
        text += "third paragraph. " * 200
        chunks = chunk_text(text, target_chars=400, overlap_chars=50)
        for chunk in chunks:
            assert text[chunk.start_char:chunk.end_char] == chunk.text

    def test_consecutive_indices(self):
        text = "word " * 500
        chunks = chunk_text(text, target_chars=200, overlap_chars=40)
        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_no_chunks_for_empty_text(self):
        chunks = chunk_text("", target_chars=4000, overlap_chars=600)
        assert chunks == []

    def test_no_chunks_for_whitespace_only(self):
        chunks = chunk_text("   \n\n\t  ", target_chars=4000)
        assert chunks == []

    def test_type_error_on_non_string(self):
        with pytest.raises(TypeError, match="must be a string"):
            chunk_text(123)

    def test_target_chars_must_be_positive(self):
        with pytest.raises(ValueError, match="target_chars must be > 0"):
            chunk_text("hello", target_chars=0)

    def test_overlap_chars_cannot_be_negative(self):
        with pytest.raises(ValueError, match="cannot be negative"):
            chunk_text("hello", overlap_chars=-1)

    def test_overlap_cannot_exceed_target(self):
        with pytest.raises(ValueError, match="must be smaller"):
            chunk_text(
                "hello", target_chars=10, overlap_chars=10
            )

    def test_overlap_cannot_exceed_target_value(self):
        with pytest.raises(ValueError, match="must be smaller"):
            chunk_text(
                "hello", target_chars=10, overlap_chars=15
            )

    def test_forward_progress_guaranteed(self):
        text = "a" * 5000
        chunks = chunk_text(
            text, target_chars=100, overlap_chars=99
        )
        assert len(chunks) > 1
        for chunk in chunks:
            assert text[chunk.start_char:chunk.end_char] == chunk.text

    def test_page_mapping_with_pages(self):
        text = "Page one content.\n\nPage two content."
        pages = (
            ExtractedPage(
                page_number=1,
                text="Page one content.",
                start_char=0,
                end_char=17,
            ),
            ExtractedPage(
                page_number=2,
                text="Page two content.",
                start_char=19,
                end_char=36,
            ),
        )
        chunks = chunk_text(text, pages=pages, target_chars=5000)
        assert len(chunks) == 1
        assert chunks[0].page_start == 1
        assert chunks[0].page_end == 2

    def test_page_mapping_without_pages(self):
        text = "Some text here."
        chunks = chunk_text(text, target_chars=5000)
        assert chunks[0].page_start is None
        assert chunks[0].page_end is None


@pytest.mark.unit
class TestValidateChunks:
    def test_valid_chunks_pass(self):
        text = "hello world"
        chunks = chunk_text(text, target_chars=5000)
        validate_chunks(text, chunks)

    def test_non_consecutive_indices_raise(self):
        text = "hello"
        chunks = [
            TextChunk(
                chunk_index=0,
                text="hello",
                start_char=0,
                end_char=5,
                page_start=None,
                page_end=None,
            ),
            TextChunk(
                chunk_index=2,
                text="hello",
                start_char=0,
                end_char=5,
                page_start=None,
                page_end=None,
            ),
        ]
        with pytest.raises(ValueError, match="not consecutive"):
            validate_chunks(text, chunks)

    def test_negative_start_raises(self):
        text = "hello"
        chunk = TextChunk(
            chunk_index=0,
            text="hello",
            start_char=-1,
            end_char=5,
            page_start=None,
            page_end=None,
        )
        with pytest.raises(ValueError, match="negative"):
            validate_chunks(text, [chunk])

    def test_end_before_start_raises(self):
        text = "hello"
        chunk = TextChunk(
            chunk_index=0,
            text="hello",
            start_char=5,
            end_char=3,
            page_start=None,
            page_end=None,
        )
        with pytest.raises(ValueError, match="invalid offsets"):
            validate_chunks(text, [chunk])

    def test_chunk_beyond_text_raises(self):
        text = "hello"
        chunk = TextChunk(
            chunk_index=0,
            text="hello",
            start_char=0,
            end_char=10,
            page_start=None,
            page_end=None,
        )
        with pytest.raises(ValueError, match="beyond source"):
            validate_chunks(text, [chunk])

    def test_chunk_text_mismatch_raises(self):
        text = "hello world"
        chunk = TextChunk(
            chunk_index=0,
            text="wrong text",
            start_char=0,
            end_char=11,
            page_start=None,
            page_end=None,
        )
        with pytest.raises(ValueError, match="does not match"):
            validate_chunks(text, [chunk])


@pytest.mark.unit
class TestTextChunk:
    def test_char_count(self):
        chunk = TextChunk(
            chunk_index=0,
            text="hello",
            start_char=0,
            end_char=5,
            page_start=None,
            page_end=None,
        )
        assert chunk.char_count == 5

    def test_to_dict(self):
        chunk = TextChunk(
            chunk_index=0,
            text="hello",
            start_char=0,
            end_char=5,
            page_start=1,
            page_end=1,
            section="abstract",
        )
        d = chunk.to_dict()
        assert d["chunk_index"] == 0
        assert d["text"] == "hello"
        assert d["char_count"] == 5
        assert d["section"] == "abstract"
