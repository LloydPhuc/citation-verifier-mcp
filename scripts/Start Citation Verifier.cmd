@echo off
REM ================================================================
REM Start Citation Verifier - One-click GROBID launcher
REM ================================================================
REM Locates start.ps1 relative to this script and executes it.
REM Works regardless of where the repository is located on Windows.
REM ================================================================

setlocal enabledelayedexpansion

REM Get the directory of this .cmd file
set "SCRIPT_DIR=%~dp0"

REM Resolve the full path to start.ps1
set "PS1_PATH=%SCRIPT_DIR%start.ps1"

echo ================================================================
echo   Citation Verifier - GROBID Startup Launcher
echo ================================================================
echo.

REM Check if start.ps1 exists
if not exist "%PS1_PATH%" (
    echo ERROR: Cannot find start.ps1 at "%PS1_PATH%"
    echo.
    echo This launcher must be in the same directory as start.ps1
    echo (typically: scripts/Start Citation Verifier.cmd)
    echo.
    pause
    exit /b 1
)

REM Pass through any arguments (e.g., custom GROBID_HOST_PORT)
set "ARGS=%*"

echo Launching PowerShell startup script...
echo Script: %PS1_PATH%
if not "%ARGS%"=="" echo Arguments: %ARGS%
echo.

REM Execute the PowerShell script
REM -NoProfile: faster startup, no user profile
REM -ExecutionPolicy Bypass: allow script execution without policy changes
REM -File: execute the script file
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS1_PATH%" %ARGS%

set "EXIT_CODE=%ERRORLEVEL%"

echo.
if %EXIT_CODE% equ 0 (
    echo ================================================================
    echo  STARTUP COMPLETED SUCCESSFULLY
    echo ================================================================
) else (
    echo ================================================================
    echo  STARTUP FAILED (exit code %EXIT_CODE%)
    echo ================================================================
    echo.
    echo Check the output above for details.
    echo Common issues:
    echo   - Docker Desktop not installed or not running
    echo   - Port 8070 (or GROBID_HOST_PORT) already in use
    echo   - Insufficient permissions
    echo.
    echo For manual troubleshooting, run:
    echo   powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PS1_PATH%"
)

echo.
pause
exit /b %EXIT_CODE%