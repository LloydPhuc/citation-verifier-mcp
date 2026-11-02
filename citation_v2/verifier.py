from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from .chunker import (
    TextChunk,
    chunk_text,
    validate_chunks,
)
from .config import (
    BM25_TOP_K,
    NLI_MODEL_ID,
    PIPELINE_VERSION,
)
from .database import (
    get_chunks,
    get_or_create_claim,
    initialize_database,
    insert_verification,
    replace_chunks,
)
from .nli import (
    score_nli_candidates,
)
from .policy import EvidenceCandidate, _decide
from .provenance import (
    ProvenanceResult,
    verify_chunk_provenance,
    verify_exact_span,
)
from .retrieval import (
    BM25Retriever,
    RetrievalResult,
)
from .source_loader import (
    SourceDocument,
    load_source,
)

# ============================================================
# Constants
# ============================================================

EVIDENCE_WINDOW_TARGET_CHARS = 1600
EVIDENCE_WINDOW_OVERLAP_CHARS = 300

MIN_CONTRADICTION_EVIDENCE_OVERLAP = 0.30


# ============================================================
# Exceptions
# ============================================================


class VerificationError(RuntimeError):
    """Base verification error."""


class VerificationInputError(VerificationError):
    """Invalid claim/source input."""


# ============================================================
# Evidence relevance: content-word overlap
# ============================================================

_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "with",
        "and",
        "or",
        "but",
        "by",
        "from",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "can",
        "this",
        "that",
        "these",
        "those",
        "i",
        "you",
        "he",
        "she",
        "it",
        "we",
        "they",
        "me",
        "him",
        "her",
        "us",
        "them",
        "my",
        "your",
        "his",
        "its",
        "our",
        "their",
        "all",
        "some",
        "any",
        "no",
        "not",
        "so",
        "than",
        "then",
        "there",
        "here",
        "what",
        "which",
        "who",
        "whom",
        "whose",
        "where",
        "when",
        "while",
        "about",
        "above",
        "below",
        "into",
        "out",
        "up",
        "down",
        "as",
        "if",
        "because",
        "until",
        "though",
        "through",
        "between",
        "during",
        "before",
        "after",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "such",
        "only",
        "own",
        "same",
        "too",
        "very",
        "just",
        "also",
        "even",
        "now",
        "said",
    }
)

_TOKEN_RE = re.compile(r"[a-zA-Z]+")


def _stem_word(word: str) -> str:
    """
    Minimal suffix-stripping stemmer for lexical overlap.

    Normalizes common English inflectional and derivational suffixes so
    that morphological variants share a stem (e.g. *hallucinated* and
    *hallucinations* both → *hallucinat*, *citations* and *citation*
    both → *citat*, *references* and *reference* both → *reference*).

    This is **not** a full Porter stemmer — it strips a curated set of
    high-frequency suffixes and is sufficient for content-word overlap
    estimation.  No external libraries are required.
    """
    if len(word) <= 3:
        return word

    # --- Step 1a: Plurals (Porter-style) ---
    if word.endswith("sses"):
        word = word[:-2] + "ss"
    elif word.endswith("ies") and len(word) > 4:
        word = word[:-3] + "i"
    elif word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]

    # --- Step 1b: Verb endings (-ed, -ing, -edly, -ingly) ---
    for suffix in ("edly", "ingly", "ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            base = word[: -len(suffix)]
            if any(ch in base for ch in "aeiou"):
                word = base
            break

    # --- Step 2/3: Derivational suffixes (longest match first) ---
    # NOTE: "ion" is preferred over "ation"/"ition" so that
    # hallucinated/hallucinations both → hallucinat, not hallucin.
    deriv_suffixes = sorted(
        [
            "izations",
            "ational",
            "fulness",
            "ousness",
            "iveness",
            "ization",
            "alize",
            "alise",
            "alised",
            "alising",
            "alized",
            "alizing",
            "ements",
            "ement",
            "aliti",
            "alism",
            "eness",
            "ities",
            "ity",
            "ment",
            "izers",
            "izer",
            "ify",
            "ate",
            "ion",
        ],
        key=len,
        reverse=True,
    )
    for suffix in deriv_suffixes:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]

    return word


def _content_words(text: str) -> frozenset[str]:
    """
    Extract lowercase alphabetic content-word stems, filtering stopwords.

    Tokens are lowercased and passed through :func:`_stem_word` so that
    morphological variants collapse to a common stem.
    """
    return frozenset(
        _stem_word(token.lower())
        for token in _TOKEN_RE.findall(text)
        if token.lower() not in _STOPWORDS
    )


def _evidence_relevant_to_claim(claim: str, evidence: str) -> bool:
    """
    Return True if the evidence passage is topically relevant to the claim.

    NLI models can assign high contradiction scores to premises that are
    simply *irrelevant* to the hypothesis (semantic distance mistaken for
    logical contradiction).  Requiring a minimum coverage of content
    words prevents unrelated evidence from generating false
    strong-contradiction signals.

    Coverage is the fraction of the claim's content-word stems that also
    appear in the evidence.  A single shared content word (e.g. the generic
    word "paper") is not sufficient — the evidence must share a meaningful
    fraction of the claim's content vocabulary.
    """
    return _claim_evidence_overlap_ratio(claim, evidence) >= MIN_CONTRADICTION_EVIDENCE_OVERLAP


def _claim_evidence_overlap_ratio(claim: str, evidence: str) -> float:
    """
    Coverage of claim content-word stems found in evidence.

    Returns ``len(claim_stems ∩ evidence_stems) / len(claim_stems)``,
    i.e. the fraction of the claim's content vocabulary that is
    substantiated by the evidence passage.
    """
    claim_words = _content_words(claim)
    if not claim_words:
        return 1.0
    evidence_words = _content_words(evidence)
    if not evidence_words:
        return 0.0
    intersection = claim_words & evidence_words
    return len(intersection) / len(claim_words)


class VerificationIntegrityError(VerificationError):
    """
    Internal persisted source/chunk provenance is inconsistent.

    We fail closed instead of silently rebuilding over possible
    corruption.
    """


# ============================================================
# Result schemas
# ============================================================


@dataclass(frozen=True)
class VerificationResult:
    source: str
    canonical_id: str

    claim: str

    verdict: str
    semantic_class: str
    reason: str

    contradiction_score: float | None
    entailment_score: float | None
    neutral_score: float | None

    evidence_quote: str | None

    evidence_start_char: int | None
    evidence_end_char: int | None

    page_start: int | None
    page_end: int | None

    best_chunk_index: int | None
    bm25_rank: int | None
    bm25_score: float | None

    provenance_verified: bool
    numeric_match: bool | None

    candidates_retrieved: int
    evidence_windows_scored: int

    model_id: str | None
    pipeline_version: str

    verification_id: int | None

    source_type: str | None = None
    canonical_url: str | None = None
    content_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ============================================================
# Claim validation
# ============================================================


def _validate_claim(
    claim: str,
) -> str:
    if not isinstance(
        claim,
        str,
    ):
        raise VerificationInputError("claim must be a string.")

    claim = claim.strip()

    if not claim:
        raise VerificationInputError("claim cannot be empty.")

    return claim


# ============================================================
# Numeric guard
# ============================================================

_NUMBER_RE = re.compile(
    r"""
    (?<![\w.])
    [+-]?
    (?:
        \d+(?:[.,]\d+)?
        |
        \.\d+
    )
    (?:[eE][+-]?\d+)?
    %?
    (?![\w.])
    """,
    re.VERBOSE,
)


def _normalize_number_token(
    value: str,
) -> str:
    value = value.strip().replace(",", "")

    if value.endswith("%"):
        value = value[:-1]

    if value.startswith("+"):
        value = value[1:]

    return value


def extract_numeric_tokens(
    text: str,
) -> tuple[str, ...]:
    """
    Extract explicit numeric values.

    This is deliberately conservative.

    Example:
        "mortality decreased by 15%"
            -> ("15",)
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string.")

    values = []

    for match in _NUMBER_RE.finditer(text):
        normalized = _normalize_number_token(match.group(0))

        if normalized:
            values.append(normalized)

    return tuple(values)


def numeric_claim_matches(
    claim: str,
    evidence: str,
) -> bool:
    """
    If the claim contains explicit numeric values, every one
    must also occur explicitly in the evidence.

    Semantic NLI alone is not trusted to verify numbers.
    """

    claim_numbers = set(extract_numeric_tokens(claim))

    if not claim_numbers:
        return True

    evidence_numbers = set(extract_numeric_tokens(evidence))

    return claim_numbers.issubset(evidence_numbers)


# ============================================================
# Chunk persistence / reconstruction
# ============================================================


def _row_to_chunk(
    row: dict[str, Any],
) -> TextChunk:
    return TextChunk(
        chunk_index=int(row["chunk_index"]),
        text=str(row["text"]),
        start_char=int(row["start_char"]),
        end_char=int(row["end_char"]),
        page_start=row.get("page_start"),
        page_end=row.get("page_end"),
        section=row.get("section"),
    )


def _build_chunk_rows(
    chunks: Sequence[TextChunk],
) -> list[dict[str, Any]]:
    return [
        {
            "text": chunk.text,
            "start_char": chunk.start_char,
            "end_char": chunk.end_char,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "section": chunk.section,
        }
        for chunk in chunks
    ]


def _load_or_create_chunks(
    source: SourceDocument,
) -> list[dict[str, Any]]:
    """
    Return persisted chunk rows including SQLite chunk IDs.

    Existing chunks are treated as immutable evidence for the
    exact source content_hash. If they are inconsistent with the
    canonical source, fail closed instead of silently replacing
    them.
    """

    rows = get_chunks(
        paper_id=source.paper_id,
        content_hash=source.content_hash,
    )

    if not rows:
        chunks = chunk_text(
            source.text,
            pages=source.pages,
        )

        if not chunks:
            raise VerificationIntegrityError("Canonical source produced no chunks.")

        validate_chunks(
            source.text,
            chunks,
        )

        replace_chunks(
            paper_id=source.paper_id,
            content_hash=source.content_hash,
            chunks=_build_chunk_rows(chunks),
        )

        rows = get_chunks(
            paper_id=source.paper_id,
            content_hash=source.content_hash,
        )

    if not rows:
        raise VerificationIntegrityError("Chunks could not be persisted or loaded.")

    chunks = [_row_to_chunk(row) for row in rows]

    validate_chunks(
        source.text,
        chunks,
    )

    for chunk in chunks:
        provenance = verify_chunk_provenance(
            source.text,
            chunk,
            pages=source.pages,
        )

        if not provenance.verified:
            raise VerificationIntegrityError(
                f"Persisted chunk provenance is invalid: chunk_index={chunk.chunk_index}"
            )

    return rows


# ============================================================
# Evidence windows
# ============================================================


def _candidate_windows(
    source: SourceDocument,
    *,
    row: dict[str, Any],
    retrieval: RetrievalResult,
) -> list[
    tuple[
        str,
        int,
        int,
        ProvenanceResult,
    ]
]:
    """
    Split one BM25 chunk into smaller exact evidence windows.

    Returned offsets are canonical source offsets.
    """

    chunk = _row_to_chunk(row)

    # Defensive consistency check:
    # BM25 must refer to the same persisted chunk row.
    if chunk.chunk_index != retrieval.chunk.chunk_index:
        raise VerificationIntegrityError("Retrieval chunk index does not match persisted chunk.")

    if (
        chunk.start_char != retrieval.chunk.start_char
        or chunk.end_char != retrieval.chunk.end_char
        or chunk.text != retrieval.chunk.text
    ):
        raise VerificationIntegrityError(
            "Retrieval chunk does not match persisted canonical chunk."
        )

    local_windows = chunk_text(
        chunk.text,
        target_chars=EVIDENCE_WINDOW_TARGET_CHARS,
        overlap_chars=EVIDENCE_WINDOW_OVERLAP_CHARS,
    )

    windows: list[
        tuple[
            str,
            int,
            int,
            ProvenanceResult,
        ]
    ] = []

    for local in local_windows:
        global_start = chunk.start_char + local.start_char

        global_end = chunk.start_char + local.end_char

        quote = source.text[global_start:global_end]

        provenance = verify_exact_span(
            source.text,
            quote=quote,
            start_char=global_start,
            end_char=global_end,
            pages=source.pages,
        )

        if not provenance.verified:
            raise VerificationIntegrityError(
                "Derived evidence window failed exact provenance verification."
            )

        windows.append(
            (
                quote,
                global_start,
                global_end,
                provenance,
            )
        )

    return windows


# ============================================================
# Candidate generation + NLI
# ============================================================


def _score_candidates(
    source: SourceDocument,
    *,
    claim: str,
    rows: Sequence[dict[str, Any]],
    retrievals: Sequence[RetrievalResult],
) -> list[EvidenceCandidate]:
    row_by_index = {int(row["chunk_index"]): row for row in rows}

    staged: list[
        tuple[
            RetrievalResult,
            dict[str, Any],
            str,
            int,
            int,
            ProvenanceResult,
        ]
    ] = []

    for retrieval in retrievals:
        chunk_index = retrieval.chunk.chunk_index

        row = row_by_index.get(chunk_index)

        if row is None:
            raise VerificationIntegrityError(
                "Retrieved chunk does not exist in persisted chunk rows."
            )

        windows = _candidate_windows(
            source,
            row=row,
            retrieval=retrieval,
        )

        for (
            quote,
            start_char,
            end_char,
            provenance,
        ) in windows:
            staged.append(
                (
                    retrieval,
                    row,
                    quote,
                    start_char,
                    end_char,
                    provenance,
                )
            )

    if not staged:
        return []

    nli_results = score_nli_candidates(
        claim=claim,
        evidences=[item[2] for item in staged],
    )

    if len(nli_results) != len(staged):
        raise VerificationIntegrityError("NLI result count does not match evidence window count.")

    candidates: list[EvidenceCandidate] = []

    for item, nli in zip(
        staged,
        nli_results,
        strict=False,
    ):
        (
            retrieval,
            row,
            quote,
            start_char,
            end_char,
            provenance,
        ) = item

        for score in (
            nli.contradiction,
            nli.entailment,
            nli.neutral,
        ):
            if not math.isfinite(score):
                raise VerificationIntegrityError("Non-finite NLI score detected.")

        candidates.append(
            EvidenceCandidate(
                bm25_rank=retrieval.rank,
                bm25_score=retrieval.score,
                chunk_id=int(row["id"]),
                chunk_index=int(row["chunk_index"]),
                quote=quote,
                start_char=start_char,
                end_char=end_char,
                page_start=provenance.page_start,
                page_end=provenance.page_end,
                contradiction=nli.contradiction,
                entailment=nli.entailment,
                neutral=nli.neutral,
                predicted_label=nli.predicted_label,
                premise_truncated=nli.premise_truncated,
                provenance_verified=provenance.verified,
                numeric_match=numeric_claim_matches(
                    claim,
                    quote,
                ),
                claim_relevant=_evidence_relevant_to_claim(
                    claim,
                    quote,
                ),
            )
        )

    return candidates


# ============================================================
# Persistence
# ============================================================


def _persist_result(
    source: SourceDocument,
    *,
    claim: str,
    verdict: str,
    semantic_class: str,
    selected: EvidenceCandidate | None,
    model_id: str | None,
) -> int:
    (
        claim_id,
        _claim_hash,
    ) = get_or_create_claim(claim)

    if selected is None:
        return insert_verification(
            claim_id=claim_id,
            paper_id=source.paper_id,
            verdict=verdict,
            provenance_verified=False,
            source_content_hash=source.content_hash,
            semantic_class=semantic_class,
            model_id=model_id,
            pipeline_version=PIPELINE_VERSION,
        )

    return insert_verification(
        claim_id=claim_id,
        paper_id=source.paper_id,
        verdict=verdict,
        provenance_verified=selected.provenance_verified,
        source_content_hash=source.content_hash,
        semantic_class=semantic_class,
        entailment_score=selected.entailment,
        contradiction_score=selected.contradiction,
        neutral_score=selected.neutral,
        best_chunk_id=selected.chunk_id,
        evidence_quote=selected.quote,
        evidence_start_char=selected.start_char,
        evidence_end_char=selected.end_char,
        model_id=model_id,
        pipeline_version=PIPELINE_VERSION,
    )


# ============================================================
# Main API
# ============================================================


def verify_claim(
    claim: str,
    source_input: str,
    *,
    top_k: int = BM25_TOP_K,
    persist: bool = True,
) -> VerificationResult:
    """
    Verify one claim against one source.

    Pipeline:

        source
        -> canonical text
        -> persisted chunks
        -> BM25
        -> evidence windows
        -> NLI
        -> exact provenance
        -> deterministic verdict
    """

    claim = _validate_claim(claim)

    if not isinstance(
        source_input,
        str,
    ):
        raise VerificationInputError("source_input must be a string.")

    source_input = source_input.strip()

    if not source_input:
        raise VerificationInputError("source_input cannot be empty.")

    if top_k <= 0:
        raise VerificationInputError("top_k must be > 0.")

    initialize_database()

    source = load_source(source_input)

    rows = _load_or_create_chunks(source)

    chunks = [_row_to_chunk(row) for row in rows]

    retriever = BM25Retriever(chunks)

    return verify_prepared_claim(
        claim=claim,
        source_input=source_input,
        source=source,
        rows=rows,
        retriever=retriever,
        top_k=top_k,
        persist=persist,
    )


def verify_prepared_claim(
    *,
    claim: str,
    source_input: str,
    source: SourceDocument,
    rows: Sequence[dict[str, Any]],
    retriever: BM25Retriever,
    top_k: int,
    persist: bool,
) -> VerificationResult:
    """Canonical per-claim pipeline, shared by single and grouped batch calls.

    Callers own input validation and source/index preparation. Evidence scoring,
    verdicts, persistence and result construction have exactly one owner here.
    """
    retrievals = retriever.search(claim, top_k=top_k)
    candidates = (
        _score_candidates(source, claim=claim, rows=rows, retrievals=retrievals)
        if retrievals
        else []
    )
    verdict, semantic_class, reason, selected = _decide(candidates)
    if not retrievals:
        reason = "NO_LEXICAL_CANDIDATES"

    model_id = NLI_MODEL_ID if candidates else None

    verification_id = None

    if persist:
        verification_id = _persist_result(
            source,
            claim=claim,
            verdict=verdict,
            semantic_class=semantic_class,
            selected=selected,
            model_id=model_id,
        )

    return VerificationResult(
        source=source_input,
        source_type=source.source_type,
        canonical_url=source.canonical_url,
        content_hash=source.content_hash,
        canonical_id=source.canonical_id,
        claim=claim,
        verdict=verdict,
        semantic_class=semantic_class,
        reason=reason,
        contradiction_score=selected.contradiction if selected else None,
        entailment_score=selected.entailment if selected else None,
        neutral_score=selected.neutral if selected else None,
        evidence_quote=selected.quote if selected else None,
        evidence_start_char=selected.start_char if selected else None,
        evidence_end_char=selected.end_char if selected else None,
        page_start=selected.page_start if selected else None,
        page_end=selected.page_end if selected else None,
        best_chunk_index=selected.chunk_index if selected else None,
        bm25_rank=selected.bm25_rank if selected else None,
        bm25_score=selected.bm25_score if selected else None,
        provenance_verified=selected.provenance_verified if selected else False,
        numeric_match=selected.numeric_match if selected else None,
        candidates_retrieved=len(retrievals),
        evidence_windows_scored=len(candidates),
        model_id=model_id,
        pipeline_version=PIPELINE_VERSION,
        verification_id=verification_id,
    )
