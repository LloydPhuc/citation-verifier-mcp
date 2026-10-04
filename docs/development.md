# Development Guide

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Windows | Windows 11 tested | Windows 10, Linux/macOS not independently verified |
| Python | 3.13+ | `py` launcher preferred |
| Docker Desktop | Latest | For GROBID (V1 PDF parsing; not V2) |
| Git | 2.x | For cloning and versioning |

## Setting Up the Development Environment

### 1. Clone the Repository

```powershell
git clone https://github.com/<your-username>/citation-verifier-mcp.git
cd citation-verifier-mcp
```

### 2. Bootstrap the Virtual Environment

For an existing checkout, inspect `.venv` ownership/version and follow the recovery precautions below before running bootstrap; an incomplete environment can be deleted by the script.

```powershell
.\scripts\bootstrap.ps1
```

This script:
- Creates an isolated `.venv` in the repository root
- Installs all dependencies from `requirements.txt`
- Pre-downloads the NLI model (`cross-encoder/nli-deberta-v3-small`)
- Runs import and compilation checks

**Supported Python:** `pyproject.toml` requires >=3.13; historical regression used 3.13.7. Bootstrap currently accepts 3.12, may select the launcher default instead of the probed 3.13, and does not validate a reused venv version. Check `.\.venv\Scripts\python.exe --version` before use. Executable compatibility defects require a separate fix before publication.

**Environment recovery:** Diagnose first. Bootstrap changes installed packages and deletes an incomplete existing `.venv`; `-Force` deletes and recreates it. Confirm the resolved path is this checkout's private environment, stop clients using it, record installed packages and preserve custom files in a separate backup before recovery. Prefer a fresh checkout when ownership is uncertain.

**Model preparation:** Bootstrap attempts to cache the tokenizer and model. Its warning about downloading on first verification is inaccurate: runtime uses `local_files_only=True`. Resolve setup/cache errors before V2 verification.

**If model download stalls:**
```powershell
$env:HF_HUB_DISABLE_XET=1
.\scripts\bootstrap.ps1
```

### 3. Verify the Environment

```powershell
.\scripts\doctor.ps1
```

This checks: Python, `.venv`, required modules, RefChecker executable, Docker CLI, Docker Engine, GROBID health, and MCP tool discovery. The final line will be `OVERALL: READY`, `OVERALL: PARTIALLY READY`, or `OVERALL: NOT READY`.

### 4. Start GROBID (for V1 RefChecker features)

```powershell
.\scripts\start.ps1
```

GROBID is only needed for `citation_summary` and `verify_document`/`verify_bibliography` (V1 features). The V2 `verify_claim` and `verify_claims` tools do not require GROBID.

Before starting or restarting, inspect endpoint/container ownership. A healthy external service can be reused only with its owner's approval. Confirm the managed container belongs to this checkout and is not shared; its Compose label alone does not establish exclusive ownership.

Stop only your exclusively owned managed GROBID:
```powershell
.\scripts\stop.ps1
```

## Testing

### Unit Tests

Unit tests are fast and do not require network access or Docker.

```powershell
# Run all unit tests (fast, no network/Docker)
.venv\Scripts\python -m pytest tests/ -m "unit and not slow" -q --basetemp=.\.pytest-tmp

# Run tests for a specific module
.venv\Scripts\python -m pytest tests/test_batch.py -m "unit and not slow" -v --basetemp=.\.pytest-tmp
```

### Integration Tests

The `integration` marker means multiple components, not necessarily external services. Current deterministic tests use synthetic files and mocked downloads/NLI. A full pytest run does not establish live network/GROBID integration coverage.

```powershell
.venv\Scripts\python -m pytest tests/ -m "integration" -q --basetemp=.\.pytest-tmp
```

### Full Test Suite

```powershell
.venv\Scripts\python -m pytest tests/ -q --basetemp=.\.pytest-tmp
```

Historical evidence: TASK 24R recorded **547 passed** on Windows 11 / Python 3.13.7 with isolated writable temporary paths, separately from live V1/GROBID and V2/arXiv checks. These results are not rerun here. Markers are registered in `pyproject.toml`; current tests have no `network`, `docker`, `slow` or `integration` decorators. Inspect collection before treating marker selection as live coverage.

### Test Markers

| Marker | Description |
|---|---|
| `unit` | Fast tests with no external dependencies |
| `integration` | Tests requiring multiple components; may be deterministic |
| `network` | Tests requiring internet access |
| `docker` | Tests requiring Docker |
| `slow` | Long-running tests (excluded only when explicitly selected out) |
| `regression` | Regression coverage for known issues |

### Running Tests on Windows

**Important:** The default pytest temp directory (`C:\Users\...\AppData\Local\Temp\pytest-of-user`) may have permission issues. Always specify `--basetemp` with a writable path:

```powershell
.venv\Scripts\python -m pytest tests/ -m "unit and not slow" -q --basetemp=.\.pytest-tmp
```

Use a dedicated disposable `--basetemp`: pytest may delete its contents. Never use production data. `tests/conftest.py` uses `setdefault` for test home/database variables, preserving inherited values; use a separate test shell and dedicated paths.

### Smoke Test

```powershell
.\scripts\smoke_test.ps1
```

Verifies MCP server startup and tool discovery.

## Project Structure

```
citation-verifier-mcp/
├── server.py                      # MCP server entry point
├── citation_v2/                   # V2 verification pipeline
│   ├── __init__.py
│   ├── config.py                  # Environment-driven configuration
│   ├── source_loader.py           # Source resolution
│   ├── text_extractor.py          # PDF text extraction (pdfplumber)
│   ├── chunker.py                 # Text chunking and validation
│   ├── cache.py                   # File caching
│   ├── database.py                # SQLite persistence
│   ├── retrieval.py               # BM25 retrieval (rank-bm25)
│   ├── nli.py                     # NLI inference (transformers/PyTorch)
│   ├── provenance.py              # Exact provenance verification
│   ├── verifier.py                # Core pipeline + decision policy
│   ├── batch.py                   # Batch processing
│   ├── schemas.py                 # Public response schemas
│   └── normalizer.py              # Text normalization
├── tests/                         # pytest test suite
│   ├── conftest.py                # Shared fixtures
│   └── test_*.py                  # Module-specific tests
├── scripts/                       # PowerShell scripts
│   ├── bootstrap.ps1              # Environment setup
│   ├── doctor.ps1                 # Environment diagnostics
│   ├── start.ps1                  # Start GROBID
│   ├── stop.ps1                   # Stop GROBID
│   ├── smoke_test.ps1             # MCP discovery test
│   └── print_kilo_config.ps1      # Generate Kilo config snippet
├── docs/                          # Documentation
│   ├── architecture.md
│   ├── verdicts.md
│   ├── limitations.md
│   ├── development.md
│   ├── troubleshooting.md
│   └── kilo-setup.md
├── requirements.txt               # Python dependencies
├── pyproject.toml                 # Project metadata and pytest config
└── README.md                      # Project overview
```

## Code Style

- Python 3.13+ with `from __future__ import annotations`
- Type hints required on all public functions
- Use `dataclasses` for structured results (`frozen=True` for immutable results)
- No comments unless they explain **why**, not **what**
- Linting: `ruff` (configured in `pyproject.toml`)

```powershell
# Lint
.venv\Scripts\ruff check .

# Format check
.venv\Scripts\ruff format --check .
```

Full-project Ruff has known pre-existing failures (historical TASK 24R: 33); the baseline is not lint-clean. Require no new violations in contributions. Historical mypy also reported failures; no current full-project pass is claimed.

## Configuration

All configuration is environment-driven. See [Architecture](architecture.md#environment-variables) for the full list. Key variables for development:

```powershell
# Use a separate test database
$env:CITATION_MCP_DB_PATH = ".\data\test_citations.db"

# Use temporary cache directory
$env:CITATION_MCP_HOME = ".\tmp_dev_home"

# Adjust NLI thresholds for testing
$env:CITATION_NLI_ENTAILMENT_THRESHOLD = "0.60"
```

## Test-Driven Development

1. Write a failing test in `tests/test_<module>.py`
2. Run it to confirm failure: `.\.venv\Scripts\python -m pytest tests/test_batch.py -k "same_source" -v --basetemp=.\.pytest-tmp`
3. Implement the fix in `citation_v2/<module>.py`
4. Run again to confirm pass
5. Run the full unit suite: `.\.venv\Scripts\python -m pytest tests/ -m "unit and not slow" -q --basetemp=.\.pytest-tmp`
6. Run linter: `.\.venv\Scripts\ruff check .`

## Database Schema

- SQLite at `CITATION_MCP_DB_PATH` (default: `data/citations.db`)
- Schema version: 1 (stored in `schema_meta` table; verified at init)
- Tables: `papers`, `chunks`, `claims`, `verifications`, `schema_meta`, `bibliography_runs`
- Papers and chunks are keyed by content hash for deduplication
- Re-verifying the same source reuses cached chunks (no re-chunking)

## NLI Model

- **Model:** `cross-encoder/nli-deberta-v3-small`
- **Cache location:** `~/.cache/huggingface/hub/models/`
- **Size:** ~170 MB
- **Framework:** PyTorch CPU-only
- **Singleton:** Loaded once per process via `get_nli_engine()`
- **Setup:** Bootstrap attempts the download; runtime uses cached files only. Duration depends on connection and cache state.

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b fix/add-feature`
3. Write tests (unit + integration as appropriate)
4. Implement the feature
5. Run `ruff check .`; document existing failures and require no new violations
6. Ensure all unit tests pass: `.\.venv\Scripts\python -m pytest tests/ -m "unit and not slow" -q --basetemp=.\.pytest-tmp`
7. Commit with a descriptive message
8. Open a pull request

## Building from Source

No build step is required. The project is pure Python. The MCP server is launched directly:

```powershell
.venv\Scripts\python server.py
```

The server communicates via stdio JSON-RPC (MCP protocol). It does not listen on a network port.
