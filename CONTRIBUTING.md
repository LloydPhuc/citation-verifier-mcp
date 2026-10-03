# Contributing to Citation Verifier MCP

Thank you for your interest in contributing to Citation Verifier MCP! This document outlines the process for setting up a development environment, running tests, and submitting changes.

## Quick Start

### Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Windows 10/11 | — | Linux/macOS untested |
| Python | 3.13+ (3.12 minimum) | `py` launcher preferred |
| Docker Desktop | Latest | For GROBID (V1 features only) |
| Git | 2.x | For cloning and versioning |

### 1. Fork and Clone

```powershell
git clone https://github.com/<your-username>/citation-verifier-mcp.git
cd citation-verifier-mcp
git checkout -b fix/add-feature
```

### 2. Bootstrap the Environment

```powershell
.\scripts\bootstrap.ps1
```

This script:
- Creates an isolated `.venv` in the repository root
- Installs all dependencies from `requirements.txt`
- Pre-downloads the NLI model (`cross-encoder/nli-deberta-v3-small`)
- Runs import and compilation checks

**Force recreate:** `.\scripts\bootstrap.ps1 -Force`

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

Stop GROBID:
```powershell
.\scripts\stop.ps1
```

### 5. Install Dev Tools

The bootstrap script installs runtime dependencies only. Dev tools (ruff, mypy, pytest) are declared in `pyproject.toml` under `[project.optional-dependencies]` and must be installed separately:

```powershell
.venv\Scripts\pip install -e ".[dev]"
```

**Note:** The codebase currently contains pre-existing lint violations (35 as of this writing). New contributions should not introduce additional violations; fixing existing ones is appreciated.

---

## Development Workflow

### 1. Write Tests

Add tests to `tests/test_<module>.py`:

```powershell
# Unit tests for a specific module
.venv\Scripts\python -m pytest tests/test_<module>.py -m "unit and not slow" -v --basetemp=.\.pytest-tmp
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

### Test Markers

| Marker | Description | External Dependencies |
|--------|-------------|----------------------|
| `unit` | Fast tests with no external dependencies | None |
| `integration` | Tests requiring multiple components | Docker, network |
| `network` | Tests requiring internet access | Internet |
| `docker` | Tests requiring Docker/GROBID | Docker, GROBID |
| `slow` | Long-running tests (excluded by default with `-m "not slow"`) | Varies |
| `regression` | Regression coverage for known issues | Varies |

### Test Commands

```powershell
# Run all unit tests (recommended default)
.venv\Scripts\python -m pytest -m "unit and not slow" -q --basetemp=.\.pytest-tmp

# Run a specific test file
.venv\Scripts\python -m pytest tests/test_source_loader.py -m "unit and not slow" -v --basetemp=.\.pytest-tmp

# Run integration tests (requires Docker + GROBID)
.venv\Scripts\python -m pytest -m "integration" --basetemp=.\.pytest-tmp

# Run the smoke test (MCP discovery)
.\scripts\smoke_test.ps1
```

### NLI Model Tests

Tests requiring the NLI model are marked `not slow` and can run without network. The model is cached locally at `~/.cache/huggingface/hub/models/`.

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

- [ ] `ruff check .` passes with no errors
- [ ] `ruff format --check .` passes
- [ ] `mypy citation_v2/ server.py` passes
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
│   ├── source_loader.py           # Source resolution (arXiv, URL, PDF, text)
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
├── legacy/
│   └── server_v1_working.py       # V1 server (uses academic-refchecker CLI)
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
