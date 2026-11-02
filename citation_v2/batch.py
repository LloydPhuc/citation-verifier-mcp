from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from .chunker import TextChunk
from .config import (
    BM25_TOP_K,
    PIPELINE_VERSION,
)
from .nli import NLIError
from .retrieval import BM25Retriever
from .schemas import (
    abstain_response,
    error_response,
    verification_result_to_response,
)
from .source_loader import (
    SourceCacheError,
    SourceDownloadError,
    SourceLoaderError,
    SourceSecurityError,
    UnsupportedSourceError,
    load_source,
)
from .text_extractor import (
    PDFEncryptedError,
    PDFExtractionError,
    PDFNoTextError,
)
from .verifier import (
    VerificationInputError,
    VerificationIntegrityError,
    _load_or_create_chunks,
    _row_to_chunk,
    verify_prepared_claim,
)

MAX_BATCH_ITEMS = 100


def _validate_top_k(
    top_k: int,
) -> None:
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
        raise ValueError("top_k must be a positive integer.")

    if top_k > 20:
        raise ValueError("top_k cannot exceed 20.")


def _indexed_response(
    index: int,
    response: dict[str, Any],
) -> dict[str, Any]:
    return {
        "index": index,
        **response,
    }


def _source_failure_response(
    *,
    index: int,
    claim: str,
    source: str,
    exc: Exception,
) -> dict[str, Any]:
    if isinstance(
        exc,
        UnsupportedSourceError,
    ):
        source_state = "UNSUPPORTED_SOURCE"

    elif isinstance(
        exc,
        SourceSecurityError,
    ):
        source_state = "BLOCKED_SOURCE"

    elif isinstance(
        exc,
        SourceDownloadError,
    ):
        source_state = "SOURCE_UNAVAILABLE"

    elif isinstance(
        exc,
        SourceCacheError,
    ):
        source_state = "CACHE_ERROR"

    elif isinstance(
        exc,
        PDFEncryptedError,
    ):
        source_state = "ENCRYPTED_PDF"

    elif isinstance(
        exc,
        PDFNoTextError,
    ):
        source_state = "NO_EXTRACTABLE_TEXT"

    elif isinstance(
        exc,
        PDFExtractionError,
    ):
        source_state = "EXTRACTION_FAILED"

    else:
        source_state = "SOURCE_UNAVAILABLE"

    return _indexed_response(
        index,
        abstain_response(
            claim=claim,
            source=source,
            source_state=source_state,
            reason=str(exc),
            error_type=type(exc).__name__,
        ),
    )


def _invalid_item_response(
    *,
    index: int,
    claim: str | None,
    source: str | None,
    reason: str,
) -> dict[str, Any]:
    return _indexed_response(
        index,
        error_response(
            claim=claim,
            source=source,
            reason=reason,
            error_type="INVALID_INPUT",
        ),
    )


def verify_claims_batch(
    claims: Sequence[dict[str, Any]],
    *,
    top_k: int = BM25_TOP_K,
    persist: bool = True,
) -> dict[str, Any]:
    """
    Verify multiple claim/source pairs.

    Important properties:
    - result order matches input order,
    - claims sharing the same source reuse one loaded document,
    - claims sharing the same source reuse one BM25 index,
    - the process-wide NLI model singleton is reused,
    - one bad claim/source does not abort the rest of the batch.
    """

    _validate_top_k(top_k)

    if isinstance(
        claims,
        str | bytes,
    ):
        raise ValueError("claims must be a sequence of objects.")

    if not isinstance(
        claims,
        Sequence,
    ):
        raise ValueError("claims must be a sequence.")

    total = len(claims)

    if total == 0:
        raise ValueError("claims cannot be empty.")

    if total > MAX_BATCH_ITEMS:
        raise ValueError(f"claims cannot contain more than {MAX_BATCH_ITEMS} items.")

    results: list[dict[str, Any] | None] = [None for _ in range(total)]

    # Each valid item becomes:
    # (index, cleaned claim, cleaned source)
    valid_items: list[tuple[int, str, str]] = []

    for index, item in enumerate(claims):
        if not isinstance(
            item,
            dict,
        ):
            results[index] = _invalid_item_response(
                index=index,
                claim=None,
                source=None,
                reason=("Each batch item must be an object."),
            )
            continue

        raw_claim = item.get("claim")
        raw_source = item.get("source")

        if not isinstance(
            raw_claim,
            str,
        ):
            results[index] = _invalid_item_response(
                index=index,
                claim=None,
                source=(
                    raw_source
                    if isinstance(
                        raw_source,
                        str,
                    )
                    else None
                ),
                reason=("claim must be a string."),
            )
            continue

        if not isinstance(
            raw_source,
            str,
        ):
            results[index] = _invalid_item_response(
                index=index,
                claim=raw_claim,
                source=None,
                reason=("source must be a string."),
            )
            continue

        clean_claim = raw_claim.strip()
        clean_source = raw_source.strip()

        if not clean_claim:
            results[index] = _invalid_item_response(
                index=index,
                claim=raw_claim,
                source=clean_source,
                reason=("claim cannot be empty."),
            )
            continue

        if not clean_source:
            results[index] = _invalid_item_response(
                index=index,
                claim=clean_claim,
                source=raw_source,
                reason=("source cannot be empty."),
            )
            continue

        valid_items.append(
            (
                index,
                clean_claim,
                clean_source,
            )
        )

    groups: dict[str, list[tuple[int, str]]] = defaultdict(list)

    for (
        index,
        claim,
        source_input,
    ) in valid_items:
        groups[source_input].append(
            (
                index,
                claim,
            )
        )

    source_loads = 0
    bm25_indexes_built = 0

    for (
        source_input,
        group_items,
    ) in groups.items():
        try:
            source = load_source(source_input)

            source_loads += 1

            rows = _load_or_create_chunks(source)

            chunks: list[TextChunk] = [_row_to_chunk(row) for row in rows]

            retriever = BM25Retriever(chunks)

            bm25_indexes_built += 1

        except (
            UnsupportedSourceError,
            SourceSecurityError,
            SourceDownloadError,
            SourceCacheError,
            SourceLoaderError,
            PDFEncryptedError,
            PDFNoTextError,
            PDFExtractionError,
        ) as exc:
            for (
                index,
                claim,
            ) in group_items:
                results[index] = _source_failure_response(
                    index=index,
                    claim=claim,
                    source=source_input,
                    exc=exc,
                )

            continue

        except Exception as exc:
            for (
                index,
                claim,
            ) in group_items:
                results[index] = _indexed_response(
                    index,
                    error_response(
                        claim=claim,
                        source=source_input,
                        reason=(f"Internal source preparation error: {type(exc).__name__}"),
                        error_type="INTERNAL_ERROR",
                    ),
                )

            continue

        for (
            index,
            claim,
        ) in group_items:
            try:
                result = verify_prepared_claim(
                    claim=claim,
                    source_input=source_input,
                    source=source,
                    rows=rows,
                    retriever=retriever,
                    top_k=top_k,
                    persist=persist,
                )

                response = verification_result_to_response(
                    result,
                    top_k=top_k,
                )

                # Final batch boundary invariant:
                # never expose an ungrounded PASS.
                if response.get("verdict") == "PASS":
                    evidence = response.get("evidence")

                    if (
                        not isinstance(
                            evidence,
                            dict,
                        )
                        or evidence.get("provenance_verified") is not True
                    ):
                        response = abstain_response(
                            claim=claim,
                            source=source_input,
                            source_state="FULL_TEXT",
                            reason=("PASS_BLOCKED_BY_PROVENANCE_GATE"),
                            error_type="PROVENANCE_FAILURE",
                        )

                results[index] = _indexed_response(
                    index,
                    response,
                )

            except (
                VerificationInputError,
                ValueError,
            ) as exc:
                results[index] = _indexed_response(
                    index,
                    error_response(
                        claim=claim,
                        source=source_input,
                        reason=str(exc),
                        error_type=type(exc).__name__,
                    ),
                )

            except (
                VerificationIntegrityError,
                NLIError,
            ) as exc:
                results[index] = _indexed_response(
                    index,
                    error_response(
                        claim=claim,
                        source=source_input,
                        reason=(f"Verification integrity error: {type(exc).__name__}"),
                        error_type=type(exc).__name__,
                    ),
                )

            except Exception as exc:
                results[index] = _indexed_response(
                    index,
                    error_response(
                        claim=claim,
                        source=source_input,
                        reason=(f"Internal verification error: {type(exc).__name__}"),
                        error_type="INTERNAL_ERROR",
                    ),
                )

    # Defensive completeness guard.
    finalized: list[dict[str, Any]] = []

    for index, item in enumerate(results):
        if item is None:
            item = _indexed_response(
                index,
                error_response(
                    claim=None,
                    source=None,
                    reason=("Batch result was not produced."),
                    error_type="INTERNAL_ERROR",
                ),
            )

        finalized.append(item)

    passed = sum(1 for item in finalized if item.get("verdict") == "PASS")

    warned = sum(1 for item in finalized if item.get("verdict") == "WARN")

    failed = sum(1 for item in finalized if item.get("verdict") == "FAIL")

    abstained = sum(1 for item in finalized if item.get("verdict") == "ABSTAIN")

    errors = sum(1 for item in finalized if item.get("ok") is False)

    return {
        "ok": True,
        "total": total,
        "passed": passed,
        "warned": warned,
        "failed": failed,
        "abstained": abstained,
        "errors": errors,
        "unique_sources": len(groups),
        "source_loads": source_loads,
        "bm25_indexes_built": bm25_indexes_built,
        "top_k": top_k,
        "pipeline_version": PIPELINE_VERSION,
        "results": finalized,
    }
