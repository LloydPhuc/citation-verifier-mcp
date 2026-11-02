<#
.SYNOPSIS
    Remove generated project artifacts, never the environment, model or database.
.DESCRIPTION
    Stop MCP clients before use. -RuntimeCache also removes downloaded/extracted
    sources; later checks reload them. Use -WhatIf to preview. Does not clean
    global pip/Hugging Face caches, Docker, or other installations.
#>
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'Medium')]
param([switch]$RuntimeCache)

$ErrorActionPreference = 'Stop'
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$Names = @('.pytest_cache', '.pytest-tmp', '.mypy_cache', '.ruff_cache', '__pycache__')
$Targets = @($Names | ForEach-Object { Join-Path $RepoRoot $_ })
foreach ($SourceRoot in @('citation_v2', 'tests', 'scripts')) {
    $Targets += Join-Path (Join-Path $RepoRoot $SourceRoot) '__pycache__'
}
if ($RuntimeCache) {
    if ($env:CITATION_MCP_HOME -and
        [IO.Path]::GetFullPath($env:CITATION_MCP_HOME) -ne $RepoRoot) {
        throw 'Custom CITATION_MCP_HOME is set. Clean that runtime manually; nothing was removed.'
    }
    $Targets += Join-Path $RepoRoot 'cache'
}

# Validate the entire list before deleting anything. Never traverse junctions.
foreach ($Path in $Targets) {
    if (-not $Path.StartsWith($RepoRoot + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase)) {
        throw "Cleanup target is outside the project: $Path"
    }
    # Check ancestors too: citation_v2 or the checkout itself may be a junction.
    $Ancestor = $Path
    while ($Ancestor) {
        if (Test-Path -LiteralPath $Ancestor) {
            if ((Get-Item -LiteralPath $Ancestor -Force).Attributes -band
                    [IO.FileAttributes]::ReparsePoint) {
                throw "Refusing to clean a linked path: $Ancestor"
            }
        }
        $Ancestor = Split-Path -Parent $Ancestor
    }
    if (Test-Path -LiteralPath $Path) {
        $Pending = [Collections.Generic.Stack[string]]::new()
        $Pending.Push($Path)
        while ($Pending.Count) {
            $Item = Get-Item -LiteralPath $Pending.Pop() -Force
            if ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Refusing to clean a linked path: $($Item.FullName)"
            }
            if ($Item.PSIsContainer) {
                foreach ($Child in Get-ChildItem -LiteralPath $Item.FullName -Force) {
                    $Pending.Push($Child.FullName)
                }
            }
        }
    }
}
foreach ($Path in $Targets) {
    if ((Test-Path -LiteralPath $Path) -and $PSCmdlet.ShouldProcess($Path, 'Remove generated files')) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}
