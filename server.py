import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from citation_v2.config import BM25_TOP_K

from citation_v2.batch import verify_claims_batch

from citation_v2.schemas import (
    abstain_response,
    error_response,
    verification_result_to_response,
)

from citation_v2.source_loader import (
    SourceCacheError,
    SourceDownloadError,
    SourceLoaderError,
    SourceSecurityError,
    UnsupportedSourceError,
)

from citation_v2.text_extractor import (
    PDFEncryptedError,
    PDFExtractionError,
    PDFNoTextError,
)

from citation_v2.verifier import (
    VerificationInputError,
    verify_claim as verify_claim_core,
)


# ============================================================
# Configuration
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

REFCHECKER_EXE = (
    BASE_DIR
    / ".venv"
    / "Scripts"
    / "academic-refchecker.exe"
)

mcp = MCPServer("Citation Verifier")


# ============================================================
# Helpers
# ============================================================

def normalize_source(source: str) -> str:
    source = os.path.expandvars(
        os.path.expanduser(source.strip())
    )

    path = Path(source)

    if path.exists():
        return str(path.resolve())

    return source


def build_environment() -> dict[str, str]:
    env = os.environ.copy()

    # Windows UTF-8
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["NO_COLOR"] = "1"

    # GROBID endpoint: respect user configuration, default to local instance.
    # 127.0.0.1 avoids localhost / IPv6 resolution issues.
    # Empty values are treated as missing (consistent with config._env_str).
    grobid_url = env.get("GROBID_URL")
    if grobid_url is not None:
        grobid_url = grobid_url.strip()
    if not grobid_url:
        grobid_url = "http://127.0.0.1:8070"
    env["GROBID_URL"] = grobid_url.rstrip("/")

    # Never send local GROBID traffic through a proxy.
    local_hosts = "localhost,127.0.0.1,::1"

    existing_no_proxy = env.get("NO_PROXY", "")
    if existing_no_proxy:
        env["NO_PROXY"] = f"{existing_no_proxy},{local_hosts}"
    else:
        env["NO_PROXY"] = local_hosts

    existing_no_proxy_lower = env.get("no_proxy", "")
    if existing_no_proxy_lower:
        env["no_proxy"] = f"{existing_no_proxy_lower},{local_hosts}"
    else:
        env["no_proxy"] = local_hosts

    return env


def load_json_report(
    report_path: Path,
) -> dict[str, Any] | None:

    if not report_path.exists():
        return None

    try:
        if report_path.stat().st_size == 0:
            return None
    except OSError:
        return None

    try:
        with report_path.open(
            "r",
            encoding="utf-8",
        ) as f:
            return json.load(f)

    except (OSError, json.JSONDecodeError):
        return None


# ============================================================
# RefChecker runner
# ============================================================

def run_refchecker(source: str) -> dict[str, Any]:
    source = normalize_source(source)

    if not REFCHECKER_EXE.exists():
        return {
            "ok": False,
            "source": source,
            "error": (
                "academic-refchecker.exe not found at "
                f"{REFCHECKER_EXE}"
            ),
        }

    # --------------------------------------------------------
    # IMPORTANT:
    # Store report beside server.py.
    #
    # We already know RefChecker successfully writes test.json
    # from this directory when run manually.
    # --------------------------------------------------------

    report_path = (
        BASE_DIR
        / f".mcp_report_{uuid.uuid4().hex}.json"
    )

    command = [
        str(REFCHECKER_EXE),
        "--paper",
        source,
        "--report-file",
        str(report_path),
        "--report-format",
        "json",
    ]

    env = build_environment()

    result = None
    success = False

    try:
        try:
            result = subprocess.run(
                command,
                cwd=str(BASE_DIR),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                env=env,
            )

        except subprocess.TimeoutExpired as exc:
            return {
                "ok": False,
                "source": source,
                "error": (
                    "RefChecker timed out after 600 seconds."
                ),
                "stdout": (
                    exc.stdout
                    if isinstance(exc.stdout, str)
                    else ""
                ),
                "stderr": (
                    exc.stderr
                    if isinstance(exc.stderr, str)
                    else ""
                ),
            }

        except OSError as exc:
            return {
                "ok": False,
                "source": source,
                "error": (
                    f"Failed to start RefChecker: {exc}"
                ),
            }

        # ----------------------------------------------------
        # Try reading report REGARDLESS of return code.
        # ----------------------------------------------------

        report = load_json_report(report_path)

        if report is not None:
            success = True

            response: dict[str, Any] = {
                "ok": True,
                "source": source,
                "report": report,
            }

            if result.returncode != 0:
                response["refchecker_returncode"] = (
                    result.returncode
                )

            return response

        # ----------------------------------------------------
        # Failure diagnostics.
        #
        # Do NOT lie with zero counts.
        # ----------------------------------------------------

        report_exists = report_path.exists()

        report_size = 0

        if report_exists:
            try:
                report_size = report_path.stat().st_size
            except OSError:
                pass

        return {
            "ok": False,
            "source": source,
            "returncode": result.returncode,
            "error": (
                "RefChecker did not produce a valid JSON report."
            ),
            "command": command,
            "report_path": str(report_path),
            "report_exists": report_exists,
            "report_size_bytes": report_size,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    finally:
        # Delete temporary report only after successful parse.
        #
        # On failure we deliberately keep the file so we can
        # inspect it.
        if success:
            try:
                report_path.unlink(missing_ok=True)
            except OSError:
                pass


# ============================================================
# Summary
# ============================================================

def normalize_summary(
    report: dict[str, Any],
) -> dict[str, Any]:

    summary = report.get("summary", {})

    total_refs = int(
        summary.get(
            "total_references_processed",
            0,
        )
        or 0
    )

    errors = int(
        summary.get(
            "total_errors_found",
            0,
        )
        or 0
    )

    warnings = int(
        summary.get(
            "total_warnings_found",
            0,
        )
        or 0
    )

    unverified = int(
        summary.get(
            "total_unverified_refs",
            0,
        )
        or 0
    )

    info = int(
        summary.get(
            "total_info_found",
            0,
        )
        or 0
    )

    # Deterministic health.
    if errors > 0 or unverified > 0:
        health = "Poor"

    elif warnings > 0:
        health = "Fair"

    else:
        health = "Good"

    return {
        "total_references_processed": total_refs,
        "total_errors": errors,
        "total_warnings": warnings,
        "total_unverified_references": unverified,
        "total_information": info,
        "citation_health": health,
    }


# ============================================================
# MCP Tools
# ============================================================

@mcp.tool()
def verify_document(
    source: str,
) -> dict[str, Any]:
    """
    Verify references in a paper.

    source may be:
    - arXiv ID
    - URL
    - DOI
    - PDF
    - BibTeX
    - LaTeX
    - text file
    """
    return run_refchecker(source)


@mcp.tool()
def verify_bibliography(
    path: str,
) -> dict[str, Any]:
    """
    Verify references in a local bibliography file.
    """

    expanded = os.path.expandvars(
        os.path.expanduser(path.strip())
    )

    resolved = Path(expanded)

    if not resolved.exists():
        return {
            "ok": False,
            "error": (
                f"File does not exist: {path}"
            ),
        }

    return run_refchecker(
        str(resolved.resolve())
    )


@mcp.tool()
def citation_summary(
    source: str,
) -> dict[str, Any]:
    """
    Verify a source and return normalized citation statistics.

    IMPORTANT:
    Consumers should use these values directly and must not
    infer missing values or recalculate citation health.
    """

    result = run_refchecker(source)

    if not result.get("ok"):
        return result

    report = result.get("report", {})

    summary = normalize_summary(report)

    return {
        "ok": True,
        "verification_succeeded": True,
        "source": source,
        **summary,
    }


@mcp.tool()
def verify_claim(
    claim: str,
    source: str,
    top_k: int = BM25_TOP_K,
) -> dict[str, Any]:
    """
    Verify whether one source supports one factual claim.

    This is a content-level citation verification tool.

    Pipeline:
        source resolution
        -> canonical full text
        -> BM25 retrieval
        -> DeBERTa NLI
        -> exact provenance verification
        -> deterministic verdict

    Verdicts:
        PASS
        WARN
        FAIL
        ABSTAIN

    PASS is forbidden unless evidence provenance is verified.

    Parameters
    ----------
    claim:
        Factual claim to verify.

    source:
        Local PDF path, arXiv identifier, arXiv URL,
        or supported direct PDF URL.

    top_k:
        Number of BM25 source chunks to inspect.
    """

    if not isinstance(claim, str):
        return error_response(
            claim=None,
            source=(
                source
                if isinstance(source, str)
                else None
            ),
            reason="claim must be a string.",
            error_type="INVALID_INPUT",
        )

    if not isinstance(source, str):
        return error_response(
            claim=claim,
            source=None,
            reason="source must be a string.",
            error_type="INVALID_INPUT",
        )

    clean_claim = claim.strip()
    clean_source = source.strip()

    if not clean_claim:
        return error_response(
            claim=claim,
            source=clean_source,
            reason="claim cannot be empty.",
            error_type="INVALID_INPUT",
        )

    if not clean_source:
        return error_response(
            claim=clean_claim,
            source=source,
            reason="source cannot be empty.",
            error_type="INVALID_INPUT",
        )

    if (
        not isinstance(top_k, int)
        or isinstance(top_k, bool)
        or top_k <= 0
    ):
        return error_response(
            claim=clean_claim,
            source=clean_source,
            reason="top_k must be a positive integer.",
            error_type="INVALID_INPUT",
        )

    if top_k > 20:
        return error_response(
            claim=clean_claim,
            source=clean_source,
            reason="top_k cannot exceed 20.",
            error_type="INVALID_INPUT",
        )

    try:
        result = verify_claim_core(
            clean_claim,
            clean_source,
            top_k=top_k,
            persist=True,
        )

        response = verification_result_to_response(
            result,
            top_k=top_k,
        )

        # Final MCP boundary invariant:
        # never expose PASS without grounded provenance.
        if response.get("verdict") == "PASS":
            evidence = response.get("evidence")

            if (
                not isinstance(evidence, dict)
                or evidence.get("provenance_verified") is not True
            ):
                return abstain_response(
                    claim=clean_claim,
                    source=clean_source,
                    source_state="FULL_TEXT",
                    reason="PASS_BLOCKED_BY_PROVENANCE_GATE",
                    error_type="PROVENANCE_FAILURE",
                )

        return response

    # Unsupported source type, e.g. DOI full-text resolution
    # is not implemented yet. This is NOT evidence against claim.
    except UnsupportedSourceError as exc:
        return abstain_response(
            claim=clean_claim,
            source=clean_source,
            source_state="UNSUPPORTED_SOURCE",
            reason=str(exc),
            error_type=type(exc).__name__,
        )

    # Source acquisition failures are ABSTAIN, not FAIL.
    except SourceSecurityError as exc:
        return abstain_response(
            claim=clean_claim,
            source=clean_source,
            source_state="BLOCKED_SOURCE",
            reason=str(exc),
            error_type=type(exc).__name__,
        )

    except SourceDownloadError as exc:
        return abstain_response(
            claim=clean_claim,
            source=clean_source,
            source_state="SOURCE_UNAVAILABLE",
            reason=str(exc),
            error_type=type(exc).__name__,
        )

    except SourceCacheError as exc:
        return abstain_response(
            claim=clean_claim,
            source=clean_source,
            source_state="CACHE_ERROR",
            reason=str(exc),
            error_type=type(exc).__name__,
        )

    except SourceLoaderError as exc:
        return abstain_response(
            claim=clean_claim,
            source=clean_source,
            source_state="SOURCE_UNAVAILABLE",
            reason=str(exc),
            error_type=type(exc).__name__,
        )

    # Full text exists but cannot be reliably extracted.
    except PDFEncryptedError as exc:
        return abstain_response(
            claim=clean_claim,
            source=clean_source,
            source_state="ENCRYPTED_PDF",
            reason=str(exc),
            error_type=type(exc).__name__,
        )

    except PDFNoTextError as exc:
        return abstain_response(
            claim=clean_claim,
            source=clean_source,
            source_state="NO_EXTRACTABLE_TEXT",
            reason=str(exc),
            error_type=type(exc).__name__,
        )

    except PDFExtractionError as exc:
        return abstain_response(
            claim=clean_claim,
            source=clean_source,
            source_state="EXTRACTION_FAILED",
            reason=str(exc),
            error_type=type(exc).__name__,
        )

    except VerificationInputError as exc:
        return error_response(
            claim=clean_claim,
            source=clean_source,
            reason=str(exc),
            error_type=type(exc).__name__,
        )

    # Unexpected bug: never turn an internal exception into PASS/FAIL,
    # and do not expose a Python traceback through MCP.
    except Exception as exc:
        return error_response(
            claim=clean_claim,
            source=clean_source,
            reason=(
                "Internal verification error: "
                f"{type(exc).__name__}"
            ),
            error_type="INTERNAL_ERROR",
        )


@mcp.tool()
def verify_claims(
    claims: list[dict[str, Any]],
    top_k: int = BM25_TOP_K,
) -> dict[str, Any]:
    """
    Verify multiple claim/source pairs in one MCP call.

    Input example:
        [
            {
                "claim": "Claim A",
                "source": "2607.22693"
            },
            {
                "claim": "Claim B",
                "source": "2607.22693"
            }
        ]

    Claims sharing the same source reuse:
    - one loaded canonical source,
    - one persisted chunk set,
    - one BM25 index,
    - the process-wide NLI model.

    One failing item does not abort the rest of the batch.
    """

    if (
        not isinstance(top_k, int)
        or isinstance(top_k, bool)
        or top_k <= 0
    ):
        return {
            "ok": False,
            "error_type": "INVALID_INPUT",
            "reason": (
                "top_k must be a positive integer."
            ),
        }

    if top_k > 20:
        return {
            "ok": False,
            "error_type": "INVALID_INPUT",
            "reason": (
                "top_k cannot exceed 20."
            ),
        }

    try:
        return verify_claims_batch(
            claims,
            top_k=top_k,
            persist=True,
        )

    except ValueError as exc:
        return {
            "ok": False,
            "error_type": "INVALID_INPUT",
            "reason": str(exc),
        }

    except Exception as exc:
        return {
            "ok": False,
            "error_type": "INTERNAL_ERROR",
            "reason": (
                "Internal batch verification error: "
                f"{type(exc).__name__}"
            ),
        }


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    mcp.run()
