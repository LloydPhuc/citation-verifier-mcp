<#
.SYNOPSIS
    Safely stops the GROBID service managed by this repository.
.DESCRIPTION
    Identifies and stops only the project-managed GROBID container.
    Never stops the external 'grobid' container.
    Never deletes databases, caches, models, images or volumes.
.NOTES
    Uses Docker Compose project metadata for ownership verification.
    Safe to run repeatedly.
#>

[CmdletBinding()]
param(
    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string] $GrobiDHostPort = $env:GROBID_HOST_PORT
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# ---------- Configuration ----------
$DefaultPort = 8070
$HostPort = if ($GrobiDHostPort) { [int]$GrobiDHostPort } else { $DefaultPort }
$ProjectContainerName = 'citation-verifier-grobid'
$ExternalContainerName = 'grobid'
$DockerComposeFile = Join-Path $PSScriptRoot '..\docker-compose.yml'

# ---------- Helper Functions ----------

function Write-Step {
    param([string]$Message)
    $ts = Get-Date -Format 'HH:mm:ss'
    Write-Host "[$ts] $Message"
}

function Write-Success {
    param([string]$Message)
    $ts = Get-Date -Format 'HH:mm:ss'
    Write-Host "[$ts] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    $ts = Get-Date -Format 'HH:mm:ss'
    Write-Host "[$ts] $Message" -ForegroundColor Yellow
}

function Write-ErrorExit {
    param([string]$Message, [int]$ExitCode = 1)
    $ts = Get-Date -Format 'HH:mm:ss'
    Write-Host "[$ts] $Message" -ForegroundColor Red
    exit $ExitCode
}

function Get-DockerCli {
    $docker = Get-Command 'docker.exe' -ErrorAction SilentlyContinue
    if ($docker) {
        return $docker.Source
    }
    $candidates = @(
        "${env:ProgramFiles}\Docker\Docker\resources\bin\docker.exe",
        "${env:ProgramFiles(x86)}\Docker\Docker\resources\bin\docker.exe",
        "${env:LOCALAPPDATA}\Docker\Docker\resources\bin\docker.exe",
        "${env:PROGRAMFILES}\Docker\Docker\resources\bin\docker.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    return $null
}

function Test-DockerEngine {
    param([string]$DockerExe)
    try {
        & $DockerExe version --format '{{.Server.Version}}' 2>$null | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Get-ComposeProjectInfo {
    param([string]$ComposeFile)
    try {
        $result = & docker compose -f $ComposeFile config --format json 2>$null
        if ($LASTEXITCODE -eq 0 -and $result) {
            $json = $result | ConvertFrom-Json
            return $json
        }
    } catch { }
    return $null
}

function Get-ManagedContainer {
    param([string]$ComposeFile, [string]$ProjectContainerName)
    $dockerExe = Get-DockerCli
    if (-not $dockerExe) { return $null }

    # First try Docker Compose project label
    try {
        $containers = & $dockerExe ps -a --filter "label=com.docker.compose.project=citation-verifier-mcp" --format '{{.Names}}' 2>$null
        if ($containers) {
            foreach ($c in $containers) {
                if ($c -eq $ProjectContainerName) {
                    return $c
                }
            }
        }
    } catch { }

    # Fallback: exact container name match (created by this project's Compose)
    try {
        $status = & $dockerExe inspect -f '{{.State.Status}} {{.Config.Labels."com.docker.compose.project"}}' $ProjectContainerName 2>$null
        if ($LASTEXITCODE -eq 0 -and $status) {
            $parts = $status.Split(' ')
            if ($parts.Count -ge 2 -and $parts[1] -eq 'citation-verifier-mcp') {
                return $ProjectContainerName
            }
        }
    } catch { }

    return $null
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

# ---------- Main Logic ----------

Write-Host "================================================"
Write-Host "  Citation Verifier - GROBID Shutdown"
Write-Host "================================================"
Write-Host ""

# Resolve repository directory
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
Write-Step "Repository: $RepoRoot"

# [1/4] Discover Docker CLI
Write-Step "[1/4] Detecting Docker CLI..."
$dockerExe = Get-DockerCli
if (-not $dockerExe) {
    Write-Warn "Docker CLI not found. Nothing to stop."
    exit 0
}
Write-Success "Found Docker: $dockerExe"

# [2/4] Check Docker Engine
Write-Step "[2/4] Checking Docker Engine..."
if (-not (Test-DockerEngine $dockerExe)) {
    Write-Warn "Docker Engine not available. Cannot stop managed container."
    exit 0
}
Write-Success "Docker Engine is running"

# [3/4] Identify managed container
Write-Step "[3/4] Identifying managed GROBID container..."
$managedContainer = Get-ManagedContainer $DockerComposeFile $ProjectContainerName

if (-not $managedContainer) {
    Write-Success "No managed GROBID container found. Nothing to stop."
    exit 0
}

Write-Success "Found managed container: $managedContainer"

# [4/4] Verify ownership and stop
Write-Step "[4/4] Stopping managed GROBID container..."

# Double-check: ensure it's not the external container
$extStatus = Get-ContainerStatus $ExternalContainerName
if ($extStatus -and $managedContainer -eq $ExternalContainerName) {
    Write-ErrorExit "Ownership ambiguity: managed container name matches external 'grobid' container. Refusing to stop."
}

# Check container status
$managedStatus = Get-ContainerStatus $managedContainer
if ($managedStatus) {
    Write-Host "  Container status: $($managedStatus.Status)"
    if ($managedStatus.Health -ne 'none') {
        Write-Host "  Health: $($managedStatus.Health)"
    }
}

# Stop the container (do not remove)
try {
    & $dockerExe stop $managedContainer 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Managed GROBID container '$managedContainer' stopped"
    } else {
        Write-ErrorExit "Failed to stop container '$managedContainer'"
    }
} catch {
    Write-ErrorExit "Error stopping container: $_"
}

Write-Host ""
Write-Success "GROBID shutdown complete"
Write-Host "Note: Container '$managedContainer' preserved (not removed)."
Write-Host "Databases, caches, and model files are unaffected."
exit 0