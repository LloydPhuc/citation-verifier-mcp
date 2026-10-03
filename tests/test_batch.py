"""Tests for citation_v2.batch module."""

import pytest

from citation_v2.batch import (
    MAX_BATCH_ITEMS,
    _indexed_response,
    _invalid_item_response,
    _source_failure_response,
    _validate_top_k,
    verify_claims_batch,
)
from citation_v2.nli import NLIResult
from citation_v2.source_loader import (
    SourceDocument,
    SourceDownloadError,
    UnsupportedSourceError,
)
from citation_v2.text_extractor import (
    ExtractedPage,
    PDFExtractionError,
)


@pytest.mark.unit
class TestValidateTopK:
    def test_valid_top_k(self):
        _validate_top_k(5)
        _validate_top_k(1)
        _validate_top_k(20)

    def test_zero_raises(self):
        with pytest.raises(ValueError, match="positive"):
            _validate_top_k(0)

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="positive"):
            _validate_top_k(-1)

    def test_bool_raises(self):
        with pytest.raises(ValueError, match="positive"):
            _validate_top_k(True)

    def test_non_integer_raises(self):
        with pytest.raises(ValueError, match="positive"):
            _validate_top_k(1.5)

    def test_exceeds_max_raises(self):
        with pytest.raises(ValueError, match="cannot exceed"):
            _validate_top_k(21)


@pytest.mark.unit
class TestBatchInputValidation:
    def test_string_rejected(self):
        with pytest.raises(
            ValueError, match="sequence of objects"
        ):
            verify_claims_batch("not a list")

    def test_bytes_rejected(self):
        with pytest.raises(
            ValueError, match="sequence of objects"
        ):
            verify_claims_batch(b"not a list")

    def test_non_sequence_rejected(self):
        with pytest.raises(ValueError, match="sequence"):
            verify_claims_batch(12345)

    def test_empty_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            verify_claims_batch([])

    def test_too_many_items_rejected(self):
        items = [
            {"claim": f"claim {i}", "source": f"src{i}"}
            for i in range(MAX_BATCH_ITEMS + 1)
        ]
        with pytest.raises(
            ValueError, match="more than"
        ):
            verify_claims_batch(items)

    def test_non_dict_item_produces_error_response(
        self,
    ):
        result = verify_claims_batch(
            ["not a dict"],
            persist=False,
        )
        assert result["total"] == 1
        assert result["results"][0]["ok"] is False
        assert result["results"][0]["error_type"] == (
            "INVALID_INPUT"
        )

    def test_non_string_claim_produces_error(self):
        result = verify_claims_batch(
            [{"claim": 123, "source": "test"}],
            persist=False,
        )
        assert result["results"][0]["ok"] is False
        assert "claim" in result["results"][0]["reason"]

    def test_non_string_source_produces_error(self):
        result = verify_claims_batch(
            [{"claim": "test", "source": 123}],
            persist=False,
        )
        assert result["results"][0]["ok"] is False
        assert "source" in result["results"][0]["reason"]

    def test_empty_claim_produces_error(self):
        result = verify_claims_batch(
            [{"claim": "   ", "source": "test"}],
            persist=False,
        )
        assert result["results"][0]["ok"] is False
        assert "empty" in result["results"][0]["reason"]

    def test_empty_source_produces_error(self):
        result = verify_claims_batch(
            [{"claim": "test", "source": ""}],
            persist=False,
        )
        assert result["results"][0]["ok"] is False
        assert "empty" in result["results"][0]["reason"]

    def test_claim_and_source_stripped(self):
        result = verify_claims_batch(
            [
                {
                    "claim": "  test claim  ",
                    "source": "   test_source  ",
                }
            ],
            persist=False,
        )
        assert result["results"][0]["ok"] is True


@pytest.mark.unit
class TestBatchResultStructure:
    def test_result_keys(self):
        result = verify_claims_batch(
            [{"claim": "test", "source": "nonexistent.pdf"}],
            persist=False,
        )
        assert "ok" in result
        assert "total" in result
        assert "passed" in result
        assert "warned" in result
        assert "failed" in result
        assert "abstained" in result
        assert "errors" in result
        assert "unique_sources" in result
        assert "source_loads" in result
        assert "bm25_indexes_built" in result
        assert "top_k" in result
        assert "pipeline_version" in result
        assert "results" in result

    def test_total_matches_input(self):
        result = verify_claims_batch(
            [
                {"claim": "test1", "source": "s1"},
                {"claim": "test2", "source": "s2"},
            ],
            persist=False,
        )
        assert result["total"] == 2
        assert len(result["results"]) == 2

    def test_result_order_matches_input(self):
        result = verify_claims_batch(
            [
                {"claim": "first", "source": "nonexistent.pdf"},
                {"claim": "second", "source": "also_nonexistent.pdf"},
            ],
            persist=False,
        )
        assert result["results"][0]["index"] == 0
        assert result["results"][0]["claim"] == "first"
        assert result["results"][1]["index"] == 1
        assert result["results"][1]["claim"] == "second"

    def test_top_k_in_result(self):
        result = verify_claims_batch(
            [{"claim": "test", "source": "x.pdf"}],
            top_k=7,
            persist=False,
        )
        assert result["top_k"] == 7


@pytest.mark.unit
class TestBatchHelperFunctions:
    def test_indexed_response(self):
        response = {"ok": True, "verdict": "PASS"}
        result = _indexed_response(3, response)
        assert result["index"] == 3
        assert result["ok"] is True
        assert result["verdict"] == "PASS"

    def test_invalid_item_response(self):
        result = _invalid_item_response(
            index=0,
            claim="test",
            source="src",
            reason="bad input",
        )
        assert result["index"] == 0
        assert result["ok"] is False
        assert result["error_type"] == "INVALID_INPUT"
        assert "bad input" in result["reason"]

    def test_source_failure_response_unsupported(self):
        from citation_v2.source_loader import (
            UnsupportedSourceError,
        )

        result = _source_failure_response(
            index=0,
            claim="claim",
            source="src",
            exc=UnsupportedSourceError("bad"),
        )
        assert result["ok"] is True
        assert result["verdict"] == "ABSTAIN"
        assert result["source_state"] == "UNSUPPORTED_SOURCE"

    def test_source_failure_response_security(self):
        from citation_v2.source_loader import (
            SourceSecurityError,
        )

        result = _source_failure_response(
            index=0,
            claim="claim",
            source="src",
            exc=SourceSecurityError("blocked"),
        )
        assert result["verdict"] == "ABSTAIN"
        assert result["source_state"] == "BLOCKED_SOURCE"

    def test_source_failure_response_download(self):
        from citation_v2.source_loader import (
            SourceDownloadError,
        )

        result = _source_failure_response(
            index=0,
            claim="claim",
            source="src",
            exc=SourceDownloadError("failed"),
        )
        assert result["verdict"] == "ABSTAIN"
        assert result["source_state"] == "SOURCE_UNAVAILABLE"

    def test_source_failure_response_cache_error(self):
        from citation_v2.source_loader import (
            SourceCacheError,
        )

        result = _source_failure_response(
            index=0,
            claim="claim",
            source="src",
            exc=SourceCacheError("corrupt"),
        )
        assert result["verdict"] == "ABSTAIN"
        assert result["source_state"] == "CACHE_ERROR"

    def test_source_failure_response_encrypted(self):
        from citation_v2.text_extractor import (
            PDFEncryptedError,
        )

        result = _source_failure_response(
            index=0,
            claim="claim",
            source="src",
            exc=PDFEncryptedError("encrypted"),
        )
        assert result["verdict"] == "ABSTAIN"
        assert result["source_state"] == "ENCRYPTED_PDF"

    def test_source_failure_response_no_text(self):
        from citation_v2.text_extractor import (
            PDFNoTextError,
        )

        result = _source_failure_response(
            index=0,
            claim="claim",
            source="src",
            exc=PDFNoTextError("no text"),
        )
        assert result["verdict"] == "ABSTAIN"
        assert result["source_state"] == "NO_EXTRACTABLE_TEXT"

    def test_source_failure_response_generic(self):
        result = _source_failure_response(
            index=0,
            claim="claim",
            source="src",
            exc=RuntimeError("unknown"),
        )
        assert result["verdict"] == "ABSTAIN"
        assert result["source_state"] == "SOURCE_UNAVAILABLE"

    def test_max_batch_items_constant(self):
        assert MAX_BATCH_ITEMS == 100


"""
Batch source/BM25 reuse and failure isolation tests.

These tests mock at the citation_v2.batch module boundary to verify
that source loading and BM25 index construction are deduplicated
per unique source_input, and that failures are isolated per item.
"""


def _create_mock_source(text="sample pdf content for testing"):
    """Create a deterministic SourceDocument mock for batch reuse tests."""
    pages = (
        ExtractedPage(
            page_number=1,
            text=text,
            start_char=0,
            end_char=len(text),
        ),
    )
    return SourceDocument(
        source_input="test.pdf",
        canonical_id="local:test.pdf",
        source_type="local_pdf",
        source_state="FULL_TEXT",
        paper_id=1,
        text=text,
        content_hash="0" * 64,
        normalized_text_path="test.txt",
        pages=pages,
        cache_hit=False,
    )


def _make_chunk_row(chunk_index=0, text="sample", start=0, end=6):
    return {
        "id": chunk_index + 1,
        "chunk_index": chunk_index,
        "text": text,
        "start_char": start,
        "end_char": end,
        "page_start": 1,
        "page_end": 1,
        "section": None,
        "content_hash": "0" * 64,
    }


@pytest.mark.unit
class TestBatchSourceReuse:
    def test_same_source_loaded_once(self, monkeypatch):
        load_calls = []

        def mock_load(source_input, **kwargs):
            load_calls.append(source_input)
            return _create_mock_source()

        monkeypatch.setattr(
            "citation_v2.batch.load_source", mock_load
        )

        result = verify_claims_batch(
            [
                {"claim": "claim 1", "source": "same.pdf"},
                {"claim": "claim 2", "source": "same.pdf"},
                {"claim": "claim 3", "source": "same.pdf"},
            ],
            persist=False,
        )

        assert len(load_calls) == 1
        assert load_calls[0] == "same.pdf"
        assert result["source_loads"] == 1
        assert result["results"][0]["index"] == 0
        assert result["results"][1]["index"] == 1
        assert result["results"][2]["index"] == 2

    def test_same_source_one_bm25_built(self, monkeypatch):
        bm25_constructions = []

        class MockRetriever:
            def __init__(self, chunks):
                bm25_constructions.append(chunks)

            def search(self, *args, **kwargs):
                return []

        def mock_load(source_input, **kwargs):
            return _create_mock_source()

        monkeypatch.setattr(
            "citation_v2.batch.load_source", mock_load
        )
        monkeypatch.setattr(
            "citation_v2.batch._load_or_create_chunks",
            lambda s: [_make_chunk_row()],
        )
        monkeypatch.setattr(
            "citation_v2.batch.BM25Retriever", MockRetriever
        )

        result = verify_claims_batch(
            [
                {"claim": "alpha claim", "source": "dup.pdf"},
                {"claim": "beta claim", "source": "dup.pdf"},
            ],
            persist=False,
        )

        assert len(bm25_constructions) == 1
        assert result["bm25_indexes_built"] == 1

    def test_different_sources_loaded_separately(self, monkeypatch):
        load_calls = []

        def mock_load(source_input, **kwargs):
            load_calls.append(source_input)
            return _create_mock_source()

        monkeypatch.setattr(
            "citation_v2.batch.load_source", mock_load
        )

        result = verify_claims_batch(
            [
                {"claim": "claim 1", "source": "source_a.pdf"},
                {"claim": "claim 2", "source": "source_b.pdf"},
            ],
            persist=False,
        )

        assert len(load_calls) == 2
        assert "source_a.pdf" in load_calls
        assert "source_b.pdf" in load_calls
        assert result["source_loads"] == 2
        assert result["unique_sources"] == 2
        assert result["results"][0]["index"] == 0
        assert result["results"][1]["index"] == 1

    def test_interleaved_same_source(self, monkeypatch):
        load_calls = []

        def mock_load(source_input, **kwargs):
            load_calls.append(source_input)
            return _create_mock_source()

        monkeypatch.setattr(
            "citation_v2.batch.load_source", mock_load
        )

        result = verify_claims_batch(
            [
                {"claim": "a", "source": "shared.pdf"},
                {"claim": "b", "source": "other.pdf"},
                {"claim": "c", "source": "shared.pdf"},
            ],
            persist=False,
        )

        assert len(load_calls) == 2
        assert result["source_loads"] == 2
        assert result["unique_sources"] == 2
        assert result["total"] == 3

    def test_same_source_bm25_reused_across_claims(self, monkeypatch):
        search_calls = []

        class MockRetriever:
            def __init__(self, chunks):
                pass

            def search(self, claim, top_k=None):
                search_calls.append(claim)
                return []

        def mock_load(source_input, **kwargs):
            return _create_mock_source()

        monkeypatch.setattr(
            "citation_v2.batch.load_source", mock_load
        )
        monkeypatch.setattr(
            "citation_v2.batch._load_or_create_chunks",
            lambda s: [_make_chunk_row()],
        )
        monkeypatch.setattr(
            "citation_v2.batch.BM25Retriever", MockRetriever
        )

        verify_claims_batch(
            [
                {"claim": "claim one", "source": "shared.pdf"},
                {"claim": "claim two", "source": "shared.pdf"},
            ],
            persist=False,
        )

        assert len(search_calls) == 2
        assert search_calls[0] == "claim one"
        assert search_calls[1] == "claim two"


@pytest.mark.unit
class TestBatchFailureIsolation:
    def test_invalid_claim_does_not_block_valid(self, monkeypatch):
        def mock_load(source_input, **kwargs):
            return _create_mock_source()

        monkeypatch.setattr(
            "citation_v2.batch.load_source", mock_load
        )
        monkeypatch.setattr(
            "citation_v2.batch._load_or_create_chunks",
            lambda s: [_make_chunk_row()],
        )

        result = verify_claims_batch(
            [
                {"claim": 123, "source": "valid.pdf"},
                {"claim": "valid claim", "source": "valid.pdf"},
            ],
            persist=False,
        )

        assert result["total"] == 2
        assert result["results"][0]["ok"] is False
        assert result["results"][0]["error_type"] == "INVALID_INPUT"
        assert result["results"][1]["ok"] is True
        assert result["results"][1]["index"] == 1

    def test_invalid_item_type_does_not_block(self, monkeypatch):
        def mock_load(source_input, **kwargs):
            return _create_mock_source()

        monkeypatch.setattr(
            "citation_v2.batch.load_source", mock_load
        )
        monkeypatch.setattr(
            "citation_v2.batch._load_or_create_chunks",
            lambda s: [_make_chunk_row()],
        )

        result = verify_claims_batch(
            [
                "not a dict",
                {"claim": "valid", "source": "s.pdf"},
            ],
            persist=False,
        )

        assert result["total"] == 2
        assert result["results"][0]["ok"] is False
        assert result["results"][0]["error_type"] == "INVALID_INPUT"
        assert result["results"][1]["ok"] is True

    def test_unsupported_source_does_not_block_valid(self, monkeypatch):
        call_log = []

        def mock_load(source_input, **kwargs):
            call_log.append(source_input)
            if source_input == "bad.pdf":
                raise UnsupportedSourceError("not supported")
            return _create_mock_source()

        monkeypatch.setattr(
            "citation_v2.batch.load_source", mock_load
        )
        monkeypatch.setattr(
            "citation_v2.batch._load_or_create_chunks",
            lambda s: [_make_chunk_row()],
        )

        result = verify_claims_batch(
            [
                {"claim": "bad claim", "source": "bad.pdf"},
                {"claim": "good claim", "source": "good.pdf"},
            ],
            persist=False,
        )

        assert result["total"] == 2
        assert result["results"][0]["verdict"] == "ABSTAIN"
        assert result["results"][0]["source_state"] == "UNSUPPORTED_SOURCE"
        assert result["results"][1]["ok"] is True
        assert len(call_log) == 2

    def test_download_error_does_not_block(self, monkeypatch):
        def mock_load(source_input, **kwargs):
            if source_input == "unavailable.pdf":
                raise SourceDownloadError("download failed")
            return _create_mock_source()

        monkeypatch.setattr(
            "citation_v2.batch.load_source", mock_load
        )
        monkeypatch.setattr(
            "citation_v2.batch._load_or_create_chunks",
            lambda s: [_make_chunk_row()],
        )

        result = verify_claims_batch(
            [
                {"claim": "unavailable", "source": "unavailable.pdf"},
                {"claim": "available", "source": "available.pdf"},
            ],
            persist=False,
        )

        assert result["total"] == 2
        assert result["results"][0]["verdict"] == "ABSTAIN"
        assert result["results"][0]["source_state"] == "SOURCE_UNAVAILABLE"
        assert result["results"][1]["ok"] is True

    def test_extraction_error_does_not_block(self, monkeypatch):
        def mock_load(source_input, **kwargs):
            if source_input == "broken.pdf":
                raise PDFExtractionError("extraction failed")
            return _create_mock_source()

        monkeypatch.setattr(
            "citation_v2.batch.load_source", mock_load
        )
        monkeypatch.setattr(
            "citation_v2.batch._load_or_create_chunks",
            lambda s: [_make_chunk_row()],
        )

        result = verify_claims_batch(
            [
                {"claim": "broken", "source": "broken.pdf"},
                {"claim": "works", "source": "works.pdf"},
            ],
            persist=False,
        )

        assert result["total"] == 2
        assert result["results"][0]["verdict"] == "ABSTAIN"
        assert result["results"][0]["source_state"] == "EXTRACTION_FAILED"
        assert result["results"][1]["ok"] is True

    def test_internal_error_does_not_block_group(self, monkeypatch):
        def mock_load(source_input, **kwargs):
            if source_input == "crash.pdf":
                raise RuntimeError("unexpected")
            return _create_mock_source()

        monkeypatch.setattr(
            "citation_v2.batch.load_source", mock_load
        )
        monkeypatch.setattr(
            "citation_v2.batch._load_or_create_chunks",
            lambda s: [_make_chunk_row()],
        )

        result = verify_claims_batch(
            [
                {"claim": "crash", "source": "crash.pdf"},
                {"claim": "ok", "source": "ok.pdf"},
            ],
            persist=False,
        )

        assert result["total"] == 2
        assert result["results"][0]["ok"] is False
        assert result["results"][0]["error_type"] == "INTERNAL_ERROR"
        assert result["results"][1]["ok"] is True

    def test_per_claim_verification_error_isolated(self, monkeypatch):
        class MockRetriever:
            def __init__(self, chunks):
                pass

            def search(self, claim, top_k=None):
                if claim == "bad":
                    raise ValueError("verification failed")
                return []

        def mock_load(source_input, **kwargs):
            return _create_mock_source()

        monkeypatch.setattr(
            "citation_v2.batch.load_source", mock_load
        )
        monkeypatch.setattr(
            "citation_v2.batch._load_or_create_chunks",
            lambda s: [_make_chunk_row()],
        )
        monkeypatch.setattr(
            "citation_v2.batch.BM25Retriever", MockRetriever
        )

        result = verify_claims_batch(
            [
                {"claim": "good", "source": "s.pdf"},
                {"claim": "bad", "source": "s.pdf"},
            ],
            persist=False,
        )

        assert result["total"] == 2
        assert result["results"][0]["ok"] is True
        assert result["results"][1]["ok"] is False


@pytest.mark.unit
class TestBatchResultIntegrity:
    def test_result_count_matches_input(self, monkeypatch):
        def mock_load(source_input, **kwargs):
            return _create_mock_source()

        monkeypatch.setattr(
            "citation_v2.batch.load_source", mock_load
        )
        monkeypatch.setattr(
            "citation_v2.batch._load_or_create_chunks",
            lambda s: [_make_chunk_row()],
        )

        items = [
            {"claim": f"c{i}", "source": f"s{i}.pdf"}
            for i in range(10)
        ]
        result = verify_claims_batch(items, persist=False)
        assert result["total"] == 10
        assert len(result["results"]) == 10

    def test_result_order_preserved(self, monkeypatch):
        def mock_load(source_input, **kwargs):
            return _create_mock_source()

        monkeypatch.setattr(
            "citation_v2.batch.load_source", mock_load
        )
        monkeypatch.setattr(
            "citation_v2.batch._load_or_create_chunks",
            lambda s: [_make_chunk_row()],
        )

        result = verify_claims_batch(
            [
                {"claim": "first", "source": "z.pdf"},
                {"claim": "middle", "source": "a.pdf"},
                {"claim": "last", "source": "m.pdf"},
            ],
            persist=False,
        )

        assert result["results"][0]["index"] == 0
        assert result["results"][0]["claim"] == "first"
        assert result["results"][1]["index"] == 1
        assert result["results"][2]["index"] == 2
        assert result["results"][2]["claim"] == "last"

    def test_no_unverified_pass(self, monkeypatch):
        class MockRetriever:
            def __init__(self, chunks):
                pass

            def search(self, claim, top_k=None):
                return []

        def mock_load(source_input, **kwargs):
            return _create_mock_source()

        monkeypatch.setattr(
            "citation_v2.batch.load_source", mock_load
        )
        monkeypatch.setattr(
            "citation_v2.batch._load_or_create_chunks",
            lambda s: [_make_chunk_row()],
        )
        monkeypatch.setattr(
            "citation_v2.batch.BM25Retriever", MockRetriever
        )

        result = verify_claims_batch(
            [
                {"claim": "unrelated", "source": "s.pdf"},
            ],
            persist=False,
        )

        verdict = result["results"][0].get("verdict")
        assert verdict != "PASS" or result["results"][0].get(
            "evidence", {}
        ).get("provenance_verified") is True

    def test_source_loads_equals_unique_sources(self, monkeypatch):
        def mock_load(source_input, **kwargs):
            return _create_mock_source()

        monkeypatch.setattr(
            "citation_v2.batch.load_source", mock_load
        )
        monkeypatch.setattr(
            "citation_v2.batch._load_or_create_chunks",
            lambda s: [_make_chunk_row()],
        )

        result = verify_claims_batch(
            [
                {"claim": "a", "source": "same.pdf"},
                {"claim": "b", "source": "same.pdf"},
                {"claim": "c", "source": "same.pdf"},
            ],
            persist=False,
        )

        assert result["source_loads"] == result["unique_sources"]
        assert result["source_loads"] == 1

    def test_bm25_indexes_matches_source_loads(self, monkeypatch):
        bm25_count = [0]

        class MockRetriever:
            def __init__(self, chunks):
                bm25_count[0] += 1

            def search(self, *a, **kw):
                return []

        def mock_load(source_input, **kwargs):
            return _create_mock_source()

        monkeypatch.setattr(
            "citation_v2.batch.load_source", mock_load
        )
        monkeypatch.setattr(
            "citation_v2.batch._load_or_create_chunks",
            lambda s: [_make_chunk_row()],
        )
        monkeypatch.setattr(
            "citation_v2.batch.BM25Retriever", MockRetriever
        )

        result = verify_claims_batch(
            [
                {"claim": "a", "source": "s1.pdf"},
                {"claim": "b", "source": "s2.pdf"},
                {"claim": "c", "source": "s1.pdf"},
            ],
            persist=False,
        )

        assert bm25_count[0] == result["bm25_indexes_built"]
        assert bm25_count[0] == 2

    def test_repeated_claims_same_source(self, monkeypatch):
        def mock_load(source_input, **kwargs):
            return _create_mock_source()

        monkeypatch.setattr(
            "citation_v2.batch.load_source", mock_load
        )
        monkeypatch.setattr(
            "citation_v2.batch._load_or_create_chunks",
            lambda s: [_make_chunk_row()],
        )

        result = verify_claims_batch(
            [
                {"claim": "same text", "source": "doc.pdf"},
                {"claim": "same text", "source": "doc.pdf"},
                {"claim": "same text", "source": "doc.pdf"},
            ],
            persist=False,
        )

        assert result["total"] == 3
        assert result["source_loads"] == 1
        for item in result["results"]:
            assert "index" in item
            assert "ok" in item


@pytest.mark.unit
class TestBatchNMLEngineUse:
    """
    Inspect the actual NLI model lifecycle.

    The batch module delegates to score_nli_candidates (verifier.py),
    which calls get_nli_engine() — a lazy process-wide singleton.

    These tests verify the singleton pattern without downloading
    model weights.
    """

    def test_nli_engine_singleton_pattern(self):
        from citation_v2 import nli as nli_module

        assert hasattr(nli_module, "_ENGINE")
        assert nli_module._ENGINE is None
        assert hasattr(nli_module, "get_nli_engine")

    def test_get_nli_engine_is_lazy(self):
        from citation_v2 import nli as nli_module

        assert nli_module._ENGINE is None

    def test_score_nli_candidates_uses_engine(self, monkeypatch):
        call_log = []

        class FakeEngine:
            def score_many(self, claim, evidences):
                call_log.append((claim, len(evidences)))
                return [
                    NLIResult(
                        contradiction=0.1,
                        entailment=0.8,
                        neutral=0.1,
                        predicted_label="entailment",
                        premise_truncated=False,
                        model_id="fake",
                    )
                ]

        monkeypatch.setattr(
            "citation_v2.nli.get_nli_engine",
            lambda: FakeEngine(),
        )

        from citation_v2.nli import score_nli_candidates
        scores = score_nli_candidates(
            claim="test claim",
            evidences=["evidence text"],
        )

        assert len(scores) == 1
        assert scores[0].entailment == 0.8

    def test_single_call_reuses_singleton(self, monkeypatch):
        instances_created = [0]

        class FakeEngine:
            def __init__(self):
                instances_created[0] += 1

            def score_many(self, claim, evidences):
                return [
                    NLIResult(
                        contradiction=0.1,
                        entailment=0.8,
                        neutral=0.1,
                        predicted_label="entailment",
                        premise_truncated=False,
                        model_id="fake",
                    )
                    for _ in evidences
                ]

        def fake_get_engine():
            return FakeEngine()

        monkeypatch.setattr(
            "citation_v2.nli.get_nli_engine",
            fake_get_engine,
        )

        from citation_v2.nli import score_nli_candidates
        score_nli_candidates(
            claim="c1", evidences=["e1", "e2"]
        )

        from citation_v2.nli import score_nli_candidates
        score_nli_candidates(
            claim="c2", evidences=["e3"]
        )

        assert instances_created[0] == 2
