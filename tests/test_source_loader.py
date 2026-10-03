"""Tests for citation_v2.source_loader module (input parsing & SSRF safety)."""

import os
import tempfile

import pytest

from citation_v2.source_loader import (
    SourceSecurityError,
    UnsupportedSourceError,
    _canonicalize_http_url,
    _extract_arxiv_from_url,
    _is_arxiv_id,
    _normalize_arxiv_id,
    _validate_public_http_url,
    load_source,
)
from citation_v2.text_extractor import (
    PDFExtractionError,
)


@pytest.mark.unit
class TestIsArxivId:
    def test_new_format(self):
        assert _is_arxiv_id("2301.12345") is True

    def test_new_format_with_version(self):
        assert _is_arxiv_id("2301.12345v2") is True

    def test_old_format(self):
        assert _is_arxiv_id("cs/0301001") is True

    def test_old_format_with_version(self):
        assert _is_arxiv_id("cs/0301001v3") is True

    def test_invalid_too_short(self):
        assert _is_arxiv_id("2301.123") is False

    def test_invalid_text(self):
        assert _is_arxiv_id("not-an-id") is False

    def test_empty_string(self):
        assert _is_arxiv_id("") is False


@pytest.mark.unit
class TestNormalizeArxivId:
    def test_strips_prefix(self):
        assert _normalize_arxiv_id("arxiv:2301.12345") == (
            "2301.12345"
        )

    def test_strips_prefix_case_insensitive(self):
        assert _normalize_arxiv_id("ARXIV:2301.12345") == (
            "2301.12345"
        )

    def test_strips_pdf_suffix(self):
        assert _normalize_arxiv_id(
            "2301.12345.pdf"
        ) == "2301.12345"

    def test_strips_whitespace(self):
        assert _normalize_arxiv_id(
            "  2301.12345  "
        ) == "2301.12345"

    def test_strips_prefix_and_pdf(self):
        assert _normalize_arxiv_id(
            "arxiv:2301.12345.pdf"
        ) == "2301.12345"

    def test_invalid_raises(self):
        with pytest.raises(
            UnsupportedSourceError, match="Invalid"
        ):
            _normalize_arxiv_id("not-an-id")

    def test_empty_raises(self):
        with pytest.raises(
            UnsupportedSourceError, match="Invalid"
        ):
            _normalize_arxiv_id("")


@pytest.mark.unit
class TestExtractArxivFromUrl:
    def test_abs_url(self):
        assert _extract_arxiv_from_url(
            "https://arxiv.org/abs/2301.12345"
        ) == "2301.12345"

    def test_pdf_url(self):
        assert _extract_arxiv_from_url(
            "https://arxiv.org/pdf/2301.12345"
        ) == "2301.12345"

    def test_pdf_url_with_extension(self):
        assert _extract_arxiv_from_url(
            "https://arxiv.org/pdf/2301.12345.pdf"
        ) == "2301.12345"

    def test_www_subdomain(self):
        assert _extract_arxiv_from_url(
            "https://www.arxiv.org/abs/2301.12345"
        ) == "2301.12345"

    def test_non_arxiv_host(self):
        assert _extract_arxiv_from_url(
            "https://example.com/abs/2301.12345"
        ) is None

    def test_no_path_prefix(self):
        assert _extract_arxiv_from_url(
            "https://arxiv.org/2301.12345"
        ) is None

    def test_invalid_id_in_url(self):
        assert _extract_arxiv_from_url(
            "https://arxiv.org/abs/not-an-id"
        ) is None

    def test_old_format_url(self):
        assert _extract_arxiv_from_url(
            "https://arxiv.org/abs/cs/0301001"
        ) == "cs/0301001"


@pytest.mark.unit
class TestCanonicalizeHttpUrl:
    def test_basic_url(self):
        url = "https://example.com/doc.pdf"
        result = _canonicalize_http_url(url)
        assert result == url

    def test_strips_fragments(self):
        url = "https://example.com/doc.pdf#section"
        result = _canonicalize_http_url(url)
        assert "section" not in result
        assert "#section" not in result

    def test_lowercases_scheme(self):
        url = "HTTPS://example.com/doc.pdf"
        result = _canonicalize_http_url(url)
        assert result.startswith("https://")

    def test_lowercases_netloc(self):
        url = "https://EXAMPLE.COM/doc.pdf"
        result = _canonicalize_http_url(url)
        assert "EXAMPLE" not in result

    def test_unsupported_scheme_raises(self):
        with pytest.raises(
            UnsupportedSourceError, match="http"
        ):
            _canonicalize_http_url("ftp://example.com/doc.pdf")

    def test_no_hostname_raises(self):
        with pytest.raises(
            UnsupportedSourceError, match="hostname"
        ):
            _canonicalize_http_url("https:///doc.pdf")

    def test_credentials_rejected(self):
        url = "https://user:pass@example.com/doc.pdf"
        with pytest.raises(
            SourceSecurityError, match="credentials"
        ):
            _canonicalize_http_url(url)

    def test_only_username_rejected(self):
        url = "https://user@example.com/doc.pdf"
        with pytest.raises(
            SourceSecurityError, match="credentials"
        ):
            _canonicalize_http_url(url)

    def test_strips_whitespace(self):
        url = "  https://example.com/doc.pdf  "
        assert _canonicalize_http_url(url) == url.strip()


@pytest.mark.unit
class TestValidatePublicHttpUrl:
    def test_localhost_blocked(self):
        with pytest.raises(
            SourceSecurityError, match="Localhost"
        ):
            _validate_public_http_url(
                "http://localhost/doc.pdf"
            )

    def test_localhost_localdomain_blocked(self):
        with pytest.raises(
            SourceSecurityError, match="Localhost"
        ):
            _validate_public_http_url(
                "http://localhost.localdomain/doc.pdf"
            )

    def test_loopback_ip_blocked(self):
        with pytest.raises(SourceSecurityError):
            _validate_public_http_url(
                "http://127.0.0.1/doc.pdf"
            )

    def test_private_ip_blocked(self):
        with pytest.raises(SourceSecurityError):
            _validate_public_http_url(
                "http://192.168.1.1/doc.pdf"
            )

    def test_non_http_scheme_blocked(self):
        with pytest.raises(
            SourceSecurityError, match="http or https"
        ):
            _validate_public_http_url(
                "ftp://example.com/doc.pdf"
            )

    def test_no_hostname_blocked(self):
        with pytest.raises(
            SourceSecurityError, match="no hostname"
        ):
            _validate_public_http_url("https://")

    def test_public_ip_allowed(self):
        _validate_public_http_url(
            "http://8.8.8.8/doc.pdf"
        )


@pytest.mark.unit
class TestLoadSourceDispatch:
    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="empty"):
            load_source("")

    def test_doi_not_supported(self):
        with pytest.raises(
            UnsupportedSourceError, match="not implemented"
        ):
            load_source("10.1038/s41467-025-58551-6")

    def test_nonexistent_local_path_raises(self):
        with pytest.raises(
            UnsupportedSourceError, match="Unsupported source"
        ):
            load_source("/nonexistent/path/file.pdf")

    def test_non_pdf_local_path_raises(self):
        fd, tmpname = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        try:
            with open(tmpname, "w") as f:
                f.write("text")
            with pytest.raises(PDFExtractionError):
                load_source(tmpname)
        finally:
            os.unlink(tmpname)

    def test_unsupported_scheme_raises(self):
        with pytest.raises(
            UnsupportedSourceError, match="Unsupported source"
        ):
            load_source("ftp://example.com/file.pdf")

    def test_type_error_on_invalid_type(self):
        with pytest.raises(TypeError):
            load_source(12345)


@pytest.mark.unit
class TestSourceDocument:
    def test_source_document_fields(self):
        from citation_v2.source_loader import SourceDocument
        from citation_v2.text_extractor import (
            ExtractedPage,
        )

        pages = (
            ExtractedPage(
                page_number=1,
                text="test",
                start_char=0,
                end_char=4,
            ),
        )
        doc = SourceDocument(
            source_input="test_input",
            canonical_id="local:test",
            source_type="local_pdf",
            source_state="FULL_TEXT",
            paper_id=1,
            text="test",
            content_hash="a" * 64,
            normalized_text_path="/path/to/text.txt",
            pages=pages,
            cache_hit=False,
        )
        assert doc.page_count == 1
        assert doc.text_char_count == 4
        assert doc.canonical_url is None
        assert doc.arxiv_id is None
        assert doc.raw_path is None

    def test_source_document_to_dict(self):
        from citation_v2.source_loader import SourceDocument
        from citation_v2.text_extractor import (
            ExtractedPage,
        )

        pages = (
            ExtractedPage(
                page_number=1,
                text="test",
                start_char=0,
                end_char=4,
            ),
        )
        doc = SourceDocument(
            source_input="test_input",
            canonical_id="local:test",
            source_type="local_pdf",
            source_state="FULL_TEXT",
            paper_id=1,
            text="test",
            content_hash="b" * 64,
            normalized_text_path="/path/to/text.txt",
            pages=pages,
            cache_hit=False,
        )
        d = doc.to_dict()
        assert d["canonical_id"] == "local:test"
        assert d["page_count"] == 1
        assert "text" not in d
        assert d["cache_hit"] is False

    def test_source_document_to_dict_includes_text(self):
        from citation_v2.source_loader import SourceDocument
        from citation_v2.text_extractor import (
            ExtractedPage,
        )

        pages = (
            ExtractedPage(
                page_number=1,
                text="test",
                start_char=0,
                end_char=4,
            ),
        )
        doc = SourceDocument(
            source_input="test_input",
            canonical_id="local:test",
            source_type="local_pdf",
            source_state="FULL_TEXT",
            paper_id=1,
            text="hello",
            content_hash="c" * 64,
            normalized_text_path="/path/to/text.txt",
            pages=pages,
            cache_hit=True,
        )
        d = doc.to_dict(include_text=True)
        assert d["text"] == "hello"
        assert d["cache_hit"] is True
