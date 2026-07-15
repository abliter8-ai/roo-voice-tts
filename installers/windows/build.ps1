# Build the Roo Voice Windows installer (dist\Roo-Voice-Setup.exe).
# Prereq: Inno Setup 6 (https://jrsoftware.org/isdl.php) — ISCC.exe on PATH or in the default location.
# Run from this folder:  powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$pyUrl  = "https://github.com/astral-sh/python-build-standalone/releases/download/20260623/cpython-3.12.13+20260623-x86_64-pc-windows-msvc-install_only.tar.gz"
$repo   = (Resolve-Path "$PSScriptRoot\..\..").Path
$stage  = "$PSScriptRoot\staging"

Write-Host "==> clean staging"
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force -Path "$stage\python", "$stage\app\installers\common" | Out-Null

Write-Host "==> fetch standalone Python (cached)"
$tgz = "$PSScriptRoot\_py-win.tar.gz"
if (-not (Test-Path $tgz)) { Invoke-WebRequest -Uri $pyUrl -OutFile $tgz }
$tmp = "$PSScriptRoot\_pyx"; if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
tar -xzf $tgz -C $tmp                          # extracts to $tmp\python\
Copy-Item -Recurse -Force "$tmp\python\*" "$stage\python\"

Write-Host "==> stage app files"
Copy-Item -Recurse -Force "$repo\server","$repo\web","$repo\assets","$repo\reference.wav","$repo\README.md" "$stage\app\"
Copy-Item -Force "$repo\installers\common\bootstrap.py" "$stage\app\installers\common\"

Write-Host "==> compile with Inno Setup"
$iscc = "ISCC.exe"
if (-not (Get-Command $iscc -ErrorAction SilentlyContinue)) {
  foreach ($p in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe")) {
    if (Test-Path $p) { $iscc = $p; break }
  }
}
if (-not (Get-Command $iscc -ErrorAction SilentlyContinue) -and -not (Test-Path $iscc)) {
  throw "Inno Setup (ISCC.exe) not found. Install from https://jrsoftware.org/isdl.php"
}
& $iscc "$PSScriptRoot\roo-voice.iss"
Write-Host "==> DONE -> $PSScriptRoot\dist\Roo-Voice-Setup.exe"
