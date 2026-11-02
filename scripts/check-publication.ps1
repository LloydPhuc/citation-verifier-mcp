<#
.SYNOPSIS
    Scan publication content locally. Exit 0 means the secret scan passed only.
.DESCRIPTION
    Requires Gitleaks 8.30.1 from its official release. Does not upload, install
    packages, run project code or grant publication approval. Independently require
    sandboxed tests, privacy review and a clean Windows restore before push.
#>
[CmdletBinding()]
param([string]$Gitleaks = 'gitleaks')
$ErrorActionPreference = 'Stop'
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Push-Location -LiteralPath $RepoRoot
try {
    $Version = & $Gitleaks version
    if ($LASTEXITCODE -ne 0 -or $Version.Trim() -ne '8.30.1') {
        throw 'Gitleaks 8.30.1 is required; verify the official release checksum.'
    }
    $Files = @(git -c core.quotePath=false ls-files --cached --others --exclude-standard)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot enumerate publication files.' }
    foreach ($File in $Files | Sort-Object -Unique) {
        if (Test-Path -LiteralPath $File -PathType Leaf) {
            & $Gitleaks dir $File --redact=100 --no-banner --log-level error `
                --ignore-gitleaks-allow --max-archive-depth 3 --max-decode-depth 3 --timeout 120
            if ($LASTEXITCODE -ne 0) { throw "Working-file scan failed: $File" }
        }
    }
    & $Gitleaks git . --staged --redact=100 --no-banner --ignore-gitleaks-allow --timeout 180
    if ($LASTEXITCODE -ne 0) { throw 'Staged-content scan failed.' }
    & $Gitleaks git . --log-opts '--all --full-history' --redact=100 --no-banner `
        --ignore-gitleaks-allow --timeout 180
    if ($LASTEXITCODE -ne 0) { throw 'History scan failed.' }
    git diff --check
    if ($LASTEXITCODE -ne 0) { throw 'Working diff whitespace check failed.' }
    git diff --cached --check
    if ($LASTEXITCODE -ne 0) { throw 'Staged diff whitespace check failed.' }
    Write-Output 'PASS: secret scan. Tests, privacy review and restoration remain separate gates.'
}
catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
}
finally { Pop-Location }
exit 0
