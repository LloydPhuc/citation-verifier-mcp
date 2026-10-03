<#
.SYNOPSIS
    Generate a portable Kilo MCP configuration entry for Citation Verifier.

.DESCRIPTION
    Derives all paths from the script's own location, so it works from any
    clone directory. Never modifies the user's Kilo configuration - it only
    prints what to insert. Detects the virtualenv Python, server.py, and
    reports missing prerequisites clearly.

.NOTES
    Run from any directory; resolves repository root relative to $PSScriptRoot.
    Does NOT edit ~/.config/kilo/kilo.jsonc or any project .kilo config.
#>

[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# ---------- Configuration ----------

$repoRoot = $null
$requirementsFile = $null
$pythonExe = $null
$serverPy = $null

# ---------- Helper Functions ----------

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "============================================================"
    Write-Host "  $Title"
    Write-Host "============================================================"
}

function Write-Success {
    param([string]$Message)
    Write-Host "  [OK] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "  [WARN] $Message" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "  [FAIL] $Message" -ForegroundColor Red
}

function Write-Step {
    param([string]$Step, [string]$Message)
    Write-Host "[$Step] $Message"
}

# Escape a Windows path for JSON (handles backslashes and any embedded quotes).
function Convert-ToJsoncPath {
    param([string]$Path)
    return $Path.Replace('\', '\\')
}

# ---------- Step 1: Locate repository root ----------

Write-Section "Kilo MCP Configuration Generator"

Write-Step "1/5" "Locating repository root..."

try {
    $repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    Write-Success "Repository root: $repoRoot"
} catch {
    Write-Fail "Could not resolve repository root."
    exit 1
}

# ---------- Step 2: Detect Python interpreter ----------

Write-Step "2/5" "Detecting Python interpreter..."

$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'

if (Test-Path $venvPython) {
    $pythonExe = $venvPython
    Write-Success "Found venv Python: $pythonExe"
} else {
    Write-Warn ".venv\Scripts\python.exe not found."

    # Fallback: check for a system Python
    $sysPython = Get-Command 'py.exe' -ErrorAction SilentlyContinue
    if ($sysPython) {
        try {
            $ver = & 'py.exe' '-3.13' '--version' 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Warn "Found system Python 3.13: $($sysPython.Source)"
                Write-Warn "Recommended: run 'scripts\bootstrap.ps1' to create an isolated .venv."
                $pythonExe = $sysPython.Source
            }
        } catch { }
    }

    if (-not $pythonExe) {
        Write-Warn "No Python found. Run 'scripts\bootstrap.ps1' first."
    }
}

# ---------- Step 3: Detect server.py ----------

Write-Step "3/5" "Detecting server.py..."

$serverPy = Join-Path $repoRoot 'server.py'

if (Test-Path $serverPy) {
    Write-Success "server.py found at: $serverPy"
} else {
    Write-Fail "server.py not found at: $serverPy"
    Write-Fail "Ensure you are running this from the repository checkout."
    exit 1
}

# ---------- Step 4: Prerequisites summary ----------

Write-Step "4/5" "Checking prerequisites..."

$allPrereqsMet = $true

if (-not (Test-Path (Join-Path $repoRoot 'requirements.txt'))) {
    Write-Warn "requirements.txt not found."
    $allPrereqsMet = $false
} else {
    Write-Success "requirements.txt present."
}

if (-not $pythonExe) {
    Write-Fail "Python interpreter not available. Run bootstrap.ps1."
    $allPrereqsMet = $false
}

# ---------- Step 5: Generate configuration ----------

Write-Step "5/5" "Generating Kilo MCP configuration..."

if (-not $allPrereqsMet) {
    Write-Host ""
    Write-Warn "PREREQUISITES MISSING - configuration generated but will not work until:"
    Write-Host "  1. Run: .\scripts\bootstrap.ps1   (creates .venv and installs dependencies)"
    Write-Host "  2. Run: .\scripts\start.ps1       (starts GROBID container)"
    Write-Host "  3. Run: .\scripts\doctor.ps1      (verifies environment)"
    Write-Host "  4. Re-run this script: .\scripts\print_kilo_config.ps1"
}

# Build the JSONC entry
$jsoncPython = Convert-ToJsoncPath $pythonExe
$jsoncServer = Convert-ToJsoncPath $serverPy

Write-Host ""
Write-Host "================================================"
Write-Host "  COPY THE BLOCK BELOW"
Write-Host "================================================"
Write-Host ""

Write-Host "@  MCP server name: citation-verifier"
Write-Host '@  Insert into your Kilo config under the "mcp" section.'
Write-Host '@  Your global config is typically: ~/.config/kilo/kilo.jsonc'
Write-Host "@  The config also supports a project-local .kilo/kilo.jsonc (overrides global)."
Write-Host ""

# Build the JSONC configuration block as individual lines
# Using single-quoted strings for static JSON text, concatenating variables
Write-Host ('"citation-verifier": {')
Write-Host ('  "type": "local",')
Write-Host ('  "command": [')
Write-Host ("    `"$jsoncPython`",")
Write-Host ("    `"$jsoncServer`"")
Write-Host ('  ],')
Write-Host ('  "enabled": true,')
Write-Host ('  "timeout": 600000')
Write-Host ('}')

Write-Host ""
Write-Host "================================================"
Write-Host "  OPTIONAL: Permission Guidance"
Write-Host "================================================"
Write-Host ""
Write-Host "To allow all Citation Verifier tools without prompting, add under"
Write-Host 'the "permission" section of your Kilo configuration:'
Write-Host ""
Write-Host '"citation-verifier_*": "allow"'

Write-Host ""
Write-Host "================================================"
Write-Host "  NEXT STEPS"
Write-Host "================================================"
Write-Host ""
Write-Host "1. Copy the JSON block above (lines between the markers)."
Write-Host "2. Open your Kilo config file:"
Write-Host "      Global:  ~/.config/kilo/kilo.jsonc"
Write-Host "      Project: <your-repo>/.kilo/kilo.jsonc (overrides global if present)"
Write-Host '3. Paste it inside the "mcp" section of your config, preserving JSON validity.'
Write-Host "4. (Optional) Add the permission line under the ""permission"" object."
Write-Host '5. Reload the VS Code/Kilo window: Ctrl+Shift+P -> Developer: Reload Window.'
Write-Host "6. Open Kilo and create a new session."
Write-Host "7. Run 'tools/list' - you should see:"
Write-Host "      verify_document"
Write-Host "      verify_bibliography"
Write-Host "      citation_summary"
Write-Host "      verify_claim"
Write-Host "      verify_claims"
Write-Host ""

if ($allPrereqsMet) {
    Write-Host "All prerequisites appear satisfied. You can now paste the configuration." -ForegroundColor Green
} else {
    Write-Host "Some prerequisites are missing. See warnings above." -ForegroundColor Yellow
}

exit 0
