[CmdletBinding()]
param(
    [switch]$BuildInstaller,
    [switch]$Sign,
    [string]$CertificateThumbprint,
    [string]$TimestampUrl = "http://timestamp.digicert.com",
    [string]$PythonExecutable = "python",
    [string]$CaddyExecutable,
    [string]$ReleaseRoot = "D:\ScanToExcel-Releases"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$distributionRoot = Join-Path $projectRoot "dist\ScanToExcelApp"
$applicationExe = Join-Path $distributionRoot "ScanToExcelApp.exe"
$lockFile = Join-Path $projectRoot "requirements-package.lock"

function Invoke-ExternalCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $FilePath $($Arguments -join ' ')"
    }
}

function Resolve-SignTool {
    $fromPath = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($fromPath) {
        return $fromPath.Source
    }

    $kitsRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    if (Test-Path -LiteralPath $kitsRoot) {
        return Get-ChildItem -LiteralPath $kitsRoot -Filter signtool.exe -Recurse |
            Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
            Sort-Object FullName -Descending |
            Select-Object -First 1 -ExpandProperty FullName
    }

    return $null
}

function Invoke-SignArtifact {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not $Sign) {
        return
    }
    if (-not $CertificateThumbprint) {
        throw "-CertificateThumbprint is required when -Sign is used."
    }

    $signTool = Resolve-SignTool
    if (-not $signTool) {
        throw "signtool.exe was not found. Install the Windows SDK before signing."
    }

    Invoke-ExternalCommand -FilePath $signTool -Arguments @(
        "sign", "/sha1", $CertificateThumbprint, "/fd", "SHA256",
        "/tr", $TimestampUrl, "/td", "SHA256", $Path
    )
}

function Resolve-CaddyExecutable {
    if ($CaddyExecutable) {
        if (-not (Test-Path -LiteralPath $CaddyExecutable -PathType Leaf)) {
            throw "Caddy executable was not found: $CaddyExecutable"
        }
        return (Resolve-Path -LiteralPath $CaddyExecutable).Path
    }

    $fromPath = Get-Command caddy.exe -ErrorAction SilentlyContinue
    if ($fromPath) {
        return $fromPath.Source
    }

    $wingetRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path -LiteralPath $wingetRoot) {
        $candidate = Get-ChildItem -LiteralPath $wingetRoot -Directory -Filter "CaddyServer.Caddy_*" |
            ForEach-Object { Join-Path $_.FullName "caddy.exe" } |
            Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
            Select-Object -First 1
        if ($candidate) {
            return $candidate
        }
    }

    throw "Caddy was not found. Install Caddy or pass -CaddyExecutable."
}

Push-Location $projectRoot
try {
    $version = & $PythonExecutable -B -c "from server.release_info import APP_VERSION; print(APP_VERSION)"
    if ($LASTEXITCODE -ne 0 -or -not $version) {
        throw "Unable to read the application version."
    }
    $version = $version.Trim()
    $releaseDirectory = Join-Path $ReleaseRoot $version
    if (Test-Path -LiteralPath $releaseDirectory) {
        throw "Release directory already exists: $releaseDirectory"
    }

    Invoke-ExternalCommand -FilePath $PythonExecutable -Arguments @(
        "-B", "scripts\verify_packaging_lock.py", $lockFile
    )
    Invoke-ExternalCommand -FilePath $PythonExecutable -Arguments @(
        "-B", "-m", "pytest", "tests\test_packaging_runtime.py",
        "-p", "no:cacheprovider", "--basetemp", "scratch\pytest-packaging-build", "-q"
    )
    Invoke-ExternalCommand -FilePath $PythonExecutable -Arguments @(
        "-B", "-m", "PyInstaller", "--clean", "--noconfirm", "scan_to_excel.spec"
    )

    $caddySource = Resolve-CaddyExecutable
    $caddyVersion = (& $caddySource version).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $caddyVersion) {
        throw "Unable to read the bundled Caddy version."
    }
    Copy-Item -LiteralPath $caddySource -Destination (Join-Path $distributionRoot "caddy.exe") -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot "packaging\Start-ScanToExcelHost.cmd") -Destination $distributionRoot -Force

    if (-not (Test-Path -LiteralPath $applicationExe)) {
        throw "Packaged executable was not created: $applicationExe"
    }

    $forbiddenNames = @(
        ".env",
        "host.env",
        "database_engine",
        "cloudflared.exe"
    )
    $forbiddenArtifacts = Get-ChildItem -LiteralPath $distributionRoot -Force -Recurse |
        Where-Object { $_.Name -in $forbiddenNames }
    if ($forbiddenArtifacts) {
        $paths = ($forbiddenArtifacts.FullName -join ", ")
        throw "Forbidden deployment artifact found: $paths"
    }

    Invoke-SignArtifact $applicationExe
    New-Item -ItemType Directory -Path $releaseDirectory | Out-Null

    $zipPath = Join-Path $releaseDirectory "ScanToExcelApp_$version.zip"
    Compress-Archive -LiteralPath $distributionRoot -DestinationPath $zipPath -CompressionLevel Optimal

    if ($BuildInstaller) {
        $isccCandidates = @(
            (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
            (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
            (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
        ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
        $iscc = $isccCandidates | Select-Object -First 1
        if (-not $iscc) {
            throw "Inno Setup 6 was not found. Install it or omit -BuildInstaller."
        }

        Invoke-ExternalCommand -FilePath $iscc -Arguments @(
            "/DMyAppVersion=$version", "/O$releaseDirectory", "setup.iss"
        )
        $installerPath = Join-Path $releaseDirectory "ScanToExcelHost-Setup-$version.exe"
        if (-not (Test-Path -LiteralPath $installerPath)) {
            throw "Installer was not created: $installerPath"
        }
        Invoke-SignArtifact $installerPath
    }

    $artifacts = Get-ChildItem -LiteralPath $releaseDirectory -File | ForEach-Object {
        [ordered]@{
            file = $_.Name
            bytes = $_.Length
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
    $manifest = [ordered]@{
        application = "Scan To Excel Host"
        version = $version
        postgresql_major = 18
        caddy_version = $caddyVersion
        cloudflared_mode = "external-windows-service"
        built_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        signed = [bool]$Sign
        artifacts = @($artifacts)
    }
    $manifestPath = Join-Path $releaseDirectory "release-manifest.json"
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding utf8

    $hashLines = Get-ChildItem -LiteralPath $releaseDirectory -File |
        Where-Object { $_.Name -ne "SHA256SUMS.txt" } |
        ForEach-Object {
            $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            "$hash  $($_.Name)"
        }
    $hashLines | Set-Content -LiteralPath (Join-Path $releaseDirectory "SHA256SUMS.txt") -Encoding ascii

    Write-Host "Release package completed: $releaseDirectory"
} finally {
    Pop-Location
}
