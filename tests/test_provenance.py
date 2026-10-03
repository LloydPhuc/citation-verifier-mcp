"""Tests for citation_v2.provenance module."""

import pytest

from citation_v2.chunker import TextChunk
from citation_v2.provenance import (
    ProvenanceInputError,
    find_exact_occurrences,
    page_range_for_span,
    provenance_from_chunk_span,
    verify_chunk_provenance,
    verify_exact_quote,
    verify_exact_span,
)
from citation_v2.text_extractor import ExtractedPage


@pytest.mark.unit
class TestFindExactOccurrences:
    def test_single_occurrence(self):
        result = find_exact_occurrences("hello world", "hello")
        assert result == [(0, 5)]

    def test_multiple_occurrences(self):
        result = find_exact_occurrences(
            "a a a", "a"
        )
        assert len(result) == 3
        assert result[0] == (0, 1)
        assert result[1] == (2, 3)
        assert result[2] == (4, 5)

    def test_overlapping_occurrences(self):
        result = find_exact_occurrences(
            "aaa", "aa"
        )
        assert len(result) == 2

    def test_no_occurrence(self):
        result = find_exact_occurrences(
            "hello world", "xyz"
        )
        assert result == []

    def test_custom_range(self):
        result = find_exact_occurrences(
            "a b a b a",
            "a",
            start_char=2,
            end_char=7,
        )
        assert result == [(4, 5)]

    def test_negative_start_raises(self):
        with pytest.raises(
            ProvenanceInputError, match="negative"
        ):
            find_exact_occurrences(
                "text", "t", start_char=-1
            )

    def test_invalid_range_raises(self):
        with pytest.raises(
            ProvenanceInputError, match="Invalid"
        ):
            find_exact_occurrences(
                "text", "t", start_char=3, end_char=2
            )

    def test_end_beyond_text_raises(self):
        with pytest.raises(
            ProvenanceInputError, match="Invalid"
        ):
            find_exact_occurrences(
                "text", "t", end_char=10
            )

    def test_non_string_source(self):
        with pytest.raises(
            ProvenanceInputError, match="must be a string"
        ):
            find_exact_occurrences(123, "text")

    def test_empty_quote_raises(self):
        with pytest.raises(
            ProvenanceInputError, match="cannot be empty"
        ):
            find_exact_occurrences("text", "")

    def test_whitespace_only_quote_raises(self):
        with pytest.raises(
            ProvenanceInputError, match="whitespace"
        ):
            find_exact_occurrences("text", "   ")


@pytest.mark.unit
class TestVerifyExactSpan:
    def test_verified_match(self):
        result = verify_exact_span(
            "hello world",
            quote="hello",
            start_char=0,
            end_char=5,
        )
        assert result.verified is True
        assert result.reason == "EXACT_MATCH"
        assert result.occurrence_count == 1

    def test_mismatch(self):
        result = verify_exact_span(
            "hello world",
            quote="goodbye",
            start_char=0,
            end_char=5,
        )
        assert result.verified is False
        assert result.reason == "SPAN_TEXT_MISMATCH"
        assert result.occurrence_count == 0

    def test_with_pages(self):
        pages = (
            ExtractedPage(
                page_number=1,
                text="hello world",
                start_char=0,
                end_char=11,
            ),
        )
        result = verify_exact_span(
            "hello world",
            quote="hello",
            start_char=0,
            end_char=5,
            pages=pages,
        )
        assert result.verified is True
        assert result.page_start == 1
        assert result.page_end == 1


@pytest.mark.unit
class TestVerifyExactQuote:
    def test_unique_quote(self):
        result = verify_exact_quote(
            "hello world", quote="hello"
        )
        assert result.verified is True
        assert result.start_char == 0
        assert result.end_char == 5
        assert result.occurrence_count == 1

    def test_quote_not_found(self):
        result = verify_exact_quote(
            "hello world", quote="xyz"
        )
        assert result.verified is False
        assert result.reason == "QUOTE_NOT_FOUND"
        assert result.occurrence_count == 0

    def test_ambiguous_quote(self):
        result = verify_exact_quote(
            "hello hello", quote="hello"
        )
        assert result.verified is False
        assert result.occurrence_count == 2
        assert "AMBIGUOUS" in result.reason

    def test_non_unique_quote(self):
        result = verify_exact_quote(
            "hello hello",
            quote="hello",
            require_unique=False,
        )
        assert result.verified is True
        assert result.occurrence_count == 2

    def test_with_pages(self):
        pages = (
            ExtractedPage(
                page_number=1,
                text="hello world",
                start_char=0,
                end_char=11,
            ),
        )
        result = verify_exact_quote(
            "hello world", quote="world", pages=pages
        )
        assert result.verified is True
        assert result.page_start == 1
        assert result.page_end == 1


@pytest.mark.unit
class TestPageSizeRange:
    def test_overlapping_page(self):
        pages = (
            ExtractedPage(
                page_number=1,
                text="page one",
                start_char=0,
                end_char=8,
            ),
            ExtractedPage(
                page_number=2,
                text="page two",
                start_char=10,
                end_char=18,
            ),
        )
        start, end = page_range_for_span(
            start_char=0,
            end_char=8,
            pages=pages,
        )
        assert start == 1
        assert end == 1

    def test_span_across_blank_page(self):
        pages = (
            ExtractedPage(
                page_number=1,
                text="page one",
                start_char=0,
                end_char=8,
            ),
            ExtractedPage(
                page_number=2,
                text="",
                start_char=8,
                end_char=8,
            ),
            ExtractedPage(
                page_number=3,
                text="page three",
                start_char=8,
                end_char=18,
            ),
        )
        start, end = page_range_for_span(
            start_char=0,
            end_char=18,
            pages=pages,
        )
        assert start == 1
        assert end == 3

    def test_no_overlap_returns_none(self):
        pages = (
            ExtractedPage(
                page_number=1,
                text="hello",
                start_char=0,
                end_char=5,
            ),
        )
        start, end = page_range_for_span(
            start_char=10,
            end_char=15,
            pages=pages,
        )
        assert start is None
        assert end is None


@pytest.mark.unit
class TestVerifyChunkProvenance:
    def test_valid_chunk(self):
        text = "hello world"
        chunk = TextChunk(
            chunk_index=0,
            text="hello",
            start_char=0,
            end_char=5,
            page_start=None,
            page_end=None,
        )
        result = verify_chunk_provenance(text, chunk)
        assert result.verified is True

    def test_invalid_chunk_text(self):
        text = "hello world"
        chunk = TextChunk(
            chunk_index=0,
            text="goodbye",
            start_char=0,
            end_char=5,
            page_start=None,
            page_end=None,
        )
        result = verify_chunk_provenance(text, chunk)
        assert result.verified is False

    def test_non_textchunk_raises(self):
        with pytest.raises(
            ProvenanceInputError, match="must be a TextChunk"
        ):
            verify_chunk_provenance("text", "not a chunk")


@pytest.mark.unit
class TestProvenanceFromChunkSpan:
    def test_valid_subspan(self):
        text = "hello world"
        chunk = TextChunk(
            chunk_index=0,
            text="hello world",
            start_char=0,
            end_char=11,
            page_start=None,
            page_end=None,
        )
        result = provenance_from_chunk_span(
            text,
            chunk,
            local_start=0,
            local_end=5,
        )
        assert result.verified is True
        assert result.quote == "hello"

    def test_invalid_chunk_provenance_raises(self):
        text = "hello world"
        chunk = TextChunk(
            chunk_index=0,
            text="wrong",
            start_char=0,
            end_char=5,
            page_start=None,
            page_end=None,
        )
        with pytest.raises(Exception, match="invalid"):
            provenance_from_chunk_span(
                text,
                chunk,
                local_start=0,
                local_end=3,
            )

    def test_local_end_exceeds_chunk_raises(self):
        text = "hello world"
        chunk = TextChunk(
            chunk_index=0,
            text="hello world",
            start_char=0,
            end_char=11,
            page_start=None,
            page_end=None,
        )
        with pytest.raises(
            ProvenanceInputError, match="exceeds"
        ):
            provenance_from_chunk_span(
                text,
                chunk,
                local_start=0,
                local_end=100,
            )

    def test_local_end_before_local_start_raises(self):
        text = "hello world"
        chunk = TextChunk(
            chunk_index=0,
            text="hello world",
            start_char=0,
            end_char=11,
            page_start=None,
            page_end=None,
        )
        with pytest.raises(
            ProvenanceInputError, match="greater than"
        ):
            provenance_from_chunk_span(
                text,
                chunk,
                local_start=5,
                local_end=3,
            )

    def test_negative_local_start_raises(self):
        text = "hello world"
        chunk = TextChunk(
            chunk_index=0,
            text="hello world",
            start_char=0,
            end_char=11,
            page_start=None,
            page_end=None,
        )
        with pytest.raises(
            ProvenanceInputError, match="negative"
        ):
            provenance_from_chunk_span(
                text,
                chunk,
                local_start=-1,
                local_end=5,
            )
