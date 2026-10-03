from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Sequence

from rank_bm25 import BM25Okapi

from .chunker import TextChunk
from .config import BM25_TOP_K


# ============================================================
# Tokenization
# ============================================================

# Examples preserved as single lexical units:
#
#   92.4%
#   0.001
#   SARS-CoV-2
#   mg/kg
#   10.1038/s41467-025-58551-6
#   α
#
# Comparison operators are also retained.
_TOKEN_RE = re.compile(
    r"""
    [^\W_]+
    (?:
        [.\-/:]
        [^\W_]+
    )*
    %?
    |
    <=
    |
    >=
    |
    <
    |
    >
    |
    =
    """,
    re.UNICODE | re.VERBOSE,
)


def tokenize_for_bm25(
    text: str,
) -> list[str]:
    """
    Tokenize text for lexical retrieval only.

    Important:
    This normalization affects retrieval tokens only.
    It NEVER modifies canonical source text or provenance.
    """

    if not isinstance(text, str):
        raise TypeError(
            "text must be a string."
        )

    if not text:
        return []

    # Compatibility normalization is acceptable here because
    # these are search tokens, not canonical evidence text.
    searchable = unicodedata.normalize(
        "NFKC",
        text,
    ).casefold()

    tokens = _TOKEN_RE.findall(
        searchable
    )

    return [
        token
        for token in tokens
        if token
    ]


# ============================================================
# Result schema
# ============================================================

@dataclass(frozen=True)
class RetrievalResult:
    rank: int

    score: float

    lexical_overlap_count: int
    lexical_overlap_ratio: float

    chunk: TextChunk

    def to_dict(
        self,
        *,
        include_text: bool = True,
    ) -> dict[str, Any]:

        result: dict[str, Any] = {
            "rank": self.rank,
            "score": self.score,
            "lexical_overlap_count":
                self.lexical_overlap_count,
            "lexical_overlap_ratio":
                self.lexical_overlap_ratio,
            "chunk": {
                "chunk_index":
                    self.chunk.chunk_index,
                "start_char":
                    self.chunk.start_char,
                "end_char":
                    self.chunk.end_char,
                "page_start":
                    self.chunk.page_start,
                "page_end":
                    self.chunk.page_end,
                "section":
                    self.chunk.section,
                "char_count":
                    self.chunk.char_count,
            },
        }

        if include_text:
            result["chunk"]["text"] = (
                self.chunk.text
            )

        return result


# ============================================================
# Validation
# ============================================================

def _validate_chunks(
    chunks: Sequence[TextChunk],
) -> None:

    seen_indices: set[int] = set()

    for chunk in chunks:

        if not isinstance(
            chunk,
            TextChunk,
        ):
            raise TypeError(
                "All retrieval corpus items "
                "must be TextChunk instances."
            )

        if chunk.chunk_index < 0:
            raise ValueError(
                "chunk_index cannot be negative."
            )

        if chunk.chunk_index in seen_indices:
            raise ValueError(
                "Duplicate chunk_index detected: "
                f"{chunk.chunk_index}"
            )

        seen_indices.add(
            chunk.chunk_index
        )

        if not chunk.text:
            raise ValueError(
                f"Chunk {chunk.chunk_index} "
                "contains empty text."
            )

        if (
            chunk.end_char
            <= chunk.start_char
        ):
            raise ValueError(
                f"Chunk {chunk.chunk_index} "
                "has invalid offsets."
            )


# ============================================================
# BM25 Retriever
# ============================================================

class BM25Retriever:
    """
    Reusable BM25 index for one document/corpus.

    Build once, query many claims.
    """

    def __init__(
        self,
        chunks: Sequence[TextChunk],
    ) -> None:

        self._chunks = tuple(
            chunks
        )

        _validate_chunks(
            self._chunks
        )

        searchable_chunks: list[
            TextChunk
        ] = []

        tokenized_corpus: list[
            list[str]
        ] = []

        token_sets: list[
            frozenset[str]
        ] = []

        for chunk in self._chunks:

            tokens = tokenize_for_bm25(
                chunk.text
            )

            # Text containing only punctuation etc. has
            # no useful lexical representation.
            if not tokens:
                continue

            searchable_chunks.append(
                chunk
            )

            tokenized_corpus.append(
                tokens
            )

            token_sets.append(
                frozenset(tokens)
            )

        self._searchable_chunks = tuple(
            searchable_chunks
        )

        self._tokenized_corpus = tuple(
            tokenized_corpus
        )

        self._token_sets = tuple(
            token_sets
        )

        if self._tokenized_corpus:
            self._bm25 = BM25Okapi(
                list(
                    self._tokenized_corpus
                )
            )
        else:
            self._bm25 = None

    @property
    def chunk_count(self) -> int:
        return len(
            self._chunks
        )

    @property
    def searchable_chunk_count(
        self,
    ) -> int:
        return len(
            self._searchable_chunks
        )

    def search(
        self,
        query: str,
        *,
        top_k: int = BM25_TOP_K,
    ) -> list[RetrievalResult]:
        """
        Retrieve lexical candidate evidence.

        A candidate must share at least one lexical token with
        the query. If no lexical overlap exists, [] is returned.

        No semantic-support conclusion is made here.
        """

        if not isinstance(
            query,
            str,
        ):
            raise TypeError(
                "query must be a string."
            )

        if top_k <= 0:
            raise ValueError(
                "top_k must be > 0."
            )

        query_tokens = (
            tokenize_for_bm25(
                query
            )
        )

        if not query_tokens:
            raise ValueError(
                "Query contains no searchable tokens."
            )

        if self._bm25 is None:
            return []

        query_token_set = frozenset(
            query_tokens
        )

        raw_scores = (
            self._bm25.get_scores(
                query_tokens
            )
        )

        candidates: list[
            tuple[
                float,
                int,
                float,
                TextChunk,
            ]
        ] = []

        for (
            chunk,
            chunk_token_set,
            raw_score,
        ) in zip(
            self._searchable_chunks,
            self._token_sets,
            raw_scores,
        ):

            overlap = (
                query_token_set
                & chunk_token_set
            )

            overlap_count = len(
                overlap
            )

            # Hard anti-garbage guard:
            # BM25 must not nominate an entirely unrelated
            # chunk merely because every score is tied.
            if overlap_count == 0:
                continue

            overlap_ratio = (
                overlap_count
                / len(query_token_set)
            )

            candidates.append(
                (
                    float(raw_score),
                    overlap_count,
                    overlap_ratio,
                    chunk,
                )
            )

        if not candidates:
            return []

        # Deterministic ordering:
        #
        # 1. BM25 score descending
        # 2. lexical overlap descending
        # 3. original chunk index ascending
        #
        # BM25 scores are retrieval-ranking values only.
        candidates.sort(
            key=lambda item: (
                -item[0],
                -item[1],
                item[3].chunk_index,
            )
        )

        selected = candidates[
            : min(
                top_k,
                len(candidates),
            )
        ]

        results: list[
            RetrievalResult
        ] = []

        for rank, (
            score,
            overlap_count,
            overlap_ratio,
            chunk,
        ) in enumerate(
            selected,
            start=1,
        ):

            results.append(
                RetrievalResult(
                    rank=rank,
                    score=score,
                    lexical_overlap_count=
                        overlap_count,
                    lexical_overlap_ratio=
                        overlap_ratio,
                    chunk=chunk,
                )
            )

        return results


# ============================================================
# Convenience API
# ============================================================

def retrieve_chunks(
    query: str,
    chunks: Sequence[TextChunk],
    *,
    top_k: int = BM25_TOP_K,
) -> list[RetrievalResult]:
    """
    Convenience function for one-off retrieval.

    For repeated queries against the same paper, instantiate
    BM25Retriever once instead.
    """

    retriever = BM25Retriever(
        chunks
    )

    return retriever.search(
        query,
        top_k=top_k,
    )