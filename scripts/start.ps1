<#
.SYNOPSIS
    One-click startup for Citation Verifier GROBID service.
.DESCRIPTION
    Detects existing healthy GROBID, or starts managed GROBID via Docker Compose.
    Supports GROBID_HOST_PORT environment variable for custom host port.
.NOTES
    Does not stop or remove external containers. Does not take over occupied ports.
    Kilo launches server.py separately via MCP configuration.
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
$GrobiDUrl = "http://127.0.0.1:$HostPort"
$HealthEndpoint = "$GrobiDUrl/api/isalive"
$ProjectContainerName = 'citation-verifier-grobid'
$ExternalContainerName = 'grobid'
$DockerComposeFile = Join-Path $PSScriptRoot '..\docker-compose.yml'
$MaxDockerWaitSec = 60
$MaxHealthWaitSec = 120
$HealthCheckIntervalSec = 3
$DockerDesktopPaths = @(
    'C:\Program Files\Docker\Docker\Docker Desktop.exe',
    'C:\Program Files (x86)\Docker\Docker\Docker Desktop.exe',
    "${env:LOCALAPPDATA}\Docker\Docker Desktop.exe",
    "${env:PROGRAMFILES}\Docker\Docker\Docker Desktop.exe"
)

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

function Test-GrobiDHealth {
    param([string]$Url, [int]$TimeoutSec = 5)
    try {
        $response = Invoke-WebRequest -Uri $Url -Method GET -TimeoutSec $TimeoutSec -UseBasicParsing -ErrorAction Stop
        if ($response.StatusCode -eq 200 -and $response.Content.Trim() -eq 'true') {
            return $true
        }
    } catch {
        # Ignore - will return false
    }
    return $false
}

function Get-DockerCli {
    $docker = Get-Command 'docker.exe' -ErrorAction SilentlyContinue
    if ($docker) {
        return $docker.Source
    }
    # Fallback common locations
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

function Start-DockerDesktop {
    foreach ($path in $DockerDesktopPaths) {
        if (Test-Path $path) {
            Write-Step "Starting Docker Desktop: $path"
            try {
                $proc = Start-Process -FilePath $path -WindowStyle Hidden -PassThru
                return $true
            } catch {
                $errMsg = $_.Exception.Message
                Write-Warn ("Failed to start Docker Desktop at " + $path + ": " + $errMsg)
            }
        }
    }
    return $false
}

function Wait-DockerEngine {
    param([string]$DockerExe, [int]$MaxWaitSec)
    Write-Step "Waiting for Docker Engine (up to ${MaxWaitSec}s)..."
    $elapsed = 0
    while ($elapsed -lt $MaxWaitSec) {
        if (Test-DockerEngine $DockerExe) {
            Write-Success "Docker Engine is ready"
            return $true
        }
        Start-Sleep -Seconds 3
        $elapsed += 3
    }
    return $false
}

function Test-PortConflict {
    param([int]$Port, [string]$ContainerName)
    $dockerExe = Get-DockerCli
    if (-not $dockerExe) { return $false }
    try {
        $containers = & $dockerExe ps -a --filter "publish=$Port" --format '{{.Names}}' 2>$null
        if ($containers) {
            foreach ($c in $containers) {
                if ($c -ne $ContainerName) {
                    Write-Warn "Port $Port is already published by container: $c"
                    return $true
                }
            }
        }
    } catch { }
    return $false
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

function Start-ManagedGrobiD {
    param([int]$Port)
    Write-Step "[2/4] Starting managed GROBID via Docker Compose..."
    $env:GROBID_HOST_PORT = $Port.ToString()
    try {
        & docker compose -f $DockerComposeFile up -d 2>&1 | ForEach-Object { Write-Host "    $_" }
        if ($LASTEXITCODE -ne 0) {
            Write-ErrorExit "Docker Compose failed to start GROBID"
        }
        Write-Success "Docker Compose started project container"
    } catch {
        $errMsg = $_.Exception.Message
        Write-ErrorExit "Failed to run docker compose up: $errMsg"
    }
}

function Wait-GrobiDHealth {
    param([string]$Url, [int]$MaxWaitSec)
    Write-Step "[3/4] Waiting for GROBID health at $Url (up to ${MaxWaitSec}s)..."
    $elapsed = 0
    while ($elapsed -lt $MaxWaitSec) {
        if (Test-GrobiDHealth $Url) {
            Write-Success "GROBID health check passed"
            return $true
        }
        Start-Sleep -Seconds $HealthCheckIntervalSec
        $elapsed += $HealthCheckIntervalSec
    }
    return $false
}

# ---------- Main Logic ----------

Write-Host "================================================"
Write-Host "  Citation Verifier - GROBID Startup"
Write-Host "================================================"
Write-Host ""

# [1/4] Check for existing healthy GROBID
Write-Step "[1/4] Checking for existing GROBID at $HealthEndpoint..."
if (Test-GrobiDHealth $HealthEndpoint) {
    # Try to identify if it's our managed container or external
    $dockerExe = Get-DockerCli
    $isManaged = $false
    $isExternal = $false

    if ($dockerExe) {
        $status = Get-ContainerStatus $ProjectContainerName
        if ($status -and $status.Status -eq 'running' -and $status.Health -eq 'healthy') {
            $isManaged = $true
        } else {
            $extStatus = Get-ContainerStatus $ExternalContainerName
            if ($extStatus -and $extStatus.Status -eq 'running') {
                $isExternal = $true
            }
        }
    }

    if ($isManaged) {
        Write-Success "EXISTING GROBID (MANAGED): READY - container '$ProjectContainerName' is healthy"
    } elseif ($isExternal) {
        Write-Success "EXISTING GROBID (EXTERNAL): READY - container '$ExternalContainerName' is running"
        Write-Warn "Using external GROBID container. This project will not manage it."
    } else {
        Write-Success "EXISTING GROBID: READY - healthy endpoint detected at $HealthEndpoint"
    }

    Write-Host ""
    Write-Host "GROBID endpoint: $GrobiDUrl"
    Write-Host "Set GROBID_URL=$GrobiDUrl in your environment for the MCP server."
    Write-Host ""
    exit 0
}

Write-Warn "No healthy GROBID detected at $HealthEndpoint"

# Check for port conflict before proceeding
if (Test-PortConflict $HostPort $ProjectContainerName) {
    Write-ErrorExit "Port $HostPort is occupied by another container. Cannot start managed GROBID. Set GROBID_HOST_PORT to a free port or stop the conflicting container."
}

# [2/4] Detect Docker CLI
Write-Step "[2/4] Detecting Docker CLI..."
$dockerExe = Get-DockerCli
if (-not $dockerExe) {
    Write-ErrorExit "Docker CLI not found. Install Docker Desktop for Windows."
}
Write-Success "Found Docker: $dockerExe"

# [3/4] Ensure Docker Engine is running
if (-not (Test-DockerEngine $dockerExe)) {
    Write-Warn "Docker Engine not responding. Attempting to start Docker Desktop..."
    if (Start-DockerDesktop) {
        if (-not (Wait-DockerEngine $dockerExe $MaxDockerWaitSec)) {
            Write-ErrorExit "Docker Engine did not become ready within ${MaxDockerWaitSec}s"
        }
    } else {
        Write-ErrorExit "Could not start Docker Desktop. Start it manually and re-run."
    }
} else {
    Write-Success "Docker Engine is running"
}

# [4/4] Start managed GROBID and wait for health
Start-ManagedGrobiD $HostPort

if (Wait-GrobiDHealth $HealthEndpoint $MaxHealthWaitSec) {
    Write-Host ""
    Write-Host "================================================"
    Write-Host "  GROBID MANAGED: READY"
    Write-Host "================================================"
    Write-Host ""
    Write-Host "GROBID endpoint: $GrobiDUrl"
    Write-Host "Container: $ProjectContainerName"
    Write-Host "Set GROBID_URL=$GrobiDUrl in your environment for the MCP server."
    if ($HostPort -ne $DefaultPort) {
        Write-Host ""
        Write-Host "NOTE: Using custom port $HostPort."
        Write-Host "Ensure GROBID_URL=http://127.0.0.1:$HostPort is set for the MCP server."
    }
    exit 0
} else {
    $logCmd = "docker logs $ProjectContainerName"
    Write-ErrorExit "GROBID health check failed after ${MaxHealthWaitSec}s. Check container logs with: $logCmd"
}