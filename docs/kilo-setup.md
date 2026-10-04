# Kilo MCP Integration Guide

This guide walks through connecting the Citation Verifier MCP server to Kilo
(a VS Code extension for AI-assisted coding) so you can call all five verification
tools directly from your chat.

---

## Prerequisites

Before starting, ensure you have:

1. **Windows 11 historically tested; Windows 10 not independently verified** (Linux/macOS may work but is untested).
2. **Docker Desktop** with Compose support (for GROBID).
3. **Python 3.13+** (required by package metadata and bootstrap). Bootstrap prefers Python 3.13 through the Windows `py` launcher and retains the actual selected interpreter, or uses a validated fallback. Python 3.13.7 on Windows 11 is the independently verified application environment.
4. Internet access for dependency/model/image setup, remote PDFs and RefChecker metadata lookups. Initial model download
   (~170 MB for the DeBERTa NLI model).

No API keys or tokens are required. Inference runs entirely locally.

---

## Quick Start

```powershell
# 1. Clone the repository
git clone https://github.com/<your-username>/citation-verifier-mcp.git
cd citation-verifier-mcp

# 2. Bootstrap the environment (creates .venv, installs deps, downloads model)
.\scripts\bootstrap.ps1

# 3. Start GROBID (starts the citation parsing service)
.\scripts\start.ps1

# 4. Verify everything is ready
.\scripts\doctor.ps1

# 5. Generate your Kilo config snippet
.\scripts\print_kilo_config.ps1
```

Copy the JSON block printed in step 5 and paste it into your Kilo configuration
file (instructions below).

---

## Step-by-Step Setup

### 1. Clone the Repository

```powershell
git clone https://github.com/<your-username>/citation-verifier-mcp.git
cd citation-verifier-mcp
```

Replace `<your-username>` with the actual repository owner.

### 2. Bootstrap the Environment

For an existing checkout, inspect `.venv` ownership/version and follow the recovery precautions below before running bootstrap. Without `-Force`, unsupported, broken or incomplete environments are preserved and rejected.

```powershell
.\scripts\bootstrap.ps1
```

This script:

- Selects and retains the actual Python interpreter via `py -3.13` or a compatible fallback; Python >=3.13 is required.
- Creates an isolated `.venv` in the repository.
- Installs all dependencies from `requirements.txt`, including PyTorch CPU.
- Installs `academic-refchecker` (the bibliography verification CLI).
- Pre-downloads the `cross-encoder/nli-deberta-v3-small` model to the local
  Hugging Face cache.
- Runs import and compilation checks.

Bootstrap validates the environment's own Python version before reuse and package installation, including newly created environments. Without `-Force`, an unsupported, broken or incomplete `.venv` is preserved and rejected. Reusing a supported environment can change installed dependencies. Explicit `-Force` recreates it only after selected-interpreter and expected-path checks, and rejects a linked root `.venv`; these checks do not establish ownership or create backups. Diagnose first, confirm exclusive ownership, stop clients and preserve the environment and package inventory before recreation. See [safe recovery](troubleshooting.md#module-import-errors).

Bootstrap can warn about model preparation and still complete. Runtime never downloads missing model files (`local_files_only=True`); resolve preparation failures before V2 use.

**Troubleshooting env var:**

If model download stalls on the Hugging Face Hub, set:

```powershell
$env:HF_HUB_DISABLE_XET=1
```

### 3. Start GROBID

```powershell
.\scripts\start.ps1
```

This starts a managed GROBID container (`citation-verifier-grobid`) via
Docker Compose and polls the health endpoint until it reports `true`.

If you already have a healthy GROBID running on port 8070 (for example, a
shared team container), `start.ps1` will detect it and skip starting a new one.

To use a custom port, set the environment variable first:

```powershell
$env:GROBID_HOST_PORT="9070"
$env:GROBID_URL="http://127.0.0.1:9070"
.\scripts\start.ps1
```

> **Environment changes:** Fully exit the client host and launch it from the shell containing the variables. Reloading a window may keep the original host environment.

### 4. Run Diagnostics

```powershell
.\scripts\doctor.ps1
```

This checks Python, `.venv`, required modules, the RefChecker executable,
Docker CLI, Docker Engine, GROBID health, and MCP tool discovery. The final
line will be `OVERALL: READY`, `OVERALL: PARTIALLY READY`, or
`OVERALL: NOT READY` with specific remediations.

### 5. Generate Kilo Configuration

```powershell
.\scripts\print_kilo_config.ps1
```

The script automatically resolves:

- The repository root (relative to the script's own location).
- The project's `.venv\Scripts\python.exe`.
- The `server.py` path.

It prints a JSONC snippet you can copy directly.

### 6. Merge the Configuration into Kilo

Kilo's configuration can live in two places:

| Location | Overrides Global? | Use Case |
|---|---|---|
| Global: `~/.config/kilo/kilo.jsonc` | N/A | Applies to all projects |
| Project: `<repo>/.kilo/kilo.jsonc` | Yes | Per-project settings (recommended for testing) |

#### Global or project configuration

Insert the helper-generated named entry directly under `mcp`. Use its absolute paths in either location; the paths below are illustrative. Preserve other server entries and existing settings. The helper only prints configuration and never edits it.

```jsonc
{
  "mcp": {
    "citation-verifier": {
      "type": "local",
      "command": [
        "C:\\path\\to\\your\\repo\\.venv\\Scripts\\python.exe",
        "C:\\path\\to\\your\\repo\\server.py"
      ],
      "enabled": true,
      "timeout": 600000
    }
  }
}
```

The generated fields are `type: "local"`, a two-element `command` array (venv Python, server.py), `enabled: true` and `timeout: 600000` milliseconds. The RefChecker subprocess itself has a 600-second limit; changing the client timeout does not extend that limit.

Permissions are optional. To allow these tools without prompts, merge the named permission into the existing top-level `permission` object, retaining all other entries. A complete illustrative config is:

```jsonc
{
  "mcp": {
    "citation-verifier": {
      "type": "local",
      "command": [
        "C:\\path\\to\\your\\repo\\.venv\\Scripts\\python.exe",
        "C:\\path\\to\\your\\repo\\server.py"
      ],
      "enabled": true,
      "timeout": 600000
    }
  },
  "permission": {
    "other_server_*": "allow",
    "citation-verifier_*": "allow"
  }
}
```

Project configuration overrides global as described by the helper. Check both files if settings conflict; no actual Kilo configuration is changed by this guide.

### 7. Reload the VS Code / Kilo Window

After saving the config file, reload Kilo:

1. Press `Ctrl+Shift+P` to open the command palette.
2. Type "Reload Window" and select **Developer: Reload Window**.

Restart/reload the client after saving configuration. Exact controls vary by client version. This reload advice concerns configuration files; environment changes require a freshly launched host process.

### 8. Verify MCP Server Connection

1. Open the client's Kilo view; names and controls vary by version.
2. Create a new session or open an existing one.
3. In the session, open the MCP tools view (often an icon or menu labeled
   "Tools" or "MCP").
4. Confirm `citation-verifier` appears as **Connected**.

`tools/list` is an MCP protocol request, not a guaranteed chat command. Check the client's advertised tools or run `.\scripts\smoke_test.ps1` independently of Kilo. Discovery does not require GROBID, network or model weights. See [timeout diagnostics](troubleshooting.md#mcp-shows-connected-but-tools-are-unavailable).

### 9. Create a New Kilo Session

1. Open Kilo.
2. Create a new session (or use an existing one).
3. The Citation Verifier tools are now available in the tool picker.

### 10. Test the Citation Verifier MCP

Call `verify_claim` with arXiv paper `2607.22693`:

**Input:**

```json
{
  "claim": "The paper studies hallucinated and suspicious citations.",
  "source": "2607.22693"
}
```

**Expected behavior:** Returns a verdict (`PASS`, `WARN`, `FAIL`, or
`ABSTAIN`) with provenance evidence, including exact quotes from the paper.

Try a batch of claims:

**Input:**

```json
{
  "claims": [
    {
      "claim": "The paper studies hallucinated and suspicious citations.",
      "source": "2607.22693"
    },
    {
      "claim": "The paper does not discuss hallucinated citations.",
      "source": "2607.22693"
    }
  ]
}
```

**Expected behavior:** Same-source batch reuses one loaded source and one
BM25 index (internally tracked as `source_loads=1, bm25_indexes_built=1`).

---

## Supported Tools

| Tool | Required arguments | Optional arguments |
|---|---|---|
| `verify_document` | `source: string` | None |
| `verify_bibliography` | `path: string` (existing local file) | None |
| `citation_summary` | `source: string` | None |
| `verify_claim` | `claim: string`, `source: string` | `top_k: integer` |
| `verify_claims` | `claims: array` of objects | `top_k: integer` |

Discovery advertises batch items as generic objects (`additionalProperties: true`); runtime requires each item's `claim` and `source` strings. Maximum batch: 100. `top_k` is 1-20, default 5 unless `CITATION_BM25_TOP_K` overrides it. V1 accepts RefChecker source identifiers/files, not arbitrary inline bibliography blocks. V2 accepts local PDFs, supported arXiv IDs/URLs and public direct PDF URLs; no inline text, BibTeX, LaTeX or DOI-only full-text resolution. See [tool reference](../README.md#tools).

---

## GROBID_HOST_PORT vs GROBID_URL

The application supports two ways to configure GROBID connectivity:

| Variable | Purpose | Default |
|---|---|---|
| `GROBID_HOST_PORT` | Docker host port mapping for `start.ps1` | `8070` |
| `GROBID_URL` | Full URL the application uses to reach GROBID | `http://127.0.0.1:8070` |

### When using the same port (default):

```powershell
.\scripts\start.ps1
```

Both default to `8070`. No environment variables needed.

### When using a custom port:

```powershell
$env:GROBID_HOST_PORT=9070
$env:GROBID_URL="http://127.0.0.1:9070"
.\scripts\start.ps1
```

**Important:** You must set **both** variables. `GROBID_HOST_PORT` controls
the Docker container's published port, but `GROBID_URL` tells the application
where to find the service. Setting only `GROBID_HOST_PORT` is not sufficient.

**VS Code / Kilo environment propagation:**

- Environment variables set in a PowerShell prompt only apply to processes
  launched **after** the assignment in the **same** shell.
- If Kilo is already running, a new shell assignment does not update its environment. Fully exit all host instances, then launch the host from the configured shell. A window reload may reuse the old environment.
- Persistent user environment settings affect future processes. Generic VS Code workspace settings are not a verified way to inject this server's environment.

---

## Troubleshooting

### MCP server shows as disconnected or disappears entirely

- Verify the JSON is valid. A malformed JSONC entry can cause **all** MCP
  servers to disappear from Kilo.
- Use a JSONC-aware editor/parser. `python -m json.tool` accepts strict JSON only; validate a separate comment-free copy rather than stripping the original configuration.
- Place `citation-verifier` directly inside `mcp` as shown above.
- Reload the Kilo window after fixing.

### MCP shows "disabled"

- Check that `"enabled": true` is present in the server entry.
- Review the active entry and the client's enabled state; UI controls vary by version.

### MCP shows "connected" but tools are unavailable

- Inspect client logs and generated executable paths. Run `.\scripts\smoke_test.ps1` for real protocol discovery; running `server.py` interactively waits for stdio input.
- Diagnose dependencies with `.\scripts\doctor.ps1` before recovery. GROBID is needed for V1 execution when parsing PDFs, not tool discovery.
- Follow [Troubleshooting](troubleshooting.md) for ownership and backup checks before bootstrap or container changes.

### "No such file or directory" or Python path errors

- Run `.\scripts\print_kilo_config.ps1` and verify the printed paths point to
  your actual repository and `.venv`.
- Ensure `.venv` was created by bootstrap (`.\scripts\bootstrap.ps1`).
- Do not hardcode paths from your development machine into the config. Always
  use paths generated by `print_kilo_config.ps1` with absolute paths for the
  current checkout.

### Missing virtual environment

- If the `command` path points to a `.venv` that does not exist, the server
  will fail to start.
- Run `.\scripts\bootstrap.ps1` to create the environment.

### Project configuration overrides global configuration

- If you have both a global `kilo.jsonc` and a project-level
  `<repo>/.kilo/kilo.jsonc`, the project configuration **overrides** the
  global one. Ensure the MCP server entry is in the active configuration file.
- Check both files if the server is not appearing.

### Changes require a VS Code window reload

- After saving `kilo.jsonc`, restart/reload the client. In VS Code, use:
  `Ctrl+Shift+P` → "Developer: Reload Window".
- Environment changes require fully exiting and freshly launching the host from the configured shell; a reload alone may retain old values.

### HF Xet / CAS download issue

- If the model download hangs, set `HF_HUB_DISABLE_XET=1` in your environment
  before running bootstrap. This disables the Xet-backed transfer mechanism
  in favor of standard HTTPS downloads.

### torch.jit FutureWarning

- You may see `FutureWarning: torch.jit.script is deprecated`. This is a
  non-fatal warning from PyTorch and does not affect functionality.

---

## Permission Guidance

To allow all Citation Verifier tools without prompting on each call:

```jsonc
"permission": {
  "citation-verifier_*": "allow"
}
```

This allows client calls matching the server tool pattern without prompts. Review the tools' file/network behavior before enabling it.
**Merge** this into your existing `permission` object rather than replacing the
entire object, which would remove permissions from other servers.

---

## Verifying the Integration

After setup, run this checklist:

1. Review each category in `.\scripts\doctor.ps1`, rather than treating its overall status as inference readiness. A V2-only setup can lack GROBID; discovery does not load model weights.
2. `.\scripts\print_kilo_config.ps1` shows the correct repo paths.
3. Kilo's MCP panel shows `citation-verifier` as **Connected**.
4. The client advertises all five tools; independent protocol discovery succeeds.
5. Call `verify_claim` with the JSON `claim`/`source` example above; inspect verdict, reason, source_state and evidence rather than assuming every request succeeds.

---

## Notes

- This project does **not** include a native Windows GUI or `.exe` installer.
  The provided launch mechanism is the `.cmd` launcher for GROBID startup
  and the PowerShell scripts for all other operations.
- The Citation Verifier runs server-side (as an MCP stdio server). No
  additional client software beyond Kilo and Docker is required.
- If you encounter issues with Kilo integration, run the direct MCP discovery
  test:
  ```powershell
  .\scripts\smoke_test.ps1
  ```
  This confirms the server starts and advertises all five tools independently
  of Kilo.
