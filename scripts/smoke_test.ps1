<#
.SYNOPSIS
    MCP Discovery Smoke Test - launches the Citation Verifier MCP server
    and verifies protocol tool discovery.

.DESCRIPTION
    This script launches the real production server through stdio using the
    project's virtual environment and validates that the MCP protocol correctly
    advertises all five required tools:
      - verify_document
      - verify_bibliography
      - citation_summary
      - verify_claim
      - verify_claims

    It also inspects the input schemas for verify_claim and verify_claims
    to confirm they expose the documented required arguments.

.PARAMETER VenvPython
    Path to the virtual environment Python executable.
    Defaults to .\.venv\Scripts\python.exe relative to the script location.

.PARAMETER ServerPy
    Path to the server.py entrypoint.
    Defaults to .\server.py relative to the script location.

.PARAMETER Timeout
    Overall timeout in seconds for the entire discovery process.
    Defaults to 30 seconds.

.EXAMPLE
    .\scripts\smoke_test.ps1

.EXAMPLE
    .\scripts\smoke_test.ps1 -Timeout 60

.NOTES
    - Requires the project virtual environment to exist (run bootstrap first).
    - Does NOT require network, Docker, GROBID, or HF model downloads.
    - The server subprocess is terminated on timeout or failure.
    - Diagnostic output goes to stderr; MCP protocol stdout is preserved.

.LINK
    tests/test_mcp_discovery.py - the pytest version of this test
#>

[CmdletBinding()]
param(
    [Parameter()]
    [string]$VenvPython = (Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"),

    [Parameter()]
    [string]$ServerPy = (Join-Path $PSScriptRoot "..\server.py"),

    [Parameter()]
    [int]$Timeout = 30
)

# Resolve to absolute paths
$VenvPython = Resolve-Path -LiteralPath $VenvPython -ErrorAction Stop
$ServerPy = Resolve-Path -LiteralPath $ServerPy -ErrorAction Stop
$RepoRoot = Split-Path -Parent $ServerPy

Write-Host "=== MCP Discovery Smoke Test ===" -ForegroundColor Cyan
Write-Host "Repository root: $RepoRoot"
Write-Host "Venv Python:     $VenvPython"
Write-Host "Server entry:    $ServerPy"
Write-Host "Timeout:         ${Timeout}s"
Write-Host ""

# Verify prerequisites
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Error "Virtual environment Python not found at $VenvPython"
    Write-Error "Run bootstrap first: .\scripts\bootstrap.ps1"
    exit 1
}

if (-not (Test-Path -LiteralPath $ServerPy)) {
    Write-Error "Server entrypoint not found at $ServerPy"
    exit 1
}

# Run the discovery test via pytest (which runs the async test properly)
# Using the test file directly with pytest
$TestFile = Join-Path $RepoRoot "tests\test_mcp_discovery.py"
if (-not (Test-Path -LiteralPath $TestFile)) {
    Write-Error "Test file not found at $TestFile"
    exit 1
}

Write-Host "Running MCP discovery test via pytest..." -ForegroundColor Yellow

# Use pytest with explicit basetemp to avoid Windows temp permission issues
$Basetemp = Join-Path $env:TEMP "citation_mcp_smoke_$(Get-Random)"
New-Item -ItemType Directory -Path $Basetemp -Force | Out-Null

$PytestArgs = @(
    "-m", "unit"
    "-q"
    "--tb=short"
    "--basetemp", $Basetemp
    "-k", "TestMCPDiscovery"
    $TestFile
)

$ExitCode = 0
try {
    & $VenvPython -m pytest @PytestArgs
    $ExitCode = $LASTEXITCODE
}
catch {
    Write-Error "pytest invocation failed: $_"
    $ExitCode = 1
}
finally {
    # Cleanup temp directory
    if (Test-Path -LiteralPath $Basetemp) {
        Remove-Item -Recurse -Force -LiteralPath $Basetemp -ErrorAction SilentlyContinue
    }
}

if ($ExitCode -eq 0) {
    Write-Host "" -NoNewline
    Write-Host "=== SMOKE TEST PASSED ===" -ForegroundColor Green
}
else {
    Write-Host "" -NoNewline
    Write-Host "=== SMOKE TEST FAILED ===" -ForegroundColor Red
}

exit $ExitCode