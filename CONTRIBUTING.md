# Contributing to RefSentry — Citation Verifier MCP

Thank you for your interest in contributing to RefSentry! This document outlines the process for setting up a development environment, running tests, and submitting changes.

## Quick Start

### Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Windows | Windows 11 tested | Windows 10, Linux/macOS not independently verified |
| Python | 3.13+ | `py` launcher preferred |
| Docker Desktop | Latest | For GROBID (V1 features only) |
| Git | 2.x | For cloning and versioning |

### 1. Fork and Clone

Fork [LloydPhuc/citation-verifier-mcp](https://github.com/LloydPhuc/citation-verifier-mcp), then replace `<your-username>` below with your GitHub username to clone your fork.

```powershell
git clone https://github.com/<your-username>/citation-verifier-mcp.git
cd citation-verifier-mcp
git checkout -b fix/add-feature
```

### 2. Bootstrap the Environment

For an existing checkout, inspect `.venv` ownership/version and follow the recovery precautions below before running bootstrap. Without `-Force`, unsupported, broken or incomplete environments are preserved and rejected.

```powershell
.\scripts\bootstrap.ps1
```

This script:
- Creates an isolated `.venv` in the repository root
- Installs all dependencies from `requirements.txt`
- Pre-downloads the NLI model (`cross-encoder/nli-deberta-v3-small`)
- Runs import and compilation checks

**Supported Python:** `pyproject.toml` and bootstrap require >=3.13. Bootstrap resolves and retains the actual interpreter selected through `py -3.13`, or uses a validated fallback interpreter. It checks the selected interpreter before environment creation and the environment's own Python before reuse and package installation. Python 3.13.7 on Windows 11 is the independently verified application environment.

**Environment recovery:** Diagnose first. Bootstrap can change installed packages when reusing a supported environment. Unsupported, broken or incomplete existing environments require an explicit recovery choice; they are not silently deleted. `-Force` deletes and recreates `.venv` only after validating the selected interpreter and expected checkout path; a linked root `.venv` is rejected. These checks do not establish ownership or create backups. Confirm exclusive ownership, stop clients, record installed packages and preserve the environment in a separate backup before choosing `-Force`. Prefer a fresh checkout when ownership is uncertain.

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

The final line will be `OVERALL: READY`, `OVERALL: PARTIALLY READY`, or `OVERALL: NOT READY`.

### 4. Start GROBID (for V1 features)

```powershell
.\scripts\start.ps1
```

Before starting or restarting, inspect endpoint/container ownership. A healthy external service can be reused only with its owner's approval. Confirm the managed container belongs to this checkout and is not shared; its Compose label alone does not establish exclusive ownership.

Stop only your exclusively owned managed GROBID:
```powershell
.\scripts\stop.ps1
```

### 5. Install Dev Tools

The bootstrap script installs runtime dependencies only. Dev tools (ruff, mypy, pytest) are declared in `pyproject.toml` under `[project.optional-dependencies]` and must be installed separately:

```powershell
.venv\Scripts\pip install -e ".[dev]"
```

**Note:** The codebase currently contains pre-existing lint violations (33 reported by the historical TASK 24R audit; not rerun here). New contributions should not introduce additional violations; fixing existing ones is appreciated.

---

## Development Workflow

### 1. Write Tests

Add tests to `tests/test_<module>.py`:

```powershell
# Unit tests for a specific module
.venv\Scripts\python -m pytest tests/test_batch.py -m "unit and not slow" -v --basetemp=.\.pytest-tmp
```

### 2. Implement the Change

Edit the relevant file in `citation_v2/` or `server.py`. Follow the code style below.

### 3. Lint and Type-Check

```powershell
# Lint
.venv\Scripts\ruff check .

# Format check
.venv\Scripts\ruff format --check .

# Type check
.venv\Scripts\mypy citation_v2/ server.py
```

### 4. Run Tests

```powershell
# Unit tests (fast, no network/Docker)
.venv\Scripts\python -m pytest -m "unit and not slow" -q --basetemp=.\.pytest-tmp

# Full test suite
.venv\Scripts\python -m pytest -q --basetemp=.\.pytest-tmp
```

**Windows temp workaround:** The default pytest temp directory (`C:\Users\...\AppData\Local\Temp\pytest-of-user`) may have permission issues. Always specify `--basetemp` with a writable path like `.\.pytest-tmp`.

Use a dedicated disposable `--basetemp`: pytest may delete its contents. In a separate test shell, verify `CITATION_MCP_HOME` and `CITATION_MCP_DB_PATH` point to disposable test data; `tests/conftest.py` preserves inherited values. Never use production paths.

### 5. Commit and Push

```powershell
git add .
git commit -m "fix: resolve source-loader timeout on large PDFs"
git push origin fix/add-feature
```

Commit messages should follow [Conventional Commits](https://www.conventionalcommits.org/):

| Type | Use when |
|------|----------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `test` | Adding or fixing tests |
| `chore` | Maintenance (deps, configs, tooling) |

### 6. Open a Pull Request

1. Push to your fork and open a PR against `main`.
2. Select the appropriate template.
3. Ensure all CI checks pass.
4. Request review from a maintainer.

---

## Testing Guide

Historical evidence: TASK 24R recorded **547 passed** on Windows 11 / Python 3.13.7 with isolated writable temporary paths, separately from live V1/GROBID and V2/arXiv checks. These results are not rerun here. Markers are registered in `pyproject.toml`; current tests have no `network`, `docker`, `slow` or `integration` decorators. Inspect collection before treating marker selection as live coverage.

### Test Markers

| Marker | Description | External Dependencies |
|--------|-------------|----------------------|
| `unit` | Fast tests with no external dependencies | None |
| `integration` | Multiple-component tests; may use mocks | Depends on the test |
| `network` | Tests requiring internet access | Internet |
| `docker` | Tests requiring Docker/GROBID | Docker, GROBID |
| `slow` | Long-running tests (exclude explicitly with `-m "not slow"`) | Varies |
| `regression` | Regression coverage for known issues | Varies |

### Test Commands

```powershell
# Run all unit tests (recommended default)
.venv\Scripts\python -m pytest -m "unit and not slow" -q --basetemp=.\.pytest-tmp

# Run a specific test file
.venv\Scripts\python -m pytest tests/test_source_loader.py -m "unit and not slow" -v --basetemp=.\.pytest-tmp

# Select integration-marked tests; inspect collection and fixtures first
.venv\Scripts\python -m pytest -m "integration" --basetemp=.\.pytest-tmp

# Run the smoke test (MCP discovery)
.\scripts\smoke_test.ps1
```

### NLI Model Tests

`not slow` is a selection expression, not a marker. Current NLI tests exercise validation/label helpers and pipeline tests use mocked scoring; they do not prove live model inference. A separate live inference check requires cached tokenizer/model files. Hugging Face uses its hub cache (commonly `~/.cache/huggingface/hub/`; environment settings can override it).

---

## Code Style

- **Python 3.13+** with `from __future__ import annotations`
- **Type hints** required on all public functions
- Use `dataclasses` for structured results (`frozen=True` for immutable results)
- **No comments** unless they explain **why**, not **what**
- **Linting:** `ruff` (configured in `pyproject.toml`)
- **Formatting:** `ruff format` (4-space indent, double quotes, LF line endings — configured in `pyproject.toml`)

### Pre-commit Checklist

Before submitting a PR, ensure:

- [ ] Run `ruff check .`; document the pre-existing baseline and introduce no new violations
- [ ] `ruff format --check .` passes
- [ ] Run `mypy citation_v2/ server.py`; document existing debt and introduce no new type errors
- [ ] All unit tests pass: `.venv\Scripts\python -m pytest -m "unit and not slow" -q --basetemp=.\.pytest-tmp`
- [ ] New code is covered by tests
- [ ] No files in `.gitignore` are committed
- [ ] No secrets, API keys, or credentials are introduced

---

## Project Structure

```
citation-verifier-mcp/
├── server.py                      # MCP server entry point
├── citation_v2/                   # V2 verification pipeline
│   ├── config.py                  # Environment-driven configuration
│   ├── source_loader.py           # Source resolution (arXiv, public direct PDF URL, local PDF)
│   ├── text_extractor.py          # PDF text extraction (pdfplumber)
│   ├── chunker.py                 # Text splitting and validation
│   ├── cache.py                   # File caching (raw + normalized text)
│   ├── database.py                # SQLite persistence layer
│   ├── retrieval.py               # BM25 lexical retrieval
│   ├── nli.py                     # Local DeBERTa NLI inference
│   ├── provenance.py              # Exact provenance verification
│   ├── verifier.py                # Core pipeline + decision policy
│   ├── batch.py                   # Batch processing with source reuse
│   ├── schemas.py                 # Public MCP response schemas
│   └── normalizer.py              # Text normalization
├── tests/                         # pytest test suite (unit + integration)
├── scripts/                       # PowerShell scripts
├── docs/                          # Documentation
├── pyproject.toml                 # Project metadata and pytest/ruff/mypy config
└── README.md                      # Project overview
```

---

## Configuration

All configuration is environment-driven. See [Architecture](docs/architecture.md#environment-variables) for the full list.

Key variables for development:

```powershell
# Use a separate test database
$env:CITATION_MCP_DB_PATH = ".\data\test_citations.db"

# Use temporary cache directory
$env:CITATION_MCP_HOME = ".\tmp_dev_home"

# Adjust NLI thresholds for testing
$env:CITATION_NLI_ENTAILMENT_THRESHOLD = "0.60"
```

---

## License

By contributing, you agree that your contributions will be licensed under the MIT License (see `LICENSE`). You represent that you have the right to submit your contribution and that it does not violate any third-party license or contain AGPL-3.0-only code (e.g., PyMuPDF).

Third-party licensing: see `THIRD_PARTY.md` for the complete inventory.
