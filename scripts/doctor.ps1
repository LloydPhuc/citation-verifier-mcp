<#
.SYNOPSIS
    Comprehensive environment diagnostics for Citation Verifier MCP.
.DESCRIPTION
    Checks Python, Docker, GROBID, and application readiness.
    No side effects: does not modify containers, install packages, or download models.
.NOTES
    Run from any directory; locates repository relative to script.
#>

[CmdletBinding()]
param(
    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string] $GrobiDHostPort = $env:GROBID_HOST_PORT
)

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

# ---------- Configuration ----------
$DefaultPort = 8070
$HostPort = if ($GrobiDHostPort) { [int]$GrobiDHostPort } else { $DefaultPort }
$GrobiDUrl = "http://127.0.0.1:$HostPort"
$HealthEndpoint = "$GrobiDUrl/api/isalive"
$ProjectContainerName = 'citation-verifier-grobid'
$ExternalContainerName = 'grobid'
$DockerComposeFile = Join-Path $PSScriptRoot '..\docker-compose.yml'

# ---------- Result Tracking ----------
$script:Results = @()

function Add-Result {
    param(
        [ValidateSet('PASS','WARN','FAIL','SKIP')]
        [string] $Status,
        [string] $Category,
        [string] $Check,
        [string] $Details
    )
    $script:Results += [PSCustomObject]@{
        Status = $Status
        Category = $Category
        Check = $Check
        Details = $Details
    }
}

function Write-Header {
    param([string]$Message)
    Write-Host ""
    Write-Host "================================================"
    Write-Host "  $Message"
    Write-Host "================================================"
}

# ---------- Helper Functions ----------

function Get-DockerCli {
    $docker = Get-Command 'docker.exe' -ErrorAction SilentlyContinue
    if ($docker) { return $docker.Source }
    $candidates = @(
        "${env:ProgramFiles}\Docker\Docker\resources\bin\docker.exe",
        "${env:ProgramFiles(x86)}\Docker\Docker\resources\bin\docker.exe",
        "${env:LOCALAPPDATA}\Docker\Docker\resources\bin\docker.exe",
        "${env:PROGRAMFILES}\Docker\Docker\resources\bin\docker.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    return $null
}

function Test-DockerEngine {
    param([string]$DockerExe)
    try { & $DockerExe version --format '{{.Server.Version}}' 2>$null | Out-Null; return $true }
    catch { return $false }
}

function Test-GrobiDHealth {
    param([string]$Url, [int]$TimeoutSec = 5)
    try {
        $response = Invoke-WebRequest -Uri $Url -Method GET -TimeoutSec $TimeoutSec -UseBasicParsing -ErrorAction Stop
        return ($response.StatusCode -eq 200 -and $response.Content.Trim() -eq 'true')
    } catch { return $false }
}

function Get-ContainerStatus {
    param([string]$ContainerName)
    $dockerExe = Get-DockerCli
    if (-not $dockerExe) { return $null }
    try {
        $status = & $dockerExe inspect -f '{{.State.Status}} {{.State.Health.Status}}' $ContainerName 2>$null
        if ($LASTEXITCODE -eq 0 -and $status) {
            $parts = $status.Split(' ')
            return @{ Status = $parts[0]; Health = if ($parts.Count -gt 1) { $parts[1] } else { 'none' } }
        }
    } catch { }
    return $null
}

# ============================================================
# PYTHON DIAGNOSTICS
# ============================================================
Write-Header "PYTHON ENVIRONMENT"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
Add-Result 'PASS' 'Python' 'Repository Root' "Found at $RepoRoot"

# Python availability
$PythonExe = $null
if (Get-Command 'python.exe' -ErrorAction SilentlyContinue) { $PythonExe = 'python.exe' }
elseif (Get-Command 'python3.exe' -ErrorAction SilentlyContinue) { $PythonExe = 'python3.exe' }
elseif (Get-Command 'py.exe' -ErrorAction SilentlyContinue) { $PythonExe = 'py.exe' }

if ($PythonExe) {
    try {
        $version = & $PythonExe --version 2>&1
        Add-Result 'PASS' 'Python' 'Python Available' "$PythonExe -> $version"
    } catch {
        Add-Result 'FAIL' 'Python' 'Python Version' "Failed to get version"
    }
} else {
    Add-Result 'FAIL' 'Python' 'Python Available' 'No python executable found in PATH'
}

# .venv existence
$VenvPath = Join-Path $RepoRoot '.venv'
if (Test-Path $VenvPath) {
    Add-Result 'PASS' 'Python' 'Virtual Environment' "Found at $VenvPath"
    $VenvPython = Join-Path $VenvPath 'Scripts\python.exe'
    if (Test-Path $VenvPython) {
        Add-Result 'PASS' 'Python' 'Venv Python' "Found at $VenvPython"
    } else {
        Add-Result 'WARN' 'Python' 'Venv Python' 'Scripts/python.exe not found in .venv'
    }
} else {
    Add-Result 'SKIP' 'Python' 'Virtual Environment' 'No .venv directory (run bootstrap.ps1 to create)'
}

# Required module availability
$RequiredModules = @('mcp', 'pdfplumber', 'rank_bm25', 'requests', 'torch', 'transformers', 'sentencepiece')
$ModulePython = $VenvPython
if (-not $ModulePython) { $ModulePython = $PythonExe }
if ($ModulePython) {
    foreach ($mod in $RequiredModules) {
        try {
            & $ModulePython -c "import $mod" 2>$null
            if ($LASTEXITCODE -eq 0) {
                Add-Result 'PASS' 'Python' "Module: $mod" 'Available'
            } else {
                Add-Result 'FAIL' 'Python' "Module: $mod" 'Not installed'
            }
        } catch {
            Add-Result 'FAIL' 'Python' "Module: $mod" 'Import error'
        }
    }
} else {
    foreach ($mod in $RequiredModules) {
        Add-Result 'SKIP' 'Python' "Module: $mod" 'No Python to test'
    }
}

# academic-refchecker executable
$RefCheckerPath = Join-Path $RepoRoot '.venv\Scripts\academic-refchecker.exe'
$RefCheckerFound = $false
if (Test-Path $RefCheckerPath) {
    Add-Result 'PASS' 'Python' 'academic-refchecker' "Found at $RefCheckerPath"
    $RefCheckerFound = $true
}
if (-not $RefCheckerFound) {
    Add-Result 'WARN' 'Python' 'academic-refchecker' 'Not found (install via bootstrap.ps1 or external source)'
}

# ============================================================
# DOCKER DIAGNOSTICS
# ============================================================
Write-Header "DOCKER ENVIRONMENT"

$dockerExe = Get-DockerCli
if ($dockerExe) {
    Add-Result 'PASS' 'Docker' 'Docker CLI' "Found at $dockerExe"
} else {
    Add-Result 'FAIL' 'Docker' 'Docker CLI' 'Not found in PATH or common locations'
    $dockerExe = $null
}

if ($dockerExe) {
    if (Test-DockerEngine $dockerExe) {
        Add-Result 'PASS' 'Docker' 'Docker Engine' 'Responding'
        # Compose availability
        try {
            & docker compose version 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Add-Result 'PASS' 'Docker' 'Docker Compose' 'Available'
            } else {
                Add-Result 'FAIL' 'Docker' 'Docker Compose' 'Not available'
            }
        } catch {
            Add-Result 'FAIL' 'Docker' 'Docker Compose' 'Error checking version'
        }
    } else {
        Add-Result 'WARN' 'Docker' 'Docker Engine' 'Not responding (Docker Desktop may be stopped)'
    }

    # Compose config validity
    try {
        & docker compose -f $DockerComposeFile config 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Add-Result 'PASS' 'Docker' 'Compose Config' 'Valid'
        } else {
            Add-Result 'FAIL' 'Docker' 'Compose Config' 'Invalid configuration'
        }
    } catch {
        Add-Result 'FAIL' 'Docker' 'Compose Config' 'Error validating'
    }

    # Managed container
    $managedStatus = Get-ContainerStatus 'citation-verifier-grobid'
    if ($managedStatus) {
        if ($managedStatus.Status -eq 'running') {
            $health = if ($managedStatus.Health -eq 'healthy') { 'healthy' } else { $managedStatus.Health }
            Add-Result 'PASS' 'Docker' 'Managed Container' "Running ($health)"
        } else {
            Add-Result 'WARN' 'Docker' 'Managed Container' "Exists but $($managedStatus.Status)"
        }
    } else {
        Add-Result 'SKIP' 'Docker' 'Managed Container' 'Not created yet'
    }

    # External GROBID container
    $extStatus = Get-ContainerStatus 'grobid'
    if ($extStatus) {
        if ($extStatus.Status -eq 'running') {
            $health = if ($extStatus.Health -eq 'healthy') { 'healthy' } else { $extStatus.Health }
            Add-Result 'PASS' 'Docker' 'External GROBID' "Container 'grobid' running ($health)"
        } else {
            Add-Result 'WARN' 'Docker' 'External GROBID' "Container 'grobid' exists but $($extStatus.Status)"
        }
    } else {
        Add-Result 'SKIP' 'Docker' 'External GROBID' "Container 'grobid' not found"
    }
} else {
    Add-Result 'SKIP' 'Docker' 'All Docker Checks' 'Docker CLI not available'
}

# ============================================================
# GROBID DIAGNOSTICS
# ============================================================
Write-Header "GROBID SERVICE"

$GrobiDUrl = "http://127.0.0.1:$HostPort"
$HealthEndpoint = "$GrobiDUrl/api/isalive"
$GrobiDHealthy = Test-GrobiDHealth $HealthEndpoint

if ($GrobiDHealthy) {
    Add-Result 'PASS' 'GROBID' 'Health Endpoint' "$HealthEndpoint returns true"
} else {
    Add-Result 'FAIL' 'GROBID' 'Health Endpoint' "$HealthEndpoint not responding or not healthy"
}

# Determine source of GROBID service
$dockerExe = Get-DockerCli
$managedRunning = $false
$externalRunning = $false

if ($dockerExe) {
    $managedStatus = Get-ContainerStatus 'citation-verifier-grobid'
    $externalStatus = Get-ContainerStatus 'grobid'

    if ($managedStatus -and $managedStatus.Status -eq 'running') {
        $managedRunning = $true
    }
    if ($externalStatus -and $externalStatus.Status -eq 'running') {
        $externalRunning = $true
    }
}

if ($GrobiDHealthy) {
    if ($managedRunning -and -not $externalRunning) {
        Add-Result 'PASS' 'GROBID' 'Service Source' 'Managed container (citation-verifier-grobid) is providing GROBID'
    } elseif ($externalRunning -and -not $managedRunning) {
        Add-Result 'PASS' 'GROBID' 'Service Source' "External container 'grobid' is providing GROBID"
    } elseif ($managedRunning -and $externalRunning) {
        Add-Result 'WARN' 'GROBID' 'Service Source' 'Both managed and external containers running - ambiguous ownership'
    } else {
        Add-Result 'WARN' 'GROBID' 'Service Source' 'Healthy endpoint but no known container running (external process?)'
    }
} else {
    if ($managedRunning) {
        Add-Result 'WARN' 'GROBID' 'Service State' "Managed container running but health check failing"
    } elseif ($externalRunning) {
        Add-Result 'WARN' 'GROBID' 'Service State' "External 'grobid' running but health check failing"
    } else {
        Add-Result 'FAIL' 'GROBID' 'Service State' 'No GROBID service available'
    }
}

# Custom port support
if ($HostPort -ne 8070) {
    $expectedUrl = "http://127.0.0.1:$HostPort"
    $expectedEnv = "GROBID_URL=http://127.0.0.1:$HostPort"
    Add-Result 'PASS' 'GROBID' 'Custom Port' "Using port $HostPort; ensure $expectedEnv is set for MCP server"
}

# ============================================================
# PYTHON APPLICATION DIAGNOSTICS
# ============================================================
Write-Header "PYTHON APPLICATION"

# File existence
$RequiredFiles = @(
    'server.py',
    'citation_v2\__init__.py',
    'citation_v2\config.py',
    'citation_v2\schemas.py',
    'citation_v2\batch.py',
    'citation_v2\verifier.py',
    'citation_v2\source_loader.py',
    'citation_v2\text_extractor.py',
    'citation_v2\nli.py',
    'citation_v2\retrieval.py',
    'citation_v2\chunker.py',
    'citation_v2\normalizer.py',
    'citation_v2\provenance.py',
    'citation_v2\database.py',
    'citation_v2\cache.py'
)

foreach ($f in $RequiredFiles) {
    $path = Join-Path $RepoRoot $f
    if (Test-Path $path) {
        Add-Result 'PASS' 'Application' "File: $f" 'Present'
    } else {
        Add-Result 'FAIL' 'Application' "File: $f" 'Missing'
    }
}

# Python compilation (if interpreter available)
$PythonTestExe = if (Test-Path (Join-Path $RepoRoot '.venv\Scripts\python.exe')) { Join-Path $RepoRoot '.venv\Scripts\python.exe' } elseif ($PythonExe) { $PythonExe } else { $null }

if ($PythonTestExe) {
    $CompileErrors = @()
    foreach ($f in $RequiredFiles) {
        $path = Join-Path $RepoRoot $f
        try {
            & $PythonTestExe -m py_compile $path 2>$null
            if ($LASTEXITCODE -ne 0) { $CompileErrors += $f }
        } catch { $CompileErrors += $f }
    }
    if ($CompileErrors.Count -eq 0) {
        Add-Result 'PASS' 'Application' 'Python Compilation' 'All modules compile successfully'
    } else {
        Add-Result 'FAIL' 'Application' 'Python Compilation' "Failed: $($CompileErrors -join ', ')"
    }
} else {
    Add-Result 'SKIP' 'Application' 'Python Compilation' 'No suitable Python interpreter'
}

# MCP tool discovery (requires dependencies)
$PythonMcpExe = if (Test-Path (Join-Path $RepoRoot '.venv\Scripts\python.exe')) { Join-Path $RepoRoot '.venv\Scripts\python.exe' } elseif ($PythonExe) { $PythonExe } else { $null }
$ExpectedTools = @('verify_document', 'verify_bibliography', 'citation_summary', 'verify_claim', 'verify_claims')

if ($PythonMcpExe) {
    try {
        $script = @"
import asyncio
import sys
sys.path.insert(0, '.')
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(
        command=sys.argv[1],
        args=[sys.argv[2]],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            for tool in result.tools:
                print(tool.name)
asyncio.run(main())
"@
        $result = & $PythonMcpExe -c $script $PythonMcpExe 'server.py' 2>&1
        $foundTools = $result.Split("`n") | Where-Object { $_ -match '\S' }
        $missing = @()
        foreach ($t in $ExpectedTools) {
            if ($foundTools -contains $t) {
                Add-Result 'PASS' 'MCP' "Tool: $t" 'Registered'
            } else {
                Add-Result 'FAIL' 'MCP' "Tool: $t" 'Missing from registration'
                $missing += $t
            }
        }
    } catch {
        Add-Result 'WARN' 'MCP' 'Tool Discovery' 'Dependencies not installed (run bootstrap.ps1)'
    }
} else {
    foreach ($t in $ExpectedTools) {
        Add-Result 'SKIP' 'MCP' "Tool: $t" 'No Python to test'
    }
}

# ============================================================
# FINAL REPORT
# ============================================================
Write-Header "DIAGNOSTIC SUMMARY"

$Pass = ($Results | Where-Object { $_.Status -eq 'PASS' }).Count
$Warn = ($Results | Where-Object { $_.Status -eq 'WARN' }).Count
$Fail = ($Results | Where-Object { $_.Status -eq 'FAIL' }).Count
$Skip = ($Results | Where-Object { $_.Status -eq 'SKIP' }).Count

$Results | Group-Object Category | ForEach-Object {
    $cat = $_.Name
    $p = ($_.Group | Where-Object { $_.Status -eq 'PASS' }).Count
    $w = ($_.Group | Where-Object { $_.Status -eq 'WARN' }).Count
    $f = ($_.Group | Where-Object { $_.Status -eq 'FAIL' }).Count
    $s = ($_.Group | Where-Object { $_.Status -eq 'SKIP' }).Count
    Write-Host "  [$cat] PASS:$p  WARN:$w  FAIL:$f  SKIP:$s"
}

Write-Host ""
Write-Host "TOTAL: PASS:$Pass  WARN:$Warn  FAIL:$Fail  SKIP:$Skip"
Write-Host ""

# Determine overall status
$OverallStatus = 'READY'
if ($Fail -gt 0) { $OverallStatus = 'NOT READY' }
elseif ($Warn -gt 0) { $OverallStatus = 'PARTIALLY READY' }

Write-Host "OVERALL: $OverallStatus"
Write-Host ""

if ($Fail -gt 0) {
    Write-Host "ACTION REQUIRED:"
    $Results | Where-Object { $_.Status -eq 'FAIL' } | ForEach-Object {
        Write-Host "  - [$($_.Category)] $($_.Check): $($_.Details)"
    }
} elseif ($Warn -gt 0) {
    Write-Host "WARNINGS:"
    $Results | Where-Object { $_.Status -eq 'WARN' } | ForEach-Object {
        Write-Host "  - [$($_.Category)] $($_.Check): $($_.Details)"
    }
} else {
    Write-Host "All checks passed. Environment is ready for Citation Verifier."
}

# Exit with appropriate code
if ($Fail -gt 0) { exit 1 } else { exit 0 }