# Troubleshooting

## MCP Server Not Appearing in Kilo

### MCP shows as disconnected or disappears entirely

**Cause:** Malformed JSONC in `kilo.jsonc` can cause **all** MCP servers to disappear.

**Fix:**
1. Back up the active configuration and validate it with a JSONC-aware editor/parser. `python -m json.tool` accepts strict JSON only; test a separate comment-free copy rather than stripping the original settings file.
2. Place the named `citation-verifier` entry directly under `mcp`; use the helper's absolute command paths, `enabled: true` and `timeout: 600000`. See [Kilo setup](kilo-setup.md#global-or-project-configuration).
3. Restart/reload the client after saving; in VS Code, use **Developer: Reload Window**. UI controls vary by version.

### MCP shows "disabled"

**Cause:** `"enabled": false` in the server entry.

**Fix:**
1. Open your `kilo.jsonc`.
2. Ensure `"enabled": true` is present in the `citation-verifier` server entry.
3. Reload the Kilo window.

### MCP shows "connected" but tools are unavailable

**Cause:** Server process crashed on startup, or dependencies are missing.

**Fix:**
1. Inspect the client logs and run `.\scripts\print_kilo_config.ps1` to check the executable paths.
2. Run real MCP discovery independently of Kilo:
   ```powershell
   .\scripts\smoke_test.ps1
   ```
   Discovery requires installed dependencies, but no network, GROBID or model weights. An interactive `server.py` waits for stdio input and is not a discovery check. The smoke script's `-Timeout` argument is currently not used by its pytest invocation; initialization is fixed at 20 seconds in the helper. A cold import timeout does not prove a missing tool. Record the timeout and use a diagnostic with a larger initialization allowance before concluding startup is broken.
3. Run `.\scripts\doctor.ps1` for categorized diagnostics. GROBID failures affect V1 execution, not registration of the five tools. Doctor compiles modules and may write bytecode; it is not a model-inference check.
4. For dependency recovery, follow [Module import errors](#module-import-errors) before running bootstrap.

## Path and Environment Issues

### "No such file or directory" or Python path errors

**Cause:** The `command` path in `kilo.jsonc` points to a `.venv` or `server.py` that doesn't exist.

**Fix:**
1. Run `.\scripts\print_kilo_config.ps1` and verify the printed paths point to your actual repository.
2. Ensure `.venv` was created by bootstrap: `.\scripts\bootstrap.ps1`.
3. Do not hardcode paths from your development machine. Use the absolute paths generated for this checkout by `print_kilo_config.ps1`.

### Missing virtual environment

Confirm `.venv` is genuinely absent. If it exists but is unsupported, broken or incomplete, bootstrap rejects it without deleting it unless `-Force` is explicitly chosen. Follow [recovery precautions](#module-import-errors) first.

**Fix:**
```powershell
.\scripts\bootstrap.ps1
```

### Environment variable changes not taking effect

**Cause:** Environment variables set in a PowerShell prompt only apply to processes launched after the assignment in the same shell. If Kilo is already running, setting a variable in a new PowerShell window will not update Kilo's environment.

**Fix:**
1. Set the variable in the shell from which you will launch the client host.
2. Fully exit all host instances, then launch the host from that shell. A VS Code window reload may preserve the old process environment.

Persistent user environment settings apply to future processes. Generic VS Code workspace settings are not a verified injection mechanism for this MCP process.

### Project configuration overrides global configuration

**Cause:** If you have both a global `kilo.jsonc` and a project-level `<repo>/.kilo/kilo.jsonc`, the project configuration **overrides** the global one.

**Fix:** Ensure the MCP server entry is in the active configuration file (check both locations).

## GROBID Issues

### GROBID won't start

**Cause:** Docker Desktop is not running, or port 8070 is already in use.

**Fix:**
1. Start Docker Desktop and wait for it to be fully running.
2. Check if another process is using port 8070:
   ```powershell
   netstat -ano | findstr 8070
   ```
3. Identify the listener/container owner before changing anything. Inspect `docker ps -a` and `docker inspect citation-verifier-grobid` (labels, mounts and port bindings); the shared Compose label alone is insufficient. Never stop an unidentified or shared service. Prefer a verified free port for your own service:
   ```powershell
   $env:GROBID_HOST_PORT="9070"
   $env:GROBID_URL="http://127.0.0.1:9070"
   .\scripts\start.ps1
   ```
4. Run diagnostics: `.\scripts\doctor.ps1`

### GROBID container already running

**Diagnosis:** Check the health endpoint, actual published ports, container labels/mounts and service owner. A healthy service may be reused with its owner's approval; no restart is needed.

`start.ps1` can create/start a managed container and reuse an existing healthy endpoint; it does not establish exclusive ownership. `stop.ps1` checks the managed name and Compose project label, but separate checkouts can share them. Only after confirming this checkout exclusively owns `citation-verifier-grobid` and that no other user depends on it, schedule a restart if diagnostics justify it. The stop script stops the container without deleting it or its volumes. Do not stop a shared/external `grobid` container to resolve a conflict; coordinate with its owner or choose another port.

## Test Issues

### pytest permission denied on temp directory

**Cause:** The default pytest temp directory (`C:\Users\...\AppData\Local\Temp\pytest-of-user`) has permission restrictions.

**Fix:** Specify `--basetemp` with a dedicated writable disposable path. Pytest may delete its contents; never use a production directory:
```powershell
.venv\Scripts\python -m pytest tests/ -m "unit and not slow" -q --basetemp=.\.pytest-tmp
```

### Tests fail with "database is locked"

**Possible causes:** Another writer, a still-running test process, or a busy timeout. Diagnose before changing files.

**Fix:**
1. Inspect `CITATION_MCP_HOME` and `CITATION_MCP_DB_PATH` in the test shell. Fixtures preserve inherited values, so a production path can override isolation.
2. Confirm the resolved path is disposable test data and identify processes using it; close only your own test processes.
3. Prefer a new dedicated test home/database path and rerun. If a test file must later be removed, establish ownership, stop all users and preserve a verified backup first. Do not delete production data or manually remove SQLite journal/WAL files.

### Module import errors

**Cause:** Virtual environment not activated or dependencies not installed.

**Fix:**
1. Always use the project's `.venv`:
   ```powershell
   .\.venv\Scripts\python.exe --version
   ```
2. Check whether `.venv\Scripts\python.exe` exists and, if present, run the version command above. Record a failed execution or missing/unparseable version output rather than treating the environment as usable. Bootstrap requires Python >=3.13 and validates both the selected interpreter and the environment's own Python; Python 3.13.7 on Windows 11 is the independently verified application environment.
3. Without `-Force`, an unsupported, broken or incomplete `.venv` is preserved and rejected before package installation. Inspect the reported executable/path and dependency/import diagnostics. Installing a newer system Python does not upgrade an existing environment; preserve it and choose a fresh checkout or an explicit recovery plan.
4. Bootstrap can change packages in a supported reused environment. Explicit `-Force` deletes and recreates `.venv` after validating the selected interpreter and expected checkout path, and rejects a linked root `.venv`. These safeguards do not establish ownership or create backups. Before choosing `-Force`, confirm exclusive ownership, stop clients, record installed packages and preserve the environment in a separate backup. Prefer a fresh checkout when ownership is uncertain. Never use forced recreation as the default response to an import error.

## Model Download Issues

### Model download hangs

Review [environment recovery precautions](#module-import-errors) before rerunning bootstrap on an existing checkout.

**Fix:**
```powershell
$env:HF_HUB_DISABLE_XET=1
.\scripts\bootstrap.ps1
```

### Model not found in cache after download

**Fix:** Runtime requires both tokenizer and model cached locally. Bootstrap may report completion after a preparation warning; it does not guarantee inference readiness. Diagnose the cached model without downloading:
```powershell
.venv\Scripts\python -c "from transformers import AutoTokenizer, AutoModelForSequenceClassification; AutoTokenizer.from_pretrained('cross-encoder/nli-deberta-v3-small', local_files_only=True); AutoModelForSequenceClassification.from_pretrained('cross-encoder/nli-deberta-v3-small', local_files_only=True)"
```

## RefChecker (V1) Issues

### citation_summary times out

**Cause:** The `academic-refchecker.exe` takes ~5–6 minutes for 24 references. The application has a 600s timeout. External runners (CI/CD, task wrappers) must allow ≥12 minutes.

**Fix:**
1. Allow at least 12 minutes for the tool to complete.
2. Inspect the installed CLI options without performing source verification:
   ```powershell
   .\.venv\Scripts\academic-refchecker.exe --help
   ```
3. CLI help confirms `--paper`, `--report-file`, `--report-format json`; the server uses these flags, not `--input` or `--json`. A manual `--paper` run performs real network/parsing work and writes a report, so use a dedicated output path only when intentionally running integration.
4. Check GROBID health when PDF parsing is required, inspect the actual `ok`, error, stdout/stderr and retained report path, and distinguish the 600-second subprocess limit from client/runner deadlines. Increasing client timeouts does not extend the subprocess limit.

### RefChecker returns warnings

**Cause:** The RefChecker reports bibliography quality issues (missing DOIs, inconsistent formatting, etc.).

**Diagnosis:** Inspect `ok` and the report/error details. Successful report parsing can coexist with a nonzero RefChecker exit status, which the server preserves as `refchecker_returncode`. Warnings, unverified references and errors have different meanings; inspect the report rather than assuming success or inventing zero counts.

## Database Issues

### "Schema version mismatch" error

**Cause:** The SQLite database was created by a different version of the code.

**Fix:**
1. Record the code version, actual resolved database path and schema mismatch details. Do not delete the database or edit its schema marker.
2. Identify its owner and all processes using it. Stop only owned writers before making a consistent SQLite backup; preserve the original database and any active WAL state. Use SQLite's backup facility for a consistent snapshot and verify the backup is readable. A bare copy of a live `.db` can omit WAL changes.
3. Seek a migration/recovery plan compatible with the stored version, or use the known-compatible code against a backup after review. No general migration command is provided by this project.
4. If starting fresh is acceptable, point `CITATION_MCP_DB_PATH` to a new, unused file in an owned directory. Keep the old database and verified backup intact. Restart the client with the new environment.

### Database path points to a directory

**Cause:** `CITATION_MCP_DB_PATH` is set to a directory instead of a file path.

**Fix:** Set the environment variable to a file path, not a directory:
```powershell
$env:CITATION_MCP_DB_PATH = "$PWD\data\citations.db"
```

## Network and Source Issues

### All verifications return ABSTAIN

**Possible causes:** Unsupported/unavailable sources, security/download/extraction failures, missing eligible evidence, or decision thresholds.

**Fix:**
1. Check that the source is supported (supported arXiv ID/URL, public direct PDF URL, or local PDF).
2. Verify the source URL is publicly accessible (no authentication required).
3. For large PDFs, ensure the file is under `MAX_SOURCE_DOWNLOAD_BYTES` (default 100 MB).
4. Inspect `ok`, `source_state`, `reason` and `error_type`; a successfully loaded source may still return `ABSTAIN`. V2 has no arbitrary inline text, BibTeX, LaTeX or DOI-only full-text resolution.

### NLI inference is slow

**Cause:** First run requires model loading. Subsequent runs reuse the singleton.

**Fix:** This is expected behavior. The first `verify_claim` call takes 10–30 seconds (model load). Subsequent calls within the same process are much faster.

## PowerShell Scripting Issues

### `&&` operator not recognized

**Cause:** PowerShell 5.1 does not support the `&&` operator for command chaining.

**Fix:** Use `;` or PowerShell's `if ($?)` pattern:
```powershell
# Instead of: cmd1 && cmd2
cmd1; if ($?) { cmd2 }
```

### Non-ASCII characters cause parse errors

**Possible cause:** PowerShell 5.1 may interpret BOM-less UTF-8 scripts using a legacy encoding.

**Fix:** Diagnose encoding and use explicit UTF-8 for text reads/writes. Prefer `-LiteralPath` for file operations; do not change names or contents merely because they contain non-ASCII text.

## Getting More Help

If none of the above resolves your issue:

1. Run full diagnostics: `.\scripts\doctor.ps1`
2. Run the smoke test: `.\scripts\smoke_test.ps1`
3. Check the Kilo logs: `Ctrl+Shift+P` → "Developer: Toggle Developer Tools" → Console tab
4. The public repository URL is pending publication; use its actual issue tracker once available. For security-sensitive reports, follow [SECURITY.md](../SECURITY.md); GitHub Private Vulnerability Reporting must be enabled and verified before public publication.
