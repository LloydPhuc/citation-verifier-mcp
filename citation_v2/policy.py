"""Pure evidence model and deterministic verdict policy; no I/O or inference."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from .config import NLI_CONTRADICTION_THRESHOLD, NLI_ENTAILMENT_THRESHOLD

PARTIAL_ENTAILMENT_THRESHOLD = 0.50


@dataclass(frozen=True)
class EvidenceCandidate:
    bm25_rank: int
    bm25_score: float
    chunk_id: int
    chunk_index: int
    quote: str
    start_char: int
    end_char: int
    page_start: int | None
    page_end: int | None
    contradiction: float
    entailment: float
    neutral: float
    predicted_label: str
    premise_truncated: bool
    provenance_verified: bool
    numeric_match: bool
    claim_relevant: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _best_entailment(candidates: Sequence[EvidenceCandidate]) -> EvidenceCandidate | None:
    """BM25 rank first, then confidence, BM25 score and source position."""
    return min(
        candidates,
        key=lambda c: (c.bm25_rank, -c.entailment, -c.bm25_score, c.start_char),
        default=None,
    )


def _best_contradiction(candidates: Sequence[EvidenceCandidate]) -> EvidenceCandidate | None:
    return min(
        candidates,
        key=lambda c: (c.bm25_rank, -c.contradiction, -c.bm25_score, c.start_char),
        default=None,
    )


def _best_neutral(candidates: Sequence[EvidenceCandidate]) -> EvidenceCandidate | None:
    return min(
        candidates,
        key=lambda c: (c.bm25_rank, -c.neutral, -c.bm25_score, c.start_char),
        default=None,
    )


def _decide(
    candidates: Sequence[EvidenceCandidate],
) -> tuple[str, str, str, EvidenceCandidate | None]:
    """Provenance gates authenticity; NLI gates meaning; BM25 ranks evidence.

    Preserve conflict precedence, the dominance safeguard and exact numeric
    grounding. Lexical relevance filters contradictions, not entailments.
    """
    if not candidates:
        return "ABSTAIN", "INSUFFICIENT_EVIDENCE", "NO_EVIDENCE_WINDOWS", None

    supported = [
        c for c in candidates if c.entailment >= NLI_ENTAILMENT_THRESHOLD and c.provenance_verified
    ]
    contradicted = [
        c
        for c in candidates
        if c.contradiction >= NLI_CONTRADICTION_THRESHOLD
        and c.provenance_verified
        and c.claim_relevant
    ]

    if supported and contradicted:
        # Do not misreport spurious entailment as a genuine conflict when
        # relevant contradictions overwhelmingly dominate the signal.
        if (
            len(contradicted) >= 3 * len(supported)
            and max(c.contradiction for c in contradicted)
            > max(c.entailment for c in supported) + 0.15
        ):
            return (
                "ABSTAIN",
                "INSUFFICIENT_EVIDENCE",
                "CONTRADICTIONS_DOMINATE_ENTAILMENT_SIGNAL",
                _best_neutral(candidates),
            )
        entailment = _best_entailment(supported)
        contradiction = _best_contradiction(contradicted)
        assert entailment is not None
        assert contradiction is not None
        selected = min(
            (entailment, contradiction),
            key=lambda c: (c.bm25_rank, -max(c.entailment, c.contradiction), c.start_char),
        )
        return "WARN", "CONFLICTING_EVIDENCE", "STRONG_ENTAILMENT_AND_CONTRADICTION", selected

    if contradicted:
        return "FAIL", "CONTRADICTED", "STRONG_CONTRADICTION", _best_contradiction(contradicted)

    if supported:
        numeric = [c for c in supported if c.numeric_match]
        if numeric:
            return (
                "PASS",
                "SUPPORTED",
                "STRONG_ENTAILMENT_WITH_PROVENANCE",
                _best_entailment(numeric),
            )
        return (
            "WARN",
            "PARTIALLY_SUPPORTED",
            "NUMERIC_VALUE_NOT_VERIFIED",
            _best_entailment(supported),
        )

    moderate = [
        c
        for c in candidates
        if c.provenance_verified
        and c.entailment >= PARTIAL_ENTAILMENT_THRESHOLD
        and c.entailment > c.neutral
        and c.entailment > c.contradiction
    ]
    if moderate:
        numeric = [c for c in moderate if c.numeric_match]
        selected = _best_entailment(numeric or moderate)
        assert selected is not None
        reason = (
            "MODERATE_ENTAILMENT"
            if selected.numeric_match
            else "MODERATE_ENTAILMENT_NUMERIC_MISMATCH"
        )
        return "WARN", "PARTIALLY_SUPPORTED", reason, selected

    return (
        "ABSTAIN",
        "INSUFFICIENT_EVIDENCE",
        "NO_SEMANTIC_SCORE_CROSSED_THRESHOLD",
        _best_neutral(candidates),
    )
