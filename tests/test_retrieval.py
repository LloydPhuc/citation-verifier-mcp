"""Tests for citation_v2.retrieval module."""

import pytest

from citation_v2.chunker import TextChunk
from citation_v2.retrieval import (
    BM25Retriever,
    RetrievalResult,
    retrieve_chunks,
    tokenize_for_bm25,
)


@pytest.mark.unit
class TestTokenizeForBm25:
    def test_basic_tokenization(self):
        tokens = tokenize_for_bm25("hello world")
        assert tokens == ["hello", "world"]

    def test_casefold_applied(self):
        tokens = tokenize_for_bm25("Hello WORLD")
        assert tokens == ["hello", "world"]

    def test_nfkc_normalized(self):
        text = "caf\u00e9"
        tokens = tokenize_for_bm25(text)
        assert tokens == ["café"]

    def test_comparison_operators_retained(self):
        tokens = tokenize_for_bm25("p < 0.05 and p >= 0.01")
        assert "<" in tokens
        assert ">=" in tokens
        assert "0.05" in tokens

    def test_doi_like_token(self):
        tokens = tokenize_for_bm25(
            "10.1038/s41467-025-58551-6"
        )
        assert "10.1038/s41467-025-58551-6" in tokens

    def test_percentage_token(self):
        tokens = tokenize_for_bm25("92.4% decrease")
        assert "92.4%" in tokens

    def test_empty_string(self):
        assert tokenize_for_bm25("") == []

    def test_type_error_on_non_string(self):
        with pytest.raises(TypeError, match="must be a string"):
            tokenize_for_bm25(123)

    def test_dashes(self):
        tokens = tokenize_for_bm25("SARS-CoV-2 virus")
        assert "sars-cov-2" in tokens

    def test_slashes(self):
        tokens = tokenize_for_bm25("mg/kg dose")
        assert "mg/kg" in tokens


@pytest.mark.unit
class TestBM25Retriever:
    def _make_chunks(self, texts):
        return [
            TextChunk(
                chunk_index=i,
                text=t,
                start_char=0,
                end_char=len(t),
                page_start=None,
                page_end=None,
            )
            for i, t in enumerate(texts)
        ]

    def test_chunk_count_property(self):
        chunks = self._make_chunks(["a", "b", "c"])
        retriever = BM25Retriever(chunks)
        assert retriever.chunk_count == 3

    def test_searchable_chunk_count_skips_empty_tokens(self):
        chunks = self._make_chunks(["hello", "!@#$", "world"])
        retriever = BM25Retriever(chunks)
        assert retriever.searchable_chunk_count == 2

    def test_search_returns_results_ordered(self):
        chunks = self._make_chunks(
            ["alpha beta gamma", "unrelated delta", "alpha sentence"]
        )
        retriever = BM25Retriever(chunks)
        results = retriever.search("alpha beta")

        assert len(results) == 2
        assert results[0].rank == 1
        assert results[1].rank == 2
        assert results[0].chunk.chunk_index == 0

    def test_search_top_k(self):
        chunks = self._make_chunks(
            ["alpha one", "alpha two", "alpha three", "alpha four"]
        )
        retriever = BM25Retriever(chunks)
        results = retriever.search("alpha", top_k=2)
        assert len(results) == 2

    def test_search_no_lexical_overlap_returns_empty(self):
        chunks = self._make_chunks(["hello world"])
        retriever = BM25Retriever(chunks)
        results = retriever.search("xyz qrs")
        assert results == []

    def test_search_empty_corpus_returns_empty(self):
        retriever = BM25Retriever([])
        results = retriever.search("test")
        assert results == []

    def test_search_type_error_on_non_string(self):
        chunks = self._make_chunks(["hello"])
        retriever = BM25Retriever(chunks)
        with pytest.raises(TypeError, match="must be a string"):
            retriever.search(123)

    def test_search_invalid_top_k(self):
        chunks = self._make_chunks(["hello"])
        retriever = BM25Retriever(chunks)
        with pytest.raises(ValueError, match="top_k must be > 0"):
            retriever.search("hello", top_k=0)

    def test_search_no_searchable_tokens_returns_empty(self):
        chunks = [
            TextChunk(
                chunk_index=0,
                text="!@#$",
                start_char=0,
                end_char=4,
                page_start=None,
                page_end=None,
            )
        ]
        retriever = BM25Retriever(chunks)
        results = retriever.search("hello")
        assert results == []

    def test_validate_chunks_rejects_non_textchunk(self):
        with pytest.raises(TypeError):
            BM25Retriever(["not a chunk"])

    def test_validate_chunks_rejects_duplicate_index(self):
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
                chunk_index=0,
                text="world",
                start_char=0,
                end_char=5,
                page_start=None,
                page_end=None,
            ),
        ]
        with pytest.raises(ValueError, match="Duplicate"):
            BM25Retriever(chunks)

    def test_validate_chunks_rejects_empty_text(self):
        chunks = [
            TextChunk(
                chunk_index=0,
                text="",
                start_char=0,
                end_char=0,
                page_start=None,
                page_end=None,
            ),
        ]
        with pytest.raises(ValueError, match="empty text"):
            BM25Retriever(chunks)

    def test_validate_chunks_rejects_invalid_offsets(self):
        chunks = [
            TextChunk(
                chunk_index=0,
                text="x",
                start_char=5,
                end_char=3,
                page_start=None,
                page_end=None,
            ),
        ]
        with pytest.raises(ValueError, match="invalid offsets"):
            BM25Retriever(chunks)

    def test_retrieval_result_to_dict(self):
        chunk = TextChunk(
            chunk_index=0,
            text="hello world",
            start_char=0,
            end_char=11,
            page_start=None,
            page_end=None,
        )
        result = RetrievalResult(
            rank=1,
            score=0.5,
            lexical_overlap_count=2,
            lexical_overlap_ratio=1.0,
            chunk=chunk,
        )
        d = result.to_dict()
        assert d["rank"] == 1
        assert d["score"] == 0.5
        assert d["chunk"]["text"] == "hello world"

    def test_retrieval_result_to_dict_no_text(self):
        chunk = TextChunk(
            chunk_index=0,
            text="hello",
            start_char=0,
            end_char=5,
            page_start=None,
            page_end=None,
        )
        result = RetrievalResult(
            rank=1,
            score=0.3,
            lexical_overlap_count=1,
            lexical_overlap_ratio=1.0,
            chunk=chunk,
        )
        d = result.to_dict(include_text=False)
        assert "text" not in d["chunk"]
        assert d["rank"] == 1


@pytest.mark.unit
class TestRetrieveChunks:
    def test_convenience_function(self):
        chunks = [
            TextChunk(
                chunk_index=i,
                text=f"text about topic {i}",
                start_char=0,
                end_char=20,
                page_start=None,
                page_end=None,
            )
            for i in range(3)
        ]
        results = retrieve_chunks("topic", chunks, top_k=2)
        assert len(results) == 2
        assert results[0].rank == 1
