from __future__ import annotations

from typing import Any

from .verifier import VerificationResult


# ============================================================
# Public MCP response schemas
# ============================================================

def verification_result_to_response(
    result: VerificationResult,
    *,
    top_k: int,
) -> dict[str, Any]:
    """
    Convert the internal VerificationResult into the stable,
    public MCP response contract.

    Important:
    - internal implementation details are not leaked
    - evidence provenance remains explicit
    - scores remain separated from verdict
    """

    evidence = None

    if result.evidence_quote is not None:
        evidence = {
            "quote": result.evidence_quote,
            "start_char": result.evidence_start_char,
            "end_char": result.evidence_end_char,
            "page_start": result.page_start,
            "page_end": result.page_end,
            "chunk_index": result.best_chunk_index,
            "provenance_verified":
                result.provenance_verified,
        }

    scores = None

    if (
        result.entailment_score is not None
        or result.contradiction_score is not None
        or result.neutral_score is not None
    ):
        scores = {
            "entailment":
                result.entailment_score,
            "contradiction":
                result.contradiction_score,
            "neutral":
                result.neutral_score,
        }

    return {
        "ok": True,

        "claim": result.claim,
        "source": result.source,
        "canonical_id":
            result.canonical_id,

        # verify_claim currently only performs semantic
        # verification after canonical full text was loaded.
        "source_state": "FULL_TEXT",

        "verdict": result.verdict,
        "semantic_class":
            result.semantic_class,
        "reason": result.reason,

        "evidence": evidence,

        "scores": scores,

        "numeric_match":
            result.numeric_match,

        "retrieval": {
            "method": "BM25",
            "top_k": top_k,
            "candidates_retrieved":
                result.candidates_retrieved,
            "evidence_windows_scored":
                result.evidence_windows_scored,
            "selected_bm25_rank":
                result.bm25_rank,
            "selected_bm25_score":
                result.bm25_score,
        },

        "model": result.model_id,

        "pipeline_version":
            result.pipeline_version,

        "verification_id":
            result.verification_id,
    }


def abstain_response(
    *,
    claim: str,
    source: str,
    source_state: str,
    reason: str,
    error_type: str | None = None,
) -> dict[str, Any]:
    """
    Public fail-closed response for situations where semantic
    verification could not be completed.

    Infrastructure/source failures are NOT interpreted as
    evidence that the claim is false.
    """

    response: dict[str, Any] = {
        "ok": True,

        "claim": claim,
        "source": source,

        "source_state":
            source_state,

        "verdict": "ABSTAIN",
        "semantic_class":
            "INSUFFICIENT_EVIDENCE",

        "reason": reason,

        "evidence": None,
        "scores": None,
        "numeric_match": None,

        "retrieval": None,
        "model": None,

        "provenance_verified": False,
    }

    if error_type:
        response["error_type"] = (
            error_type
        )

    return response


def error_response(
    *,
    claim: str | None,
    source: str | None,
    reason: str,
    error_type: str,
) -> dict[str, Any]:
    """
    Public response for invalid tool invocation or unexpected
    internal failures.

    Unlike ABSTAIN, ok=False means the tool request itself could
    not be processed reliably.
    """

    return {
        "ok": False,

        "claim": claim,
        "source": source,

        "source_state": "ERROR",

        "verdict": None,
        "semantic_class": None,

        "reason": reason,
        "error_type": error_type,

        "evidence": None,
        "scores": None,

        "provenance_verified": False,
    }