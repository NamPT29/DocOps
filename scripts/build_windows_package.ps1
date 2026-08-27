[CmdletBinding()]
param(
    [switch]$BuildInstaller
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$distributionRoot = Join-Path $projectRoot "dist\ScanToExcelApp"

Push-Location $projectRoot
try {
    python -m PyInstaller --clean --noconfirm scan_to_excel.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed with exit code $LASTEXITCODE."
    }

    $forbiddenNames = @(
        ".env",
        "host.env",
        "database_engine",
        "cloudflared.exe",
        "Caddy.exe"
    )
    $forbiddenArtifacts = Get-ChildItem -LiteralPath $distributionRoot -Force -Recurse |
        Where-Object { $_.Name -in $forbiddenNames }
    if ($forbiddenArtifacts) {
        $paths = ($forbiddenArtifacts.FullName -join ", ")
        throw "Forbidden deployment artifact found: $paths"
    }

    if ($BuildInstaller) {
        $isccCandidates = @(
            (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
            (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
        ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
        $iscc = $isccCandidates | Select-Object -First 1
        if (-not $iscc) {
            throw "Inno Setup 6 was not found. Install it or omit -BuildInstaller."
        }
        & $iscc setup.iss
        if ($LASTEXITCODE -ne 0) {
            throw "Inno Setup build failed with exit code $LASTEXITCODE."
        }
    }

    Write-Host "Package build completed: $distributionRoot"
} finally {
    Pop-Location
}
