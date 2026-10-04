<#
.SYNOPSIS
    Bootstrap a fresh Python environment for Citation Verifier MCP.
.DESCRIPTION
    Creates a virtual environment, installs dependencies, verifies RefChecker,
    and prepares the NLI model for local inference.
    Safe to rerun. Does not modify Kilo config or global settings.
.NOTES
    Run from the repository root: .\scripts\bootstrap.ps1
    Requires internet access for initial dependency and model downloads.
#>

[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# ---------- Configuration ----------
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$VenvDir = Join-Path $RepoRoot '.venv'
$RequirementsFile = Join-Path $RepoRoot 'requirements.txt'
$MinPythonVersion = [version]'3.13'
$PreferredPythonVersion = '3.13'
$NLIModelId = 'cross-encoder/nli-deberta-v3-small'
$PyTorchCpuIndex = 'https://download.pytorch.org/whl/cpu'
$MaxInstallTimeoutSec = 600

# ---------- Helper Functions ----------

function Write-Step {
    param([string]$Step, [string]$Message)
    Write-Host "[$Step] $Message"
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

function Write-ErrorExit {
    param([string]$Message, [int]$ExitCode = 1)
    Write-Fail $Message
    Write-Host ""
    Write-Host "Bootstrap failed. See above for details." -ForegroundColor Red
    exit $ExitCode
}

function Get-PythonVersion {
    param([string]$Executable)
    $output = & $Executable '--version' 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Could not run '$Executable' (exit code $LASTEXITCODE)."
    }
    $versionText = ($output -join "`n").Trim()
    if ($versionText -notmatch '^Python (\d+\.\d+\.\d+)$') {
        throw "Could not parse Python version from '$Executable': $versionText"
    }
    $detectedVersion = [version]$Matches[1]
    if ($detectedVersion -lt $MinPythonVersion) {
        throw "Python $detectedVersion at '$Executable' is unsupported. Python >= $MinPythonVersion is required."
    }
    return $detectedVersion
}

# ---------- [1/7] Checking Python ----------

Write-Host ""
Write-Host "================================================"
Write-Host "  Citation Verifier MCP - Environment Bootstrap"
Write-Host "================================================"
Write-Host ""
Write-Host "Repository: $RepoRoot"
Write-Host ""

Write-Step "1/7" "Checking Python installation..."

$PythonExe = $null
$SkipVenvCreation = $false

# Try preferred Python 3.13 first
$pyLauncher = Get-Command 'py.exe' -ErrorAction SilentlyContinue
if ($pyLauncher) {
    try {
        $resolvedPython = & ($pyLauncher.Source) "-$PreferredPythonVersion" '-c' 'import sys; print(sys.executable)' 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "py launcher could not resolve Python $PreferredPythonVersion."
        }
        $resolvedPath = ($resolvedPython -join "`n").Trim()
        if (-not [IO.Path]::IsPathRooted($resolvedPath) -or
            -not (Test-Path -LiteralPath $resolvedPath -PathType Leaf)) {
            throw "py launcher returned an invalid interpreter path: $resolvedPath"
        }
        $pythonVersion = Get-PythonVersion $resolvedPath
        $PythonExe = $resolvedPath
        Write-Success "Found Python $pythonVersion via py launcher: $PythonExe"
    } catch {
        Write-Warn "Preferred Python unavailable: $_"
    }
}

# Try compatible interpreters on PATH if the preferred launcher selection fails.
if (-not $PythonExe) {
    $candidates = @(
        'python3.13',
        'python3',
        'python'
    )
    foreach ($cmd in $candidates) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($found) {
            try {
                $pythonVersion = Get-PythonVersion $found.Source
                $PythonExe = $found.Source
                Write-Success "Found Python $pythonVersion at $PythonExe"
                break
            } catch {
                Write-Warn "Skipping '$($found.Source)': $_"
            }
        }
    }
}

if (-not $PythonExe) {
    Write-ErrorExit "No suitable Python found. Python >= $MinPythonVersion is required. Install Python 3.13 or newer from https://www.python.org/downloads/"
}

# Verify version
try {
    $pythonVersion = Get-PythonVersion $PythonExe
    Write-Success "Python version: $pythonVersion (minimum required: $MinPythonVersion)"
} catch {
    Write-ErrorExit "Selected interpreter validation failed: $_ No virtual environment was changed."
}

# ---------- [2/7] Preparing virtual environment ----------

Write-Step "2/7" "Preparing virtual environment..."

if (Test-Path -LiteralPath $VenvDir) {
    $venvPython = Join-Path $VenvDir 'Scripts\python.exe'
    if ($Force) {
        # Do not follow a linked environment outside this checkout when deleting.
        $resolvedVenvPath = (Resolve-Path -LiteralPath $VenvDir).Path
        $expectedVenvPath = [IO.Path]::GetFullPath((Join-Path $RepoRoot '.venv'))
        if ($resolvedVenvPath -ne $expectedVenvPath) {
            Write-ErrorExit "Refusing to recreate .venv outside the expected checkout path: $resolvedVenvPath"
        }
        $venvItem = Get-Item -LiteralPath $VenvDir -Force
        if ($venvItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            Write-ErrorExit "Refusing to recreate a linked .venv at '$VenvDir'. Preserve it and use a private checkout environment."
        }
        Write-Warn "Existing .venv found. Recreating due to -Force flag..."
        Remove-Item -LiteralPath $VenvDir -Recurse -Force
    } else {
        if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
            Write-ErrorExit "Existing .venv has no Python interpreter at '$venvPython'. It was preserved. Back it up before explicitly choosing -Force, or use a fresh checkout."
        }
        try {
            $venvVersion = Get-PythonVersion $venvPython
        } catch {
            Write-ErrorExit "Existing .venv cannot be reused: $_ It was preserved. Back it up before explicitly choosing -Force, or use a fresh checkout."
        }
        Write-Success "Existing .venv uses Python $venvVersion. Reusing."
        Write-Host "  Location: $VenvDir"
        Write-Host "  Use -Force to recreate from scratch."
        $SkipVenvCreation = $true
    }
}

if (-not $SkipVenvCreation) {
    Write-Host "  Creating virtual environment at: $VenvDir"
    try {
        & $PythonExe '-m' 'venv' $VenvDir 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-ErrorExit "Failed to create virtual environment."
        }
        Write-Success "Virtual environment created."
    } catch {
        Write-ErrorExit "Failed to create virtual environment: $_"
    }
}

$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$VenvPip = Join-Path $VenvDir 'Scripts\pip.exe'

if (-not (Test-Path $VenvPython)) {
    Write-ErrorExit "Virtual environment python.exe not found at: $VenvPython"
}

# Check the resulting environment before any package installation.
try {
    $venvVersion = Get-PythonVersion $VenvPython
} catch {
    Write-ErrorExit "Virtual environment validation failed: $_ No packages were installed. Preserve the environment before recovery."
}

Write-Success "Venv Python: $VenvPython"

# ---------- [3/7] Installing dependencies ----------

Write-Step "3/7" "Installing runtime dependencies..."

if (-not (Test-Path $RequirementsFile)) {
    Write-ErrorExit "requirements.txt not found at: $RequirementsFile"
}

# Upgrade pip first
Write-Host "  Upgrading pip..."
& $VenvPython -m pip install --upgrade pip --quiet 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Warn "pip upgrade failed, continuing with existing pip."
}

# Install PyTorch CPU separately (requires specialized index)
Write-Host "  Installing PyTorch (CPU) from PyTorch index..."
& $VenvPython -m pip install torch==2.14.0+cpu --index-url $PyTorchCpuIndex --quiet 2>&1 | ForEach-Object {
    if ($_ -match 'ERROR') { Write-Host "    $_" -ForegroundColor Red }
}
if ($LASTEXITCODE -ne 0) {
    Write-ErrorExit "Failed to install PyTorch CPU. Ensure internet connectivity. Index: $PyTorchCpuIndex"
}
Write-Success "PyTorch CPU installed."

# Install remaining dependencies (excluding torch which is already installed)
Write-Host "  Installing remaining dependencies from requirements.txt..."
& $VenvPython -m pip install -r $RequirementsFile --quiet 2>&1 | ForEach-Object {
    if ($_ -match 'ERROR') { Write-Host "    $_" -ForegroundColor Red }
}
if ($LASTEXITCODE -ne 0) {
    Write-ErrorExit "Failed to install dependencies from requirements.txt"
}
Write-Success "All runtime dependencies installed."

# ---------- [4/7] Installing RefChecker ----------

Write-Step "4/7" "Verifying RefChecker CLI..."

$RefCheckerExe = Join-Path $VenvDir 'Scripts\academic-refchecker.exe'

if (Test-Path $RefCheckerExe) {
    Write-Success "RefChecker found at: $RefCheckerExe"
} else {
    Write-Warn "RefChecker not found. Installing academic-refchecker..."
    & $VenvPython -m pip install academic-refchecker==3.0.190 --quiet 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-ErrorExit "Failed to install academic-refchecker. Bibliography verification will not work."
    }
    if (Test-Path $RefCheckerExe) {
        Write-Success "RefChecker installed at: $RefCheckerExe"
    } else {
        Write-ErrorExit "academic-refchecker installed but executable not found at expected path: $RefCheckerExe"
    }
}

# ---------- [5/7] Preparing NLI model ----------

Write-Step "5/7" "Preparing NLI model ($NLIModelId)..."
Write-Host "  This downloads ~170MB on first run. Subsequent runs use the cache."

try {
    $modelCheck = & $VenvPython -c @"
import sys
sys.stdout.reconfigure(encoding='utf-8')
try:
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    model_id = '$NLIModelId'
    # Try loading from cache first
    try:
        tokenizer = AutoTokenizer.from_pretrained(model_id, local_files_only=True)
        model = AutoModelForSequenceClassification.from_pretrained(model_id, local_files_only=True)
        print('MODEL_CACHED')
    except Exception:
        # Download if not cached
        print('DOWNLOADING')
        tokenizer = AutoTokenizer.from_pretrained(model_id)
        model = AutoModelForSequenceClassification.from_pretrained(model_id)
        print('MODEL_DOWNLOADED')
except Exception as e:
    print(f'MODEL_ERROR: {e}')
    sys.exit(1)
"@ 2>&1

    $modelOutput = $modelCheck -join "`n"
    if ($modelOutput -match 'MODEL_CACHED') {
        Write-Success "NLI model already cached. No download needed."
    } elseif ($modelOutput -match 'MODEL_DOWNLOADED') {
        Write-Success "NLI model downloaded and cached successfully."
    } elseif ($modelOutput -match 'MODEL_ERROR') {
        Write-Warn "NLI model preparation issue: $modelOutput"
        Write-Warn "The model will be downloaded on first verification run."
        Write-Warn "Ensure internet connectivity is available when running verify_claim."
    } else {
        Write-Warn "Unexpected model check output: $modelOutput"
    }
} catch {
    Write-Warn "Could not verify NLI model: $_"
    Write-Warn "The model will be downloaded on first use."
}

# ---------- [6/7] Checking application imports ----------

Write-Step "6/7" "Verifying application imports..."

$ImportCheckScript = @"
import sys
sys.path.insert(0, r'$RepoRoot')
errors = []
try:
    import mcp
except ImportError as e:
    errors.append(f'mcp: {e}')
try:
    import pdfplumber
except ImportError as e:
    errors.append(f'pdfplumber: {e}')
try:
    import rank_bm25
except ImportError as e:
    errors.append(f'rank_bm25: {e}')
try:
    import requests
except ImportError as e:
    errors.append(f'requests: {e}')
try:
    import torch
except ImportError as e:
    errors.append(f'torch: {e}')
try:
    import transformers
except ImportError as e:
    errors.append(f'transformers: {e}')
try:
    import sentencepiece
except ImportError as e:
    errors.append(f'sentencepiece: {e}')
if errors:
    for err in errors:
        print(f'IMPORT_FAIL: {err}')
    sys.exit(1)
else:
    print('ALL_IMPORTS_OK')
"@

$importCheck = & ($VenvPython) '-c' $ImportCheckScript 2>&1
$importOutput = $importCheck -join "`n"
if ($importOutput -match 'ALL_IMPORTS_OK') {
    Write-Success "All required modules import successfully."
} else {
    Write-Fail "Import errors detected:"
    $importOutput | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    Write-ErrorExit "Application imports failed. See above."
}

# ---------- [7/7] Installation verification ----------

Write-Step "7/7" "Running final verification..."

$CompileCheckScript = @"
import sys, py_compile, pathlib
sys.path.insert(0, r'$RepoRoot')
repo = pathlib.Path(r'$RepoRoot')
files = [repo / 'server.py'] + list((repo / 'citation_v2').glob('*.py'))
errors = []
for f in files:
    try:
        py_compile.compile(str(f), doraise=True)
    except py_compile.PyCompileError as e:
        errors.append(str(e))
if errors:
    for e in errors:
        print(f'COMPILE_FAIL: {e}')
    sys.exit(1)
else:
    print(f'ALL_{len(files)}_FILES_COMPILE_OK')
"@

$compileResult = & ($VenvPython) '-c' $CompileCheckScript 2>&1
$compileOutput = $compileResult -join "`n"
if ($compileOutput -match 'ALL_\d+_FILES_COMPILE_OK') {
    Write-Success "All production Python files compile successfully."
} else {
    Write-Fail "Compilation errors:"
    $compileOutput | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    Write-ErrorExit "Compilation check failed."
}

# Verify RefChecker executable one more time
if (-not (Test-Path $RefCheckerExe)) {
    Write-ErrorExit "Final check: RefChecker executable missing at $RefCheckerExe"
}
Write-Success "RefChecker executable verified."

# ---------- Success ----------

Write-Host ""
Write-Host "================================================" -ForegroundColor Green
Write-Host "  BOOTSTRAP COMPLETE" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Environment ready at: $VenvDir"
Write-Host "Python: $VenvPython"
Write-Host ""
Write-Host "NEXT STEPS:"
Write-Host ""
Write-Host "  1. Start GROBID:"
Write-Host "     .\scripts\start.ps1"
Write-Host "     (or double-click scripts\Start Citation Verifier.cmd)"
Write-Host ""
Write-Host "  2. Run environment diagnostics:"
Write-Host "     .\scripts\doctor.ps1"
Write-Host ""
Write-Host "  3. Configure Kilo MCP (use scripts\print_kilo_config.ps1"
Write-Host "     when available in TASK 14)."
Write-Host ""
Write-Host "  The NLI model ($NLIModelId) is cached locally."
Write-Host "  No API keys or tokens are required for inference."
Write-Host ""

exit 0
