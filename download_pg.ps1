$ErrorActionPreference = "Stop"

$pgVersion = "16.4-1"
$pgUrl = "https://get.enterprisedb.com/postgresql/postgresql-$pgVersion-windows-x64-binaries.zip"
$zipFile = "postgresql.zip"
$extractPath = "database_engine"

Write-Host "Downloading PostgreSQL Portable ($pgVersion)... This might take a while (~100MB)."
Invoke-WebRequest -Uri $pgUrl -OutFile $zipFile

Write-Host "Extracting PostgreSQL..."
Expand-Archive -Path $zipFile -DestinationPath ".\" -Force

Write-Host "Moving to database_engine folder..."
if (Test-Path $extractPath) {
    Remove-Item -Recurse -Force $extractPath
}
Rename-Item -Path "pgsql" -NewName $extractPath

Write-Host "Cleaning up..."
Remove-Item $zipFile

Write-Host "Done! PostgreSQL Portable is now in $extractPath."
