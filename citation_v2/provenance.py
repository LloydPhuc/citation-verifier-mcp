from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from .chunker import TextChunk
from .text_extractor import ExtractedPage


# ============================================================
# Exceptions
# ============================================================

class ProvenanceError(RuntimeError):
    """Base provenance error."""


class ProvenanceInputError(ProvenanceError):
    """Invalid provenance input."""


class ProvenanceAmbiguityError(ProvenanceError):
    """
    Exact quote occurs multiple times and no unique location
    can be determined safely.
    """


# ============================================================
# Result schema
# ============================================================

@dataclass(frozen=True)
class ProvenanceResult:
    verified: bool

    quote: str

    start_char: int | None
    end_char: int | None

    page_start: int | None
    page_end: int | None

    occurrence_count: int

    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ============================================================
# Validation helpers
# ============================================================

def _validate_source_text(
    source_text: str,
) -> None:

    if not isinstance(
        source_text,
        str,
    ):
        raise ProvenanceInputError(
            "source_text must be a string."
        )

    if not source_text:
        raise ProvenanceInputError(
            "source_text cannot be empty."
        )


def _validate_quote(
    quote: str,
) -> None:

    if not isinstance(
        quote,
        str,
    ):
        raise ProvenanceInputError(
            "quote must be a string."
        )

    if not quote:
        raise ProvenanceInputError(
            "quote cannot be empty."
        )

    if not quote.strip():
        raise ProvenanceInputError(
            "quote cannot contain only whitespace."
        )


def _validate_span(
    source_text: str,
    *,
    start_char: int,
    end_char: int,
) -> None:

    if not isinstance(
        start_char,
        int,
    ):
        raise ProvenanceInputError(
            "start_char must be an integer."
        )

    if not isinstance(
        end_char,
        int,
    ):
        raise ProvenanceInputError(
            "end_char must be an integer."
        )

    if start_char < 0:
        raise ProvenanceInputError(
            "start_char cannot be negative."
        )

    if end_char <= start_char:
        raise ProvenanceInputError(
            "end_char must be greater than start_char."
        )

    if end_char > len(
        source_text
    ):
        raise ProvenanceInputError(
            "Evidence span extends beyond source text."
        )


# ============================================================
# Page mapping
# ============================================================

def page_range_for_span(
    *,
    start_char: int,
    end_char: int,
    pages: Sequence[ExtractedPage],
) -> tuple[int | None, int | None]:
    """
    Map an exact character span to physical source pages.

    Zero-width blank pages are never treated as evidence pages.
    """

    matching_pages: list[int] = []

    for page in pages:

        if (
            page.end_char
            == page.start_char
        ):
            continue

        overlaps = (
            start_char < page.end_char
            and end_char > page.start_char
        )

        if overlaps:
            matching_pages.append(
                page.page_number
            )

    if not matching_pages:
        return None, None

    return (
        min(matching_pages),
        max(matching_pages),
    )


# ============================================================
# Exact occurrence search
# ============================================================

def find_exact_occurrences(
    source_text: str,
    quote: str,
    *,
    start_char: int = 0,
    end_char: int | None = None,
) -> list[tuple[int, int]]:
    """
    Find all exact occurrences of quote inside a source range.

    Matching is intentionally exact and case-sensitive.

    No whitespace normalization.
    No fuzzy matching.
    No semantic matching.
    """

    _validate_source_text(
        source_text
    )

    _validate_quote(
        quote
    )

    if end_char is None:
        end_char = len(
            source_text
        )

    if start_char < 0:
        raise ProvenanceInputError(
            "Search start cannot be negative."
        )

    if (
        end_char < start_char
        or end_char > len(source_text)
    ):
        raise ProvenanceInputError(
            "Invalid search range."
        )

    occurrences: list[
        tuple[int, int]
    ] = []

    cursor = start_char

    while cursor <= end_char:

        found = source_text.find(
            quote,
            cursor,
            end_char,
        )

        if found < 0:
            break

        occurrence_end = (
            found + len(quote)
        )

        occurrences.append(
            (
                found,
                occurrence_end,
            )
        )

        # +1 intentionally allows detection of overlapping
        # occurrences while guaranteeing forward progress.
        cursor = found + 1

    return occurrences


# ============================================================
# Span verification
# ============================================================

def verify_exact_span(
    source_text: str,
    *,
    quote: str,
    start_char: int,
    end_char: int,
    pages: Sequence[ExtractedPage] = (),
) -> ProvenanceResult:
    """
    Verify that a supplied quote exactly equals a supplied
    canonical source span.
    """

    _validate_source_text(
        source_text
    )

    _validate_quote(
        quote
    )

    _validate_span(
        source_text,
        start_char=start_char,
        end_char=end_char,
    )

    actual = source_text[
        start_char:end_char
    ]

    verified = (
        actual == quote
    )

    page_start = None
    page_end = None

    if verified and pages:
        (
            page_start,
            page_end,
        ) = page_range_for_span(
            start_char=start_char,
            end_char=end_char,
            pages=pages,
        )

    return ProvenanceResult(
        verified=verified,
        quote=quote,
        start_char=start_char,
        end_char=end_char,
        page_start=page_start,
        page_end=page_end,
        occurrence_count=(
            1 if verified else 0
        ),
        reason=(
            "EXACT_MATCH"
            if verified
            else "SPAN_TEXT_MISMATCH"
        ),
    )


# ============================================================
# Quote location
# ============================================================

def verify_exact_quote(
    source_text: str,
    *,
    quote: str,
    pages: Sequence[ExtractedPage] = (),
    search_start: int = 0,
    search_end: int | None = None,
    require_unique: bool = True,
) -> ProvenanceResult:
    """
    Locate and verify an exact quote in canonical source text.

    If require_unique=True, a quote occurring multiple times
    is considered ambiguous rather than silently choosing the
    first occurrence.
    """

    occurrences = (
        find_exact_occurrences(
            source_text,
            quote,
            start_char=search_start,
            end_char=search_end,
        )
    )

    if not occurrences:

        return ProvenanceResult(
            verified=False,
            quote=quote,
            start_char=None,
            end_char=None,
            page_start=None,
            page_end=None,
            occurrence_count=0,
            reason="QUOTE_NOT_FOUND",
        )

    if (
        require_unique
        and len(occurrences) > 1
    ):

        return ProvenanceResult(
            verified=False,
            quote=quote,
            start_char=None,
            end_char=None,
            page_start=None,
            page_end=None,
            occurrence_count=len(
                occurrences
            ),
            reason="AMBIGUOUS_MULTIPLE_OCCURRENCES",
        )

    start_char, end_char = (
        occurrences[0]
    )

    page_start = None
    page_end = None

    if pages:
        (
            page_start,
            page_end,
        ) = page_range_for_span(
            start_char=start_char,
            end_char=end_char,
            pages=pages,
        )

    return ProvenanceResult(
        verified=True,
        quote=quote,
        start_char=start_char,
        end_char=end_char,
        page_start=page_start,
        page_end=page_end,
        occurrence_count=len(
            occurrences
        ),
        reason="EXACT_MATCH",
    )


# ============================================================
# Chunk provenance
# ============================================================

def verify_chunk_provenance(
    source_text: str,
    chunk: TextChunk,
    *,
    pages: Sequence[ExtractedPage] = (),
) -> ProvenanceResult:
    """
    Verify that a TextChunk is an exact canonical-source span.
    """

    if not isinstance(
        chunk,
        TextChunk,
    ):
        raise ProvenanceInputError(
            "chunk must be a TextChunk."
        )

    return verify_exact_span(
        source_text,
        quote=chunk.text,
        start_char=chunk.start_char,
        end_char=chunk.end_char,
        pages=pages,
    )


# ============================================================
# Exact quote derived from a chunk
# ============================================================

def provenance_from_chunk_span(
    source_text: str,
    chunk: TextChunk,
    *,
    local_start: int,
    local_end: int,
    pages: Sequence[ExtractedPage] = (),
) -> ProvenanceResult:
    """
    Create provenance for an exact subspan inside a verified
    source chunk.

    This is the preferred path for future evidence extraction:

        retrieve chunk
        -> choose subspan
        -> convert local offsets to canonical source offsets
        -> verify exact source mapping
    """

    chunk_result = (
        verify_chunk_provenance(
            source_text,
            chunk,
            pages=pages,
        )
    )

    if not chunk_result.verified:
        raise ProvenanceError(
            "Cannot derive evidence from a chunk "
            "whose provenance is invalid."
        )

    if not isinstance(
        local_start,
        int,
    ):
        raise ProvenanceInputError(
            "local_start must be an integer."
        )

    if not isinstance(
        local_end,
        int,
    ):
        raise ProvenanceInputError(
            "local_end must be an integer."
        )

    if local_start < 0:
        raise ProvenanceInputError(
            "local_start cannot be negative."
        )

    if local_end <= local_start:
        raise ProvenanceInputError(
            "local_end must be greater than local_start."
        )

    if local_end > len(
        chunk.text
    ):
        raise ProvenanceInputError(
            "Local evidence span exceeds chunk text."
        )

    global_start = (
        chunk.start_char
        + local_start
    )

    global_end = (
        chunk.start_char
        + local_end
    )

    quote = source_text[
        global_start:global_end
    ]

    return verify_exact_span(
        source_text,
        quote=quote,
        start_char=global_start,
        end_char=global_end,
        pages=pages,
    )