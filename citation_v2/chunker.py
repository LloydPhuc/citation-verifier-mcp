from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence

from .config import (
    CHUNK_OVERLAP_CHARS,
    CHUNK_TARGET_CHARS,
)
from .text_extractor import ExtractedPage


# ============================================================
# Result schema
# ============================================================

@dataclass(frozen=True)
class TextChunk:
    chunk_index: int

    text: str

    start_char: int
    end_char: int

    page_start: int | None
    page_end: int | None

    section: str | None = None

    @property
    def char_count(self) -> int:
        return len(self.text)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["char_count"] = self.char_count
        return result


# ============================================================
# Validation
# ============================================================

def _validate_pages(
    text: str,
    pages: Sequence[ExtractedPage],
) -> None:
    """
    Verify that page provenance is consistent with the
    canonical document text.
    """

    previous_page_number = 0
    previous_end = 0

    for page in pages:

        if page.page_number != previous_page_number + 1:
            raise ValueError(
                "Page numbers must be consecutive "
                "and start at 1."
            )

        if page.start_char < 0:
            raise ValueError(
                f"Invalid page start offset: "
                f"{page.page_number}"
            )

        if page.end_char < page.start_char:
            raise ValueError(
                f"Invalid page offsets: "
                f"{page.page_number}"
            )

        if page.end_char > len(text):
            raise ValueError(
                f"Page {page.page_number} extends "
                "beyond document text."
            )

        if page.start_char < previous_end:
            raise ValueError(
                "Page offsets overlap unexpectedly."
            )

        mapped = text[
            page.start_char:
            page.end_char
        ]

        if mapped != page.text:
            raise ValueError(
                "Page provenance mismatch on page "
                f"{page.page_number}."
            )

        previous_page_number = page.page_number
        previous_end = page.end_char


# ============================================================
# Span helpers
# ============================================================

def _trim_span(
    text: str,
    start: int,
    end: int,
) -> tuple[int, int]:
    """
    Remove only surrounding whitespace while preserving
    exact offsets.

    Interior source content is never modified.
    """

    while (
        start < end
        and text[start].isspace()
    ):
        start += 1

    while (
        end > start
        and text[end - 1].isspace()
    ):
        end -= 1

    return start, end


def _choose_end_boundary(
    text: str,
    start: int,
    nominal_end: int,
    target_chars: int,
) -> int:
    """
    Prefer a natural boundary before nominal_end.

    Priority:
      paragraph
      newline
      sentence punctuation
      whitespace
      hard character boundary

    Search is restricted to the latter portion of the
    target window so chunks do not become pathologically short.
    """

    if nominal_end >= len(text):
        return len(text)

    minimum_size = max(
        1,
        int(target_chars * 0.60),
    )

    search_start = min(
        nominal_end,
        start + minimum_size,
    )

    if search_start >= nominal_end:
        return nominal_end

    window = text[
        search_start:nominal_end
    ]

    # --------------------------------------------------------
    # 1. Paragraph boundary
    # --------------------------------------------------------

    pos = window.rfind("\n\n")

    if pos >= 0:
        return (
            search_start
            + pos
            + 2
        )

    # --------------------------------------------------------
    # 2. Physical line boundary
    # --------------------------------------------------------

    pos = window.rfind("\n")

    if pos >= 0:
        return (
            search_start
            + pos
            + 1
        )

    # --------------------------------------------------------
    # 3. Sentence-like boundary
    #
    # Keep punctuation inside the chunk.
    # --------------------------------------------------------

    best_sentence_end = -1

    for punctuation in (
        ". ",
        "? ",
        "! ",
        ".\n",
        "?\n",
        "!\n",
    ):
        pos = window.rfind(
            punctuation
        )

        if pos >= 0:

            # Include punctuation character,
            # not necessarily following whitespace.
            candidate = (
                search_start
                + pos
                + 1
            )

            if candidate > best_sentence_end:
                best_sentence_end = candidate

    if best_sentence_end > start:
        return best_sentence_end

    # --------------------------------------------------------
    # 4. Ordinary whitespace
    # --------------------------------------------------------

    last_space = max(
        window.rfind(" "),
        window.rfind("\t"),
    )

    if last_space >= 0:
        return (
            search_start
            + last_space
        )

    # --------------------------------------------------------
    # 5. Hard boundary
    # --------------------------------------------------------

    return nominal_end


# ============================================================
# Page mapping
# ============================================================

def _page_range_for_span(
    *,
    start: int,
    end: int,
    pages: Sequence[ExtractedPage],
) -> tuple[int | None, int | None]:
    """
    Find pages whose textual spans overlap a chunk.

    Blank pages have zero-width spans and therefore are not
    considered direct evidence pages.

    If a chunk spans page 1 and page 3 around a blank page 2,
    the returned range is still (1, 3).
    """

    matching_pages: list[int] = []

    for page in pages:

        # Blank page has no textual evidence.
        if page.end_char == page.start_char:
            continue

        overlaps = (
            start < page.end_char
            and end > page.start_char
        )

        if overlaps:
            matching_pages.append(
                page.page_number
            )

    if matching_pages:
        return (
            min(matching_pages),
            max(matching_pages),
        )

    # A non-empty text chunk should normally overlap at least
    # one textual page. Returning None is safer than inventing
    # a page number.
    return None, None


# ============================================================
# Main chunking function
# ============================================================

def chunk_text(
    text: str,
    *,
    pages: Sequence[ExtractedPage] = (),
    target_chars: int = CHUNK_TARGET_CHARS,
    overlap_chars: int = CHUNK_OVERLAP_CHARS,
) -> list[TextChunk]:
    """
    Split canonical source text into overlapping chunks.

    Critical invariant:

        chunk.text ==
        text[chunk.start_char:chunk.end_char]

    No source content is rewritten.
    """

    if not isinstance(text, str):
        raise TypeError(
            "text must be a string."
        )

    if target_chars <= 0:
        raise ValueError(
            "target_chars must be > 0."
        )

    if overlap_chars < 0:
        raise ValueError(
            "overlap_chars cannot be negative."
        )

    if overlap_chars >= target_chars:
        raise ValueError(
            "overlap_chars must be smaller "
            "than target_chars."
        )

    if pages:
        _validate_pages(
            text,
            pages,
        )

    if not text.strip():
        return []

    chunks: list[TextChunk] = []

    document_length = len(text)

    cursor = 0
    chunk_index = 0

    while cursor < document_length:

        nominal_end = min(
            cursor + target_chars,
            document_length,
        )

        end = _choose_end_boundary(
            text,
            cursor,
            nominal_end,
            target_chars,
        )

        # Defensive guard against malformed boundary logic.
        if end <= cursor:
            end = nominal_end

        start, trimmed_end = _trim_span(
            text,
            cursor,
            end,
        )

        # A window consisting entirely of whitespace should
        # never create an evidence chunk.
        if start < trimmed_end:

            page_start, page_end = (
                _page_range_for_span(
                    start=start,
                    end=trimmed_end,
                    pages=pages,
                )
            )

            chunk_text_value = text[
                start:trimmed_end
            ]

            chunk = TextChunk(
                chunk_index=chunk_index,
                text=chunk_text_value,
                start_char=start,
                end_char=trimmed_end,
                page_start=page_start,
                page_end=page_end,
            )

            # ------------------------------------------------
            # Internal provenance assertion.
            # ------------------------------------------------

            if (
                text[
                    chunk.start_char:
                    chunk.end_char
                ]
                != chunk.text
            ):
                raise RuntimeError(
                    "Internal chunk provenance mismatch."
                )

            chunks.append(
                chunk
            )

            chunk_index += 1

        if end >= document_length:
            break

        next_cursor = (
            end - overlap_chars
        )

        # Guaranteed forward progress.
        if next_cursor <= cursor:
            next_cursor = cursor + 1

        cursor = next_cursor

    return chunks


# ============================================================
# Diagnostics
# ============================================================

def validate_chunks(
    text: str,
    chunks: Sequence[TextChunk],
) -> None:
    """
    Assert core chunk provenance invariants.
    """

    previous_index = -1

    for chunk in chunks:

        if (
            chunk.chunk_index
            != previous_index + 1
        ):
            raise ValueError(
                "Chunk indices are not consecutive."
            )

        if chunk.start_char < 0:
            raise ValueError(
                "Chunk start offset is negative."
            )

        if (
            chunk.end_char
            <= chunk.start_char
        ):
            raise ValueError(
                "Chunk has invalid offsets."
            )

        if chunk.end_char > len(text):
            raise ValueError(
                "Chunk extends beyond source text."
            )

        if (
            text[
                chunk.start_char:
                chunk.end_char
            ]
            != chunk.text
        ):
            raise ValueError(
                "Chunk text does not match "
                "source provenance."
            )

        previous_index = (
            chunk.chunk_index
        )