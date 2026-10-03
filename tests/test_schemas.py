"""Tests for citation_v2.schemas module."""

import pytest

from citation_v2.schemas import (
    abstain_response,
    error_response,
    verification_result_to_response,
)
from citation_v2.verifier import VerificationResult


@pytest.mark.unit
class TestVerificationResultToResponse:
    def _make_result(self, **kwargs):
        defaults = {
            "source": "test_source",
            "canonical_id": "local:test",
            "claim": "test claim",
            "verdict": "PASS",
            "semantic_class": "SUPPORTED",
            "reason": "test reason",
            "contradiction_score": 0.1,
            "entailment_score": 0.9,
            "neutral_score": 0.0,
            "evidence_quote": "evidence text",
            "evidence_start_char": 0,
            "evidence_end_char": 12,
            "page_start": 1,
            "page_end": 1,
            "best_chunk_index": 0,
            "bm25_rank": 1,
            "bm25_score": 0.85,
            "provenance_verified": True,
            "numeric_match": True,
            "candidates_retrieved": 5,
            "evidence_windows_scored": 3,
            "model_id": "test:model",
            "pipeline_version": "2.0.0",
            "verification_id": 1,
        }
        defaults.update(kwargs)
        return VerificationResult(**defaults)

    def test_pass_verdict(self):
        result = self._make_result(verdict="PASS")
        response = verification_result_to_response(
            result, top_k=5
        )
        assert response["ok"] is True
        assert response["verdict"] == "PASS"
        assert response["source_state"] == "FULL_TEXT"

    def test_evidence_included_when_quote_present(self):
        result = self._make_result(
            evidence_quote="some evidence"
        )
        response = verification_result_to_response(
            result, top_k=5
        )
        assert response["evidence"] is not None
        assert response["evidence"]["quote"] == "some evidence"
        assert response["evidence"]["provenance_verified"] is True

    def test_evidence_none_when_no_quote(self):
        result = self._make_result(evidence_quote=None)
        response = verification_result_to_response(
            result, top_k=5
        )
        assert response["evidence"] is None

    def test_scores_included_when_present(self):
        result = self._make_result(
            entailment_score=0.8,
            contradiction_score=0.1,
            neutral_score=0.1,
        )
        response = verification_result_to_response(
            result, top_k=5
        )
        assert response["scores"] is not None
        assert response["scores"]["entailment"] == 0.8

    def test_scores_none_when_all_null(self):
        result = self._make_result(
            entailment_score=None,
            contradiction_score=None,
            neutral_score=None,
        )
        response = verification_result_to_response(
            result, top_k=5
        )
        assert response["scores"] is None

    def test_retrieval_info(self):
        result = self._make_result(
            bm25_rank=2,
            bm25_score=0.75,
            candidates_retrieved=10,
            evidence_windows_scored=5,
        )
        response = verification_result_to_response(
            result, top_k=5
        )
        assert response["retrieval"]["method"] == "BM25"
        assert response["retrieval"]["top_k"] == 5
        assert response["retrieval"]["candidates_retrieved"] == 10
        assert response["retrieval"]["evidence_windows_scored"] == 5
        assert response["retrieval"]["selected_bm25_rank"] == 2

    def test_numeric_match_in_response(self):
        result = self._make_result(numeric_match=False)
        response = verification_result_to_response(
            result, top_k=5
        )
        assert response["numeric_match"] is False

    def test_model_id_in_response(self):
        result = self._make_result(model_id="bert-base")
        response = verification_result_to_response(
            result, top_k=5
        )
        assert response["model"] == "bert-base"

    def test_pipeline_version_in_response(self):
        result = self._make_result(pipeline_version="1.0.0")
        response = verification_result_to_response(
            result, top_k=5
        )
        assert response["pipeline_version"] == "1.0.0"

    def test_verification_id_in_response(self):
        result = self._make_result(verification_id=42)
        response = verification_result_to_response(
            result, top_k=5
        )
        assert response["verification_id"] == 42


@pytest.mark.unit
class TestAbstainResponse:
    def test_basic_structure(self):
        response = abstain_response(
            claim="some claim",
            source="some source",
            source_state="FULL_TEXT",
            reason="test reason",
        )
        assert response["ok"] is True
        assert response["verdict"] == "ABSTAIN"
        assert response["semantic_class"] == "INSUFFICIENT_EVIDENCE"
        assert response["reason"] == "test reason"
        assert response["evidence"] is None
        assert response["scores"] is None
        assert response["retrieval"] is None
        assert response["model"] is None
        assert response["provenance_verified"] is False

    def test_with_error_type(self):
        response = abstain_response(
            claim="c",
            source="s",
            source_state="FULL_TEXT",
            reason="r",
            error_type="SOME_ERROR",
        )
        assert response["error_type"] == "SOME_ERROR"

    def test_without_error_type(self):
        response = abstain_response(
            claim="c",
            source="s",
            source_state="FULL_TEXT",
            reason="r",
        )
        assert "error_type" not in response

    def test_claim_and_source_preserved(self):
        response = abstain_response(
            claim="my claim",
            source="my source",
            source_state="ERROR",
            reason="r",
        )
        assert response["claim"] == "my claim"
        assert response["source"] == "my source"
        assert response["source_state"] == "ERROR"


@pytest.mark.unit
class TestErrorResponse:
    def test_structure(self):
        response = error_response(
            claim="bad claim",
            source="bad source",
            reason="bad input",
            error_type="INVALID_INPUT",
        )
        assert response["ok"] is False
        assert response["verdict"] is None
        assert response["semantic_class"] is None
        assert response["reason"] == "bad input"
        assert response["error_type"] == "INVALID_INPUT"
        assert response["source_state"] == "ERROR"
        assert response["provenance_verified"] is False

    def test_none_claim_and_source(self):
        response = error_response(
            claim=None,
            source=None,
            reason="internal error",
            error_type="INTERNAL_ERROR",
        )
        assert response["ok"] is False
        assert response["claim"] is None
        assert response["source"] is None
