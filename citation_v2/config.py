from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse


# ============================================================
# Environment parsing helpers
# ============================================================

def _env_str(name: str, default: str) -> str:
    """
    Read a string environment variable.

    Empty values are treated as missing so that:
        VAR=""
    does not accidentally override a valid default.
    """
    value = os.environ.get(name)

    if value is None:
        return default

    value = value.strip()

    return value if value else default


def _env_int(
    name: str,
    default: int,
    *,
    minimum: int | None = None,
) -> int:
    raw = os.environ.get(name)

    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = int(raw.strip())
        except ValueError as exc:
            raise RuntimeError(
                f"Environment variable {name} must be an integer, "
                f"got {raw!r}."
            ) from exc

    if minimum is not None and value < minimum:
        raise RuntimeError(
            f"Environment variable {name} must be >= {minimum}, "
            f"got {value}."
        )

    return value


def _env_float(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    raw = os.environ.get(name)

    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = float(raw.strip())
        except ValueError as exc:
            raise RuntimeError(
                f"Environment variable {name} must be numeric, "
                f"got {raw!r}."
            ) from exc

    if minimum is not None and value < minimum:
        raise RuntimeError(
            f"Environment variable {name} must be >= {minimum}, "
            f"got {value}."
        )

    if maximum is not None and value > maximum:
        raise RuntimeError(
            f"Environment variable {name} must be <= {maximum}, "
            f"got {value}."
        )

    return value


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)

    if raw is None or not raw.strip():
        path = default
    else:
        path = Path(
            os.path.expandvars(
                os.path.expanduser(raw.strip())
            )
        )

    return path.resolve()


# ============================================================
# Project root
# ============================================================

DEFAULT_BASE_DIR = Path(__file__).resolve().parent.parent

BASE_DIR = _env_path(
    "CITATION_MCP_HOME",
    DEFAULT_BASE_DIR,
)


# ============================================================
# Persistent paths
# ============================================================

DATA_DIR = BASE_DIR / "data"

DB_PATH = _env_path(
    "CITATION_MCP_DB_PATH",
    DATA_DIR / "citations.db",
)

LOG_DIR = BASE_DIR / "logs"


# ============================================================
# Cache paths
# ============================================================

CACHE_DIR = BASE_DIR / "cache"

RAW_CACHE_DIR = CACHE_DIR / "raw"
TEXT_CACHE_DIR = CACHE_DIR / "text"
SOURCE_CACHE_DIR = CACHE_DIR / "source"
TEMP_CACHE_DIR = CACHE_DIR / "temp"


# ============================================================
# Pipeline versioning
# ============================================================

PIPELINE_VERSION = "2.0.0"


# ============================================================
# GROBID
# ============================================================

GROBID_URL = _env_str(
    "GROBID_URL",
    "http://127.0.0.1:8070",
).rstrip("/")


# ============================================================
# Retrieval
# ============================================================

BM25_TOP_K = _env_int(
    "CITATION_BM25_TOP_K",
    5,
    minimum=1,
)


# ============================================================
# Chunking
# ============================================================

CHUNK_TARGET_CHARS = _env_int(
    "CITATION_CHUNK_TARGET_CHARS",
    4000,
    minimum=500,
)

CHUNK_OVERLAP_CHARS = _env_int(
    "CITATION_CHUNK_OVERLAP_CHARS",
    600,
    minimum=0,
)


# ============================================================
# NLI
# ============================================================

NLI_MODEL_ID = _env_str(
    "CITATION_NLI_MODEL",
    "cross-encoder/nli-deberta-v3-small",
)

NLI_ENTAILMENT_THRESHOLD = _env_float(
    "CITATION_NLI_ENTAILMENT_THRESHOLD",
    0.70,
    minimum=0.0,
    maximum=1.0,
)

NLI_CONTRADICTION_THRESHOLD = _env_float(
    "CITATION_NLI_CONTRADICTION_THRESHOLD",
    0.70,
    minimum=0.0,
    maximum=1.0,
)


# ============================================================
# Network
# ============================================================

HTTP_CONNECT_TIMEOUT_SECONDS = _env_int(
    "CITATION_HTTP_CONNECT_TIMEOUT",
    15,
    minimum=1,
)

HTTP_READ_TIMEOUT_SECONDS = _env_int(
    "CITATION_HTTP_READ_TIMEOUT",
    120,
    minimum=1,
)

HTTP_MAX_REDIRECTS = _env_int(
    "CITATION_HTTP_MAX_REDIRECTS",
    5,
    minimum=0,
)

MAX_SOURCE_DOWNLOAD_BYTES = _env_int(
    "CITATION_MAX_SOURCE_DOWNLOAD_BYTES",
    100 * 1024 * 1024,
    minimum=1024 * 1024,
)

HTTP_USER_AGENT = _env_str(
    "CITATION_HTTP_USER_AGENT",
    "CitationMCP/2.0 local-research-verifier",
)


# ============================================================
# Cache retention
# ============================================================

RAW_PDF_TTL_DAYS = _env_int(
    "CITATION_RAW_PDF_TTL_DAYS",
    7,
    minimum=0,
)

FAILED_TEMP_TTL_HOURS = _env_int(
    "CITATION_FAILED_TEMP_TTL_HOURS",
    24,
    minimum=0,
)


# ============================================================
# SQLite
# ============================================================

SQLITE_BUSY_TIMEOUT_MS = _env_int(
    "CITATION_SQLITE_BUSY_TIMEOUT_MS",
    5000,
    minimum=100,
)


# ============================================================
# Directory management
# ============================================================

REQUIRED_DIRECTORIES = (
    DATA_DIR,
    DB_PATH.parent,
    LOG_DIR,
    RAW_CACHE_DIR,
    TEXT_CACHE_DIR,
    SOURCE_CACHE_DIR,
    TEMP_CACHE_DIR,
)


def ensure_directories() -> None:
    """
    Create all required directories.

    Safe to call repeatedly.

    Raises RuntimeError if a required directory path already exists
    as a regular file or cannot be created.
    """

    for directory in REQUIRED_DIRECTORIES:

        if directory.exists() and not directory.is_dir():
            raise RuntimeError(
                f"Required directory path exists but is not a directory: "
                f"{directory}"
            )

        try:
            directory.mkdir(
                parents=True,
                exist_ok=True,
            )
        except OSError as exc:
            raise RuntimeError(
                f"Unable to create required directory: {directory}"
            ) from exc


# ============================================================
# Validation
# ============================================================

def validate_config() -> None:
    """
    Validate configuration invariants.

    This function performs no network access and does not load models.
    """

    if not BASE_DIR.exists():
        raise RuntimeError(
            f"Citation MCP base directory does not exist: {BASE_DIR}"
        )

    if not BASE_DIR.is_dir():
        raise RuntimeError(
            f"Citation MCP base path is not a directory: {BASE_DIR}"
        )

    if CHUNK_OVERLAP_CHARS >= CHUNK_TARGET_CHARS:
        raise RuntimeError(
            "CHUNK_OVERLAP_CHARS must be smaller than "
            "CHUNK_TARGET_CHARS."
        )

    if not NLI_MODEL_ID.strip():
        raise RuntimeError(
            "NLI_MODEL_ID cannot be empty."
        )

    parsed_grobid = urlparse(GROBID_URL)

    if parsed_grobid.scheme not in {"http", "https"}:
        raise RuntimeError(
            f"GROBID_URL must use http or https: {GROBID_URL}"
        )

    if not parsed_grobid.hostname:
        raise RuntimeError(
            f"GROBID_URL has no valid hostname: {GROBID_URL}"
        )

    if DB_PATH.exists() and DB_PATH.is_dir():
        raise RuntimeError(
            f"Database path points to a directory: {DB_PATH}"
        )


def initialize_runtime_paths() -> None:
    """
    Validate configuration and create filesystem directories.

    Call this explicitly during application/database startup.
    """

    validate_config()
    ensure_directories()


# ============================================================
# Diagnostics
# ============================================================

def runtime_summary() -> dict[str, object]:
    """
    Return non-secret runtime configuration for diagnostics.

    Do not add credentials or API keys here.
    """

    return {
        "pipeline_version": PIPELINE_VERSION,
        "base_dir": str(BASE_DIR),
        "database": str(DB_PATH),
        "cache_dir": str(CACHE_DIR),
        "grobid_url": GROBID_URL,
        "bm25_top_k": BM25_TOP_K,
        "chunk_target_chars": CHUNK_TARGET_CHARS,
        "chunk_overlap_chars": CHUNK_OVERLAP_CHARS,
        "nli_model": NLI_MODEL_ID,
        "nli_entailment_threshold": NLI_ENTAILMENT_THRESHOLD,
        "nli_contradiction_threshold": NLI_CONTRADICTION_THRESHOLD,
        "raw_pdf_ttl_days": RAW_PDF_TTL_DAYS,
        "failed_temp_ttl_hours": FAILED_TEMP_TTL_HOURS,
	"http_max_redirects": HTTP_MAX_REDIRECTS,
	"max_source_download_bytes": MAX_SOURCE_DOWNLOAD_BYTES,
    }