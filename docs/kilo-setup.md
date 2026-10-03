# Kilo MCP Integration Guide

This guide walks through connecting the Citation Verifier MCP server to Kilo
(a VS Code extension for AI-assisted coding) so you can call all five verification
tools directly from your chat.

---

## Prerequisites

Before starting, ensure you have:

1. **Windows 10 or 11** (Linux/macOS may work but is untested).
2. **Docker Desktop** with Compose support (for GROBID).
3. **Python 3.13+** (the bootstrap script uses the Windows `py` launcher and
   prefers Python 3.13; Python 3.12 is the minimum).
4. Internet access for the **initial** dependency and model download
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

```powershell
.\scripts\bootstrap.ps1
```

This script:

- Detects Python 3.13 (or 3.12+) via the `py` launcher.
- Creates an isolated `.venv` in the repository.
- Installs all dependencies from `requirements.txt`, including PyTorch CPU.
- Installs `academic-refchecker` (the bibliography verification CLI).
- Pre-downloads the `cross-encoder/nli-deberta-v3-small` model to the local
  Hugging Face cache.
- Runs import and compilation checks.

**Safe to rerun.** If `.venv` already exists and is valid, it is reused.
Use `.\scripts\bootstrap.ps1 -Force` to recreate from scratch.

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
$env:GROBID_HOST_PORT=9070
.\scripts\start.ps1
```

> **Important:** Setting an environment variable in PowerShell only affects
> new processes. If Kilo is already running, you must restart Kilo (or reload
> the VS Code window) for the variable to take effect.

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

#### Global configuration

Open `~/.config/kilo/kilo.jsonc` in your editor. It typically looks like:

```jsonc
{
  // ...existing config...
  "mcp": {
    "servers": {
      // ...other MCP servers...
    }
  },
  "permission": {
    // ...existing permissions...
  }
}
```

Insert the generated entry **inside** the `mcp` > `servers` object:

```jsonc
{
  "mcp": {
    "servers": {
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
  },
  "permission": {
    "citation-verifier_*": "allow"
  }
}
```

#### Project configuration (recommended for testing)

To avoid touching your global config, create `<repo>/.kilo/kilo.jsonc`:

```jsonc
{
  "mcp": {
    "servers": {
      "citation-verifier": {
        "type": "local",
        "command": [
          ".\\.venv\\Scripts\\python.exe",
          "server.py"
        ],
        "enabled": true,
        "timeout": 600000
      }
    }
  }
}
```

> **Merging note:** When adding the `permission` section, **merge** it into
> the existing object. Do not replace the entire `permission` object unless you
> want to reset all permissions. For example, if you already have:
>
> ```jsonc
> "permission": {
>   "other_server_*": "allow"
> }
> ```
>
> Change it to:
>
> ```jsonc
> "permission": {
>   "other_server_*": "allow",
>   "citation-verifier_*": "allow"
> }
> ```

### 7. Reload the VS Code / Kilo Window

After saving the config file, reload Kilo:

1. Press `Ctrl+Shift+P` to open the command palette.
2. Type "Reload Window" and select **Developer: Reload Window**.

Kilo re-reads the configuration on window reload. Without this step, the
new MCP server will not be picked up.

### 8. Verify MCP Server Connection

1. Open Kilo (`Ctrl+Shift+P` → "Kilo: Focus" or open the Kilo sidebar).
2. Create a new session or open an existing one.
3. In the session, open the MCP tools view (often an icon or menu labeled
   "Tools" or "MCP").
4. Confirm `citation-verifier` appears as **Connected**.

You can also run `tools/list` directly in a Kilo session — the five Citation
Verifier tools should be listed:

- `verify_document`
- `verify_bibliography`
- `citation_summary`
- `verify_claim`
- `verify_claims`

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

| Tool | Purpose |
|---|---|
| `verify_document` | Verify all citations in a local PDF, arXiv paper, or web-hosted PDF. |
| `verify_bibliography` | Check a bibliography block or BibTeX file for errors and issues. |
| `citation_summary` | Summarize citation quality for a paper (e.g., arXiv ID). |
| `verify_claim` | Verify a single factual claim against a source (arXiv ID, URL, or PDF path). |
| `verify_claims` | Verify multiple claims in one batch, with same-source reuse. |

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
$env:GROBID_URL=http://127.0.0.1:9070
.\scripts\start.ps1
```

**Important:** You must set **both** variables. `GROBID_HOST_PORT` controls
the Docker container's published port, but `GROBID_URL` tells the application
where to find the service. Setting only `GROBID_HOST_PORT` is not sufficient.

**VS Code / Kilo environment propagation:**

- Environment variables set in a PowerShell prompt only apply to processes
  launched **after** the assignment in the **same** shell.
- If Kilo is already running, setting a variable in a new PowerShell window
  will **not** update Kilo's environment. You must restart Kilo or reload
  the window (`Developer: Reload Window`) after setting environment variables.
- To make environment variables persistent for Kilo, set them in your system
  environment or in a VS Code workspace settings file.

---

## Troubleshooting

### MCP server shows as disconnected or disappears entirely

- Verify the JSON is valid. A malformed JSONC entry can cause **all** MCP
  servers to disappear from Kilo.
- Validate your config with a JSON parser. Remove all comments and trailing
  commas, then test with `python -m json.tool`.
- Ensure the `mcp.servers` object is correctly nested.
- Reload the Kilo window after fixing.

### MCP shows "disabled"

- Check that `"enabled": true` is present in the server entry.
- In some Kilo versions, toggling the server off in the MCP panel sets
  `"enabled": false`. Re-enable it.

### MCP shows "connected" but tools are unavailable

- The server process may have crashed on startup. Run `server.py` directly to
  see error output:
  ```powershell
  .\.venv\Scripts\python.exe server.py
  ```
- Check that `.venv` exists and has all dependencies installed (run
  `.\scripts\bootstrap.ps1`).
- Check that GROBID is running and healthy (run `.\scripts\start.ps1` and
  verify `http://127.0.0.1:8070/api/isalive` returns `true`).
- Run `.\scripts\doctor.ps1` for a full diagnostic.

### "No such file or directory" or Python path errors

- Run `.\scripts\print_kilo_config.ps1` and verify the printed paths point to
  your actual repository and `.venv`.
- Ensure `.venv` was created by bootstrap (`.\scripts\bootstrap.ps1`).
- Do not hardcode paths from your development machine into the config. Always
  use paths generated by `print_kilo_config.ps1` or relative paths from the
  repository root.

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

- Kilo reads the config file on startup. Any change to `kilo.jsonc` (global
  or project) requires a window reload:
  `Ctrl+Shift+P` → "Developer: Reload Window".
- Setting environment variables also requires a reload if Kilo is already
  running.

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

This grants the MCP server permission to execute all its registered tools.
**Merge** this into your existing `permission` object rather than replacing the
entire object, which would remove permissions from other servers.

---

## Verifying the Integration

After setup, run this checklist:

1. `.\scripts\doctor.ps1` reports `OVERALL: READY`.
2. `.\scripts\print_kilo_config.ps1` shows the correct repo paths.
3. Kilo's MCP panel shows `citation-verifier` as **Connected**.
4. In a Kilo session, `tools/list` returns all five tools.
5. `verify_claim("2607.22693", ...)` returns a verdict with provenance.

---

## Notes

- This project does **not** include a native Windows GUI or `.exe` installer.
  The supported launch mechanism is the `.cmd` launcher for GROBID startup
  and the PowerShell scripts for all other operations.
- The Citation Verifier runs server-side (as an MCP stdio server). No
  additional client software beyond Kilo and Docker is required.
- If you encounter issues with Kilo integration, run the direct MCP discovery
  test:
  ```powershell
  .\.venv\Scripts\python.exe -c "from mcp import ClientSession, StdioServerParameters; from mcp.client.stdio import stdio_client; ..."
  ```
  This confirms the server starts and advertises all five tools independently
  of Kilo.
