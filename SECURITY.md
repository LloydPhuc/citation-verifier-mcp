# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| main (2.x) | Yes |
| legacy/server_v1_working.py | No — historical baseline, not maintained |

## Reporting a Vulnerability

To report a security vulnerability, **do not use public issues**.

1. Go to the **Security** tab of this repository: `https://github.com/<owner>/citation-verifier-mcp/security`
2. Click **Report a vulnerability** and fill in the advisory form.
3. Alternatively, email the maintainer listed in `pyproject.toml`.

You should receive an initial response within 48 hours. If the report is accepted, a patch will be prioritized. You will be notified of the fix and asked for **embargo** until a release is published.

## Threat Model

**Citation Verifier MCP** is a local-first Model Context Protocol (MCP) server. The core design principle is: **all inference runs on the user's machine — no API keys, no cloud calls, no data leaves the device.**

### What runs locally

| Component | Location | Network |
|-----------|----------|---------|
| MCP server (`server.py`) | User's machine | stdio JSON-RPC only (no TCP listener) |
| V2 verification pipeline (`citation_v2/`) | User's machine | CPU-only PyTorch + local model |
| NLI model (DeBERTa) | Local cache (`~/.cache/huggingface/`) | Download once at first run |
| GROBID | Local Docker container | Application connects via `127.0.0.1:8070`; Docker Compose binds to `127.0.0.1` (loopback only) |
| academic-refchecker | Local subprocess in `.venv` | None (invoked via `subprocess.run`) |

### Data flow

1. The MCP client (e.g., Kilo) sends a claim and source request to `server.py` over **stdio** (pipe-based JSON-RPC). The server does **not** listen on any TCP port.
2. Sources provided by the user (arXiv IDs, PDF URLs, local files) are downloaded or read into local cache (`cache/`).
3. Verification is performed entirely on the local machine using a local PyTorch model.
4. Results are returned to the MCP client over stdio. **No data is transmitted to third parties.**

### What the project does NOT do

- No API keys, tokens, or credentials are required or stored.
- No telemetry is collected.
- No inference results are sent to any server.
- The server does not listen on any network port.

## Security Controls

### 1. SSRF Protection — `citation_v2/source_loader.py`

When a user provides a URL as a source, the server downloads it with multiple safeguards:

| Control | Implementation | Default |
|---------|---------------|---------|
| Non-public IP blocking | `_validate_public_http_url()` checks `ipaddress.is_global` for literal IPs and all DNS-resolved addresses | Always on |
| Localhost / RFC1918 / link-local blocking | Hostnames `localhost` blocked; all resolved IPs must be globally routable | Always on |
| Redirect re-validation | Every redirect hop is re-validated against the SSRF rules (not just the initial URL) | Always on |
| Redirect limit | `HTTP_MAX_REDIRECTS` environment variable | 5 |
| Download size limit | `MAX_SOURCE_DOWNLOAD_BYTES` environment variable | 100 MB |
| Connection timeout | `HTTP_CONNECT_TIMEOUT` environment variable | 15 seconds |
| Read timeout | `HTTP_READ_TIMEOUT` environment variable | 120 seconds |
| URL scheme restriction | Only `http://` and `https://` are accepted | Always on |
| Embedded credentials | URLs with `username:password@host` are rejected | Always on |
| PDF header validation | Downloaded content must contain `%PDF-` within the first 1024 bytes | Always on |

**Limitation:** DNS rebinding defenses against time-of-check/time-of-use races are not implemented. An attacker who controls a source URL could potentially exploit a TOCTOU window between DNS resolution and connection. Mitigation: users should only provide source URLs from trusted publishers.

### 2. Subprocess Isolation — `server.py`

The `academic-refchecker.exe` CLI (used for V1 bibliography features: `verify_document`, `verify_bibliography`, `citation_summary`) is invoked via `subprocess.run()`:

| Control | Implementation |
|---------|---------------|
| Timeout | 600 seconds (10 minutes) — prevents indefinite hangs |
| Output capture | `capture_output=True` — stdout/stderr are captured, not inherited |
| Working directory | `cwd=BASE_DIR` — fixed, predictable working directory |
| UUID report path | Report UUID prevents collision and path prediction |
| Temp file cleanup | Report files are deleted after successful parse |
| Environment | `build_environment()` sets `PYTHONIOENCODING`, `PYTHONUTF8`, and `NO_PROXY` for local hosts |

The RefChecker runs in a separate process with no access to the MCP server's Python interpreter state.

### 3. Cache Path Safety — `citation_v2/cache.py`

| Control | Implementation |
|---------|---------------|
| Filename sanitization | `safe_filename()` strips path separators and directory components, rejecting `../../secret.txt`, `C:\Windows\file` |
| Deletion boundary check | `delete_cache_file()` verifies the target path is inside the cache directory via `Path.resolve()` + `relative_to()` |
| Atomic writes | `tempfile.mkstemp()` + `os.replace()` — prevents half-written cache files on crash |
| Content-addressable storage | SHA-256 content hash used as filename — corruption is detected on read by re-hashing |
| Cache integrity verification | On cache load, file hash is compared to expected content hash; mismatch raises `RuntimeError` |

### 4. Model Safety — `citation_v2/nli.py`

| Control | Implementation |
|---------|---------------|
| Offline loading | `local_files_only=True` — model and tokenizer are loaded from local cache only; no runtime network calls |
| CPU-only | `device="cpu"` enforced — GPU access is rejected |
| Singleton | One model instance per process — no repeated loading |
| Numerical validation | Non-finite logits/probabilities raise `NLIModelError` |
| Probability sanity | Scores are validated to sum to 1.0 within tolerance |

The NLI model (`cross-encoder/nli-deberta-v3-small`) is downloaded **once** from Hugging Face Hub at first run (~170 MB). Subsequent runs use the local cache entirely offline.

### 5. Database Safety — `citation_v2/database.py`

| Control | Implementation |
|---------|---------------|
| Schema versioning | The stored schema version is verified at initialization; mismatch raises `RuntimeError` |
| SQLite busy timeout | Configurable via `CITATION_SQLITE_BUSY_TIMEOUT_MS` (default 5000 ms) — prevents lock contention issues |
| Content hash deduplication | Papers and chunks keyed by SHA-256 — no unbounded duplication |
| Parameterized data | All `SELECT`/`INSERT`/`DELETE` statements that accept user or source data use `?` placeholders with parameter tuples |
| Git-ignored | `*.db`, `*.sqlite`, `*.sqlite3`, `data/` are in `.gitignore` — no database files are committed |

### 6. Path Safety — `citation_v2/source_loader.py`

Local PDF paths are handled with care:

| Control | Implementation |
|---------|---------------|
| Path resolution | `os.path.expandvars()` + `os.path.expanduser()` + `Path.resolve()` — normalizes the path |
| Existence check | `path.exists()` and `path.is_file()` — rejects directories and non-files |
| Re-extraction | Local PDFs are re-extracted on each call (not cached by path) — if a user modifies a PDF at the same path, the updated content is used |

## Security Hardening Recommendations

Users running this server in a multi-user or restricted environment should:

1. **Run the server under a dedicated user account** with minimal filesystem permissions.
2. **Restrict the `.venv` directory** to the running user only (e.g., `chmod 700 .venv`).
3. **GROBID binds to loopback**: Docker Compose binds GROBID to `127.0.0.1` by default (configured in `docker-compose.yml`). If you need to expose it externally, explicitly set `GROBID_HOST_PORT` and configure your firewall accordingly.
4. **Set resource limits** if using in a shared environment: memory (~2 GB for model + inference), CPU, and disk space for cache.
5. **Review environment variables**: `GROBID_URL` is read from the environment. Ensure no unexpected proxy or redirect is configured.
6. **Clear cache periodically**: cached downloads in `cache/` may contain sensitive source PDFs. Clear with `cache/` directory when no longer needed.

## Known Limitations

- **No sandboxing of PDF parsing**: pdfplumber is a pure-Python PDF parser with no seccomp/namespace isolation. A maliciously crafted PDF could trigger parser bugs. Mitigation: only load PDFs from trusted sources.
- **No input sanitization beyond the controls above**: The claim text and source content are passed directly to the NLI model and retrieval pipeline without additional sanitization beyond the type and content checks in `nli.py`.
- **DNS rebinding**: Not mitigated (see SSRF section above).
- **Side-channel**: NLI inference timing may leak information about the claim/evidence pair. This is inherent to local inference and is not considered a vulnerability in the local-first threat model.
