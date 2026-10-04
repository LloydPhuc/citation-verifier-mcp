# Third-Party Licenses

This file documents all third-party components used by the Citation Verifier MCP
project, their licenses, and the project's relationship to each.

**Project license:** MIT (for project-owned code only — see `LICENSE`)

**Copyright holder:** Huu Phuc Le
**Year:** 2026

**License inventory recorded:** 2026-10-02
**Runtime/publication descriptions reviewed:** 2026-10-04

---

## Overview

The Citation Verifier MCP distributes **only its own source code**. All
third-party components — Python packages, Docker images, and machine-learning
model weights — are installed or downloaded by the end user during setup or explicit service startup. None
are vendored or bundled into this repository.

Third-party components remain under their respective licenses. The MIT license
applied to project-owned code does **not** relicense third-party packages,
model weights, or external services.

---

## Direct Runtime Dependencies

Listed in `requirements.txt`. Bootstrap installs the CPU-only PyTorch build from the PyTorch CPU index before the remaining requirements; a manual requirements install needs that index as documented in [README](README.md#dependencies).

### 1. pdfplumber

| Field | Value |
|---|---|
| **Component** | pdfplumber |
| **Version** | 0.11.10 |
| **License** | MIT |
| **Author** | Jeremy Singer-Vine |
| **Package source** | PyPI: `pdfplumber==0.11.10` |
| **License source** | PyPI classifier (MIT); verified license file in `pdfplumber-0.11.10.dist-info/licenses/LICENSE.txt` (MIT, Copyright (c) 2015, Jeremy Singer-Vine) |
| **How used** | Imported as `import pdfplumber` in `citation_v2/text_extractor.py` — primary PDF text extraction |
| **Replaces** | PyMuPDF (AGPL-3.0) — see Removed Dependencies below |
| **Redistributed?** | No — installed via pip |
| **Obligations** | MIT — copyright notice retention only. No copyleft. |

**License file content (verified):**
> The MIT License (MIT)
> Copyright (c) 2015, Jeremy Singer-Vine
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction...

### 2. MCP Python SDK (mcp)

| Field | Value |
|---|---|
| **Component** | MCP (Model Context Protocol) Python SDK |
| **Version** | 2.2.0 |
| **License** | MIT |
| **Author** | Model Context Protocol (a Series of LF Projects, LLC) |
| **Package source** | PyPI: `mcp==2.2.0` |
| **License source** | PyPI metadata (`License: MIT`); license file in `mcp-2.2.0.dist-info/licenses/LICENSE` (MIT, Copyright (c) 2024 Anthropic, PBC) |
| **How used** | Imported as `from mcp.server import MCPServer` in `server.py` — MCP server framework |
| **Redistributed?** | No — installed via pip |
| **Obligations** | MIT — copyright notice retention only. |

### 3. rank-bm25

| Field | Value |
|---|---|
| **Component** | rank-bm25 (BM25 retrieval algorithms) |
| **Version** | 0.2.2 |
| **License** | Apache License 2.0 |
| **Author** | D. Brown |
| **Package source** | PyPI: `rank-bm25==0.2.2` |
| **License source** | PyPI metadata; license file in `rank_bm25-0.2.2.dist-info/licenses/LICENSE` (Apache-2.0) |
| **How used** | Imported as `from rank_bm25 import BM25Okapi` in `citation_v2/retrieval.py` — BM25 lexical retrieval |
| **Redistributed?** | No — installed via pip |
| **Obligations** | Apache 2.0 — notice retention if redistributing; patent grant included. No copyleft. |

### 4. requests

| Field | Value |
|---|---|
| **Component** | Requests: HTTP for Humans |
| **Version** | 2.34.2 |
| **License** | Apache License 2.0 |
| **Author** | Kenneth Reitz |
| **Package source** | PyPI: `requests==2.34.2` |
| **License source** | PyPI metadata; license file in package `requests-2.34.2.dist-info/licenses/LICENSE` (Apache-2.0) |
| **How used** | Imported in `citation_v2/source_loader.py` — HTTP downloads for source/document loading |
| **Redistributed?** | No — installed via pip |
| **Obligations** | Apache 2.0 — notice retention if redistributing; patent grant included. |

### 5. PyTorch (torch) — CPU-only build

| Field | Value |
|---|---|
| **Component** | PyTorch (CPU-only build) |
| **Version** | 2.14.0+cpu |
| **License** | Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND MIT |
| **Author** | PyTorch Team |
| **Package source** | PyTorch CPU index: `torch==2.14.0+cpu` |
| **License source** | PyPI metadata (License-Expression); <https://pytorch.org> |
| **How used** | Imported as `import torch` in `citation_v2/nli.py` — NLI inference backend |
| **Redistributed?** | No — installed via pip |
| **Obligations** | Composite license: primarily Apache 2.0; LLVM exception for some components; BSD for others. Retain applicable notices when redistributing; consult the component license files. |

**Note:** The CPU-only build (`+cpu`) is installed from the PyTorch CPU index.
The project requires no GPU support.

### 6. Transformers (transformers)

| Field | Value |
|---|---|
| **Component** | Transformers (machine learning model framework) |
| **Version** | 5.17.0 |
| **License** | Apache License 2.0 |
| **Author** | The Hugging Face team |
| **Package source** | PyPI: `transformers==5.17.0` |
| **License source** | PyPI metadata; license file (Apache-2.0, Copyright 2018- The Hugging Face team) |
| **How used** | Imported in `citation_v2/nli.py` — DeBERTa NLI model loading and inference |
| **Redistributed?** | No — installed via pip |
| **Obligations** | Apache 2.0 — notice retention if redistributing; patent grant included. |

### 7. SentencePiece (sentencepiece)

| Field | Value |
|---|---|
| **Component** | SentencePiece (unsupervised text tokenizer) |
| **Version** | 0.2.2 |
| **License** | Apache License 2.0 |
| **Author** | Taku Kudo (Google) |
| **Package source** | PyPI: `sentencepiece==0.2.2` |
| **License source** | PyPI metadata (License-Expression: Apache-2.0); <https://github.com/google/sentencepiece> |
| **How used** | Required by transformers for DeBERTa tokenizer |
| **Redistributed?** | No — installed via pip as a declared direct dependency |
| **Obligations** | Apache 2.0 — no copyleft. |

---

## External CLI Tool

### 8. academic-refchecker

| Field | Value |
|---|---|
| **Component** | Academic RefChecker |
| **Version** | 3.0.190 |
| **License** | MIT |
| **Author** | Mark Russinovich |
| **Source** | PyPI: `academic-refchecker==3.0.190`; GitHub: `markrussinovich/refchecker` |
| **License source** | PyPI metadata (License-Expression: MIT); verified license file in dist-info (MIT, Copyright (c) 2025 RefChecker) |
| **How used** | Invoked as external CLI via `subprocess.run()` in `server.py` (not imported as a Python module) |
| **Installed** | Via bootstrap.ps1 (`pip install academic-refchecker==3.0.190`) into user's `.venv` |
| **Redistributed?** | No — installed into user's `.venv` via bootstrap.ps1 |
| **Obligations** | MIT; see the component license text for redistribution terms. |

**Important distinction:** The project invokes `academic-refchecker.exe` as a
**separate external process** via `subprocess.run()`. It does not import or
link to the library directly. This creates a process boundary. The project's
MIT code does not incorporate academic-refchecker's source.

**Important compliance note:** Academic RefChecker depends on two GPL-licensed
packages in its dependency tree:
- `fuzzywuzzy==0.18.0` — **GNU General Public License v2 (GPLv2)**
- `python-Levenshtein==0.27.5` / `Levenshtein==0.27.5` — **GNU GPL-2.0-or-later**

These packages are installed into the same `.venv` as RefChecker. The server invokes RefChecker as a subprocess; that is an implementation fact, not a determination of GPL compatibility. The publication repository does not bundle RefChecker or these dependencies. Redistribution of a complete environment or other combined package requires a separate review of the applicable licenses.

---

## Docker Services

### 9. GROBID (Docker Image)

| Field | Value |
|---|---|
| **Component** | GROBID (GeneRation Of BIbliographic Data) |
| **Image** | `grobid/grobid:0.9.1-crf` |
| **Version** | 0.9.1-crf |
| **License** | Apache License 2.0 |
| **Author** | Patrice Lopez (Science-miner) |
| **Source** | GitHub: <https://github.com/grobidOrg/grobid>; Docker Hub: `grobid/grobid` |
| **License source** | <https://github.com/grobidOrg/grobid> (LICENSE file: Apache-2.0) |
| **How used** | Run as a Docker container via `docker-compose.yml`; accessed via HTTP REST API at `http://127.0.0.1:8070` |
| **Redistributed?** | No — users run the official Docker image via Docker Compose |
| **Obligations** | Apache 2.0 — documentation is CC-0; data is CC-BY. No copyleft. |

**Note:** GROBID is only required for V1 RefChecker features
(`citation_summary`, `verify_document`, `verify_bibliography`). The V2
verification pipeline (`verify_claim`, `verify_claims`) does not depend on
GROBID.

---

## Model Weights (Prepared During Setup)

### 10. NLI Model: cross-encoder/nli-deberta-v3-small

| Field | Value |
|---|---|
| **Component** | cross-encoder/nli-deberta-v3-small (DeBERTa-v3 cross-encoder for NLI) |
| **Model ID** | `cross-encoder/nli-deberta-v3-small` |
| **License** | Apache License 2.0 |
| **Author** | Tom Aarsen (Sentence Transformers / UKP Lab) |
| **Source** | Hugging Face Hub: <https://huggingface.co/cross-encoder/nli-deberta-v3-small> |
| **License source** | Hugging Face model card (License: apache-2.0) |
| **Base model** | `microsoft/deberta-v3-small` (MIT-licensed) |
| **Training data** | SNLI + MultiNLI datasets |
| **How used** | Prepared by bootstrap using `transformers`; runtime loads tokenizer and model with `local_files_only=True`; ~0.1B parameter model, ~170 MB download |
| **Redistributed?** | No — downloaded during setup from Hugging Face Hub; not bundled in repository |
| **Obligations** | Apache 2.0 — no redistribution obligation for local use. Model weights are not redistributed by this project. |

**Privacy note:** NLI inference processes claims/evidence locally using cached files. Bootstrap can contact Hugging Face to prepare the model; runtime has no download fallback. This does not make source retrieval, RefChecker metadata lookups, remote GROBID or the MCP client offline. See [SECURITY.md](SECURITY.md).

### 11. NLI Model Base: microsoft/deberta-v3-small

| Field | Value |
|---|---|
| **Component** | microsoft/deberta-v3-small |
| **License** | MIT |
| **Source** | Hugging Face Hub: <https://huggingface.co/microsoft/deberta-v3-small> |
| **How used** | Base model that `cross-encoder/nli-deberta-v3-small` was fine-tuned from |
| **Redistributed?** | No; base-model provenance only, no separate base-model download in application code |

---

## Removed Dependencies

### 1. PyMuPDF (pymupdf) — **REMOVED** (was AGPL-3.0)

| Field | Value |
|---|---|
| **Component** | PyMuPDF |
| **Version (was installed)** | 1.28.2 |
| **License (was)** | GNU Affero General Public License v3.0 (dual-licensed: AGPL-3.0 **or** Artifex Commercial License) |
| **Author** | Artifex Software, Inc. |
| **Historical migration** | TASK 20A in the development repository; its commit is not a publication-history reference |
| **License source** | PyPI metadata (<https://pymupdf.io/licensing>) — historical reference only |

**Removal justification (verified, not just requirements.txt edit):**

The migration to `pdfplumber` is verified complete at the code level:

1. **No production code imports pymupdf:** A full source audit across
   `citation_v2/*.py` and `server.py` confirms zero `import pymupdf`
   or `PyMuPDF` references. The sole former import was in
   `citation_v2/text_extractor.py:8`, now replaced with `import pdfplumber`.

2. **No test code imports pymupdf:** All PDF fixture creation in
   `tests/test_text_extractor.py` was rewritten using `reportlab` + `pypdf`.
   No `pymupdf` references remain in any test file.

3. **No production code references extraction_method='pymupdf':**
   The default changed from `"pymupdf"` to `"pdfplumber"` at
   `citation_v2/text_extractor.py:194`. All test assertions updated.

4. **`pymupdf==1.28.2` removed from `requirements.txt`:** Replaced with
   `pdfplumber==0.11.10`.

5. **`pymupdf` removed from `pyproject.toml` dependencies:** Replaced with
   `pdfplumber==0.11.10` in `[project.dependencies]`.

6. **`pymupdf` removed from `scripts/bootstrap.ps1` and `scripts/doctor.ps1`:**
   All import checks updated to `pdfplumber`.

7. **Historical legacy backup excluded:** `legacy/server_v1_working.py` is absent from the publication tree and reachable history. A development-only backup is not part of this release.

**Current status:** PyMuPDF is not declared in either runtime manifest and is not imported by production/test code. This describes the source publication; it does not certify arbitrary existing environments or other redistribution packages.

---

## Development Dependencies

Declared in `pyproject.toml` under `[project.optional-dependencies].dev` and mirrored in `requirements-dev.txt`.

### 12. reportlab (BSD-3-Clause, test-only dev dependency)

| Field | Value |
|---|---|
| **Component** | ReportLab PDF Toolkit |
| **Version** | 4.2.5 |
| **License** | BSD-3-Clause |
| **Author** | ReportLab Ltd / Andy Robinson, Robin Becker, the ReportLab team |
| **Package source** | PyPI: `reportlab==4.2.5` |
| **License source** | PyPI metadata (BSD license); verified license file (BSD-3-Clause, Copyright (c) 2000-2018, ReportLab Inc.) |
| **How used** | Test-only: `tests/test_text_extractor.py` creates synthetic PDFs using `reportlab.pdfgen.canvas` |
| **Redistributed?** | No — dev-only dependency, not required for runtime |
| **Obligations** | BSD-3-Clause — copyright notice retention only. No copyleft. |

**Why reportlab:** `pdfplumber` is a read-only library and cannot create PDFs.
Tests require synthetic PDF fixture generation. reportlab is BSD-3-Clause
as disclosed in its license file.

### 13. pypdf (BSD-3-Clause, test-only dev dependency)

| Field | Value |
|---|---|
| **Component** | pypdf |
| **Version** | 6.19.0 |
| **License** | BSD-3-Clause |
| **Author** | Mathieu Fenniak and contributors |
| **Package source** | PyPI: `pypdf==6.19.0` |
| **License source** | PyPI metadata (License-Expression: BSD-3-Clause); verified license file in `pypdf-6.19.0.dist-info/licenses/LICENSE` |
| **How used** | Test-only: `tests/test_text_extractor.py` creates encrypted test PDFs by wrapping reportlab-generated PDFs with pypdf encryption |
| **Redistributed?** | No — dev-only dependency |
| **Obligations** | BSD-3-Clause — copyright notice retention only. |

### 14. pytest (MIT, dev-only)

| Field | Value |
|---|---|
| **Component** | pytest |
| **Version** | 8.3.5 |
| **License** | MIT |
| **How used** | Test runner |
| **Source** | PyPI |
| **Redistributed?** | No |
| **Obligations** | MIT |

### 15. ruff (MIT, dev-only)

| Field | Value |
|---|---|
| **Component** | ruff |
| **Version** | 0.9.3 |
| **License** | MIT |
| **How used** | Linter/formatter |
| **Source** | PyPI |
| **Redistributed?** | No |
| **Obligations** | MIT |

### 16. mypy (MIT, dev-only)

| Field | Value |
|---|---|
| **Component** | mypy |
| **Version** | 1.15.0 |
| **License** | MIT |
| **How used** | Static type checker |
| **Source** | PyPI |
| **Redistributed?** | No |
| **Obligations** | MIT |

---

## Key Transitive Dependencies

These packages are pulled in as dependencies of the direct dependencies above.
They are listed for completeness. None are redistributed by this project
(each is installed by the end user via pip).

| Package | Version | License | Source (pip show) | How pulled in |
|---|---|---|---|---|
| pdfminer.six | 20260107 | MIT | PyPI metadata (License-Expression: MIT) | Transitive via pdfplumber |
| pypdfium2 | 5.13.0 | BSD-3-Clause AND Apache-2.0 | PyPI metadata | Transitive via pdfplumber |
| Pillow | 12.3.0 | MIT-CMU | License file (MIT-CMU) | Transitive via pdfplumber, reportlab |
| chardet | 7.6.0 | 0BSD | License classifier | Transitive via reportlab |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | License-Expression | Transitive via pdfminer.six |
| charset-normalizer | 3.5.2 | MIT | License-Expression | Transitive via requests |
| certifi | 2026.7.22 | MPL-2.0 | License-Expression | Transitive via requests; includes Mozilla CA bundle |
| urllib3 | 2.8.0 | MIT | License-Expression | Transitive via requests |
| idna | 3.20 | BSD-3-Clause | License-Expression | Transitive via requests |
| pandas | 3.0.6 | BSD-3-Clause | License file (BSD 3-Clause) | Transitive via academic-refchecker |
| pybtex | 0.26.1 | MIT | License file | Transitive via academic-refchecker |
| fuzzywuzzy | 0.18.0 | **GPLv2** | License classifier | Transitive via academic-refchecker |
| python-Levenshtein | 0.27.5 | **GPL-2.0-or-later** | License classifier | Transitive via academic-refchecker |
| numpy | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | License-Expression | Transitive via torch, transformers, rank-bm25, pandas |
| huggingface_hub | 1.33.0 | Apache-2.0 | License-Expression | Transitive via transformers |
| PyYAML | 6.0.3 | MIT | License-Expression | Transitive via transformers, huggingface_hub |
| tqdm | 4.70.1 | MPL-2.0 AND MIT | License-Expression | Transitive via transformers, huggingface_hub |
| safetensors | 0.8.0 | Apache-2.0 | License classifier | Transitive via transformers |
| tokenizers | 0.23.2 | Apache-2.0 | License classifier | Transitive via transformers |
| regex | 2026.9.29 | Apache-2.0 AND CNRI-Python | License-Expression | Transitive via transformers |
| typing_extensions | 4.16.0 | PSF-2.0 | License-Expression | Transitive via torch, transformers |
| sympy | 1.14.0 | BSD-3-Clause AND MIT | License-Expression | Transitive via torch |
| networkx | 3.6.1 | BSD-3-Clause | License-Expression | Transitive via torch |
| filelock | 3.32.3 | MIT | License-Expression | Transitive via transformers, huggingface_hub |
| fsspec | 2026.7.0 | BSD-3-Clause | License-Expression | Transitive via torch |
| anyio | 4.15.1 | MIT | License-Expression | Transitive via mcp |
| jsonschema | 4.26.0 | MIT | License-Expression | Transitive via mcp |
| pydantic | 2.13.5 | MIT | License-Expression | Transitive via mcp |
| attrs | 26.1.0 | MIT | License-Expression | Transitive via jsonschema |
| PyJWT | 2.15.1 | MIT | License-Expression | Transitive via mcp |
| starlette | 1.7.0 | BSD-3-Clause | License-Expression | Transitive via mcp (uvicorn/sse-starlette) |
| uvicorn | 0.54.0 | BSD-3-Clause | License-Expression | Transitive via mcp |
| sse-starlette | 3.5.0 | BSD-3-Clause | License-Expression | Transitive via mcp |
| httpx2 | 2.13.1 | BSD-3-Clause | License-Expression | Transitive via mcp |
| h11 | 0.16.0 | MIT | License-Expression | Transitive via mcp |
| python-multipart | 0.0.32 | Apache-2.0 | License-Expression | Transitive via mcp |
| pywin32 | 312 | PSF | License-Expression | Transitive via mcp |
| opentelemetry-api | 1.45.0 | Apache-2.0 | License-Expression | Transitive via mcp |
| click | 8.5.0 | BSD-3-Clause | License-Expression | Transitive via mcp, typer |
| typer | 0.27.2 | MIT | License-Expression | Transitive via mcp |
| shellingham | 1.5.4 | ISC | License-Expression | Transitive via typer |
| colorama | 0.4.6 | BSD | License file (BSD) | Transitive via academic-refchecker |
| lxml | 6.1.3 | BSD-3-Clause | License-Expression | Transitive via academic-refchecker |
| beautifulsoup4 | 4.15.0 | MIT | License file (MIT) | Transitive via academic-refchecker |
| soupsieve | 2.10 | MIT | License-Expression | Transitive via beautifulsoup4 |
| RapidFuzz | 3.14.6 | MIT | License-Expression | Transitive via fuzzywuzzy |
| latexcodec | 3.0.1 | MIT | License-Expression | Transitive via pybtex |
| six | 1.17.0 | MIT | License-Expression | Transitive via python-dateutil |
| python-dateutil | 2.9.0.post0 | BSD-3-Clause AND MIT | License-Expression | Transitive via academic-refchecker |

**Note on GPL transitive dependencies:** `fuzzywuzzy` (GPLv2) and `python-Levenshtein` / `Levenshtein` (GPL-2.0-or-later) remain disclosed. A subprocess boundary alone does not establish a compatibility conclusion.

---

## License Review Scope

Project-owned source is MIT-licensed. The inventory above retains the component license identities, including GPL and MPL dependencies. No third-party packages, images or weights are bundled in this source publication. This document does not certify license compatibility of a redistributed `.venv`, container bundle or other combined distribution; review that packaging separately against the actual license texts.

---

## Redistribution

**This project does NOT redistribute any third-party packages or model weights.**
All third-party components are installed or downloaded by the end user via:

- `pip install -r requirements.txt` (Python runtime packages)
- `pip install -r requirements-dev.txt` (development dependencies)
- `pip install academic-refchecker==3.0.190` (RefChecker CLI, via bootstrap.ps1)
- `docker compose up -d` (GROBID Docker image)
- Hugging Face Hub preparation during bootstrap (NLI model weights, ~170 MB)

The project only distributes its own source code. Third-party components
remain under their respective licenses.

---

## Repository Contents Audit

**No model weights, DB files, or third-party binaries are tracked in Git.**

Verified via `git ls-files`:
- 56 tracked files total (including the approved banner)
- All files ≤ 100 KB
- No `.safetensors`, `.bin`, `.pt`, `.pth`, `.gguf`, or model weight files
- No `.pdf` files tracked (test fixtures generated at test time)
- No `.db` or `.sqlite` files tracked
- Historical TASK 24R credential scan found only test fixtures; no new credential scan or complete release audit is claimed here

---

## Historical Legacy File

`legacy/server_v1_working.py` is excluded from this publication repository's tracked tree and reachable history. Earlier descriptions of a retained file and development commit `c4171fe` concerned the development repository, not this source publication. The separate development backup was not modified by this documentation review.

---

## Summary Table

| # | Component | Version | License | Installed/Imported | Redistributed? |
|---|---|---|---|---|---|
| 1 | pdfplumber | 0.11.10 | MIT | Import — PDF text extraction | No |
| 2 | MCP SDK | 2.2.0 | MIT | Import — MCP server framework | No |
| 3 | rank-bm25 | 0.2.2 | Apache-2.0 | Import — BM25 retrieval | No |
| 4 | requests | 2.34.2 | Apache-2.0 | Import — HTTP client | No |
| 5 | PyTorch (CPU) | 2.14.0+cpu | Apache-2.0 (composite) | Import — NLI inference | No |
| 6 | transformers | 5.17.0 | Apache-2.0 | Import — model loading | No |
| 7 | sentencepiece | 0.2.2 | Apache-2.0 | Direct dependency; tokenizer support | No |
| 8 | academic-refchecker | 3.0.190 | MIT | Subprocess CLI — V1 bibliography | No |
| 9 | GROBID (Docker) | 0.9.1-crf | Apache-2.0 | Docker container | No |
| 10 | NLI model | nli-deberta-v3-small | Apache-2.0 | Setup download; offline runtime loading | No |
| 11 | DeBERTa-v3-small (base) | v3-small | MIT | Model provenance; no separate download | No |
| 12 | reportlab | 4.2.5 | BSD-3-Clause | Dev-only import — test PDF creation | No |
| 13 | pypdf | 6.19.0 | BSD-3-Clause | Dev-only import — encrypted test PDFs | No |
| 14 | pytest | 8.3.5 | MIT | Dev-only test runner | No |
| 15 | ruff | 0.9.3 | MIT | Dev-only linter | No |
| 16 | mypy | 1.15.0 | MIT | Dev-only type checker | No |
| — | PyMuPDF (was) | 1.28.2 | AGPL-3.0 | **REMOVED** | No |

---

## Publication Scope

This source publication applies MIT to project-owned code and keeps third-party license disclosures separate. PyMuPDF is absent from current manifests and production/test imports; RefChecker's GPL dependencies remain disclosed and are not bundled. No blanket compatibility conclusion is made for direct/transitive dependencies or complete environment redistribution. Packaging third-party components requires its own license review.
