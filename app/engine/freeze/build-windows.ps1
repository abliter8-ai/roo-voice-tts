# IP-322 — freeze roo-engine and pinned qwentts native server (Windows x64).
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path; $EngineDir = Split-Path -Parent $Here
$Venv = if ($env:ROO_FREEZE_ENV) { $env:ROO_FREEZE_ENV } else { "$EngineDir\.freeze-venv" }; $Out = "$EngineDir\dist\roo-engine"
if (-not (Test-Path "$Venv\Scripts\pyinstaller.exe")) {
    python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "python venv creation failed: $LASTEXITCODE" }
    & "$Venv\Scripts\pip.exe" install --quiet -r "$Here\requirements-freeze.txt"
    if ($LASTEXITCODE -ne 0) { throw "freeze dependency install failed: $LASTEXITCODE" }
}
Write-Host "== [1/3] PyInstaller freeze (NumPy only) =="
Set-Location $EngineDir
& "$Venv\Scripts\pyinstaller.exe" --noconfirm --clean --onedir --name roo-engine --distpath dist --workpath build --specpath build --paths . freeze\freeze_entry.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed: $LASTEXITCODE" }
if (-not (Test-Path "$Out\roo-engine.exe")) { throw "freeze produced no exe" }
Write-Host "== [2/3] native qwentts (Vulkan + portable CPU fallback) =="
bash "$Here/build-native.sh" windows "$Out"
if ($LASTEXITCODE -ne 0) { throw "native qwentts build failed: $LASTEXITCODE" }
if (-not (Test-Path "$Out\tts-server.exe")) { throw "native server was not packaged" }
Write-Host "== verify native DLL closure =="
$dumpbin = Get-Command dumpbin.exe -ErrorAction Stop
$runtimePattern = '(?im)^\s*((?:concrt|msvcp|vcruntime|vcomp)\d*(?:_\d+)?\.dll)\s*$'
if (-not $env:VCToolsRedistDir) { throw "VCToolsRedistDir was not exported by vcvars64" }
$x64Redist = Join-Path $env:VCToolsRedistDir 'x64'
if (-not (Test-Path $x64Redist)) { throw "x64 MSVC redist root not found: $x64Redist" }
$crtRoots = @(Get-ChildItem -Path $x64Redist -Directory -Filter 'Microsoft.VC*.CRT' -ErrorAction SilentlyContinue)
if ($crtRoots.Count -ne 1) { throw "expected exactly one x64 MSVC CRT redist, found $($crtRoots.Count) under $x64Redist" }
$crtRoot = $crtRoots[0].FullName
$crtFamily = $crtRoots[0].Name -replace '\.CRT$', ''
$openMpRoots = @(Get-ChildItem -Path $x64Redist -Directory -Filter "$crtFamily.OpenMP" -ErrorAction SilentlyContinue)
if ($openMpRoots.Count -gt 1) { throw "ambiguous x64 MSVC OpenMP redist for $crtFamily" }
$redistRoots = @($crtRoot)
if ($openMpRoots.Count -eq 1) { $redistRoots += $openMpRoots[0].FullName }
Write-Host "x64 MSVC CRT redist: $crtRoot"
if ($openMpRoots.Count -eq 1) { Write-Host "x64 MSVC OpenMP redist: $($openMpRoots[0].FullName)" }
function Find-X64Runtime([string] $name) {
    foreach ($root in $redistRoots) {
        $candidate = Get-ChildItem -Path $root -File -Filter $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($candidate) { return $candidate }
    }
    return $null
}
$pending = [System.Collections.Generic.Queue[string]]::new()
$pending.Enqueue((Join-Path $Out 'tts-server.exe'))
$seen = @{}
while ($pending.Count -gt 0) {
    $binary = $pending.Dequeue()
    if ($seen.ContainsKey($binary)) { continue }
    $seen[$binary] = $true
    $depText = (& $dumpbin.Source /DEPENDENTS $binary | Out-String)
    if ($LASTEXITCODE -ne 0) { throw "dumpbin dependency inspection failed for $binary`: $LASTEXITCODE" }
    $runtimeNames = [regex]::Matches($depText, $runtimePattern) |
        ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
    foreach ($name in $runtimeNames) {
        $destination = Join-Path $Out $name
        if (-not (Test-Path $destination)) {
            $candidate = Find-X64Runtime $name
            if (-not $candidate) { throw "x64 native dependency not found: $name" }
            Copy-Item $candidate.FullName $destination -Force
            Write-Host "bundled x64 native runtime: $name"
        }
        $pending.Enqueue($destination)
    }
}
Write-Host "== [3/3] bundled resources =="
& "$Venv\Scripts\python.exe" "$Here\prepare-assets.py" --output "$Out"
if ($LASTEXITCODE -ne 0) { throw "asset preparation failed: $LASTEXITCODE" }
& "$Venv\Scripts\python.exe" "$Here\prepare-assets.py" --check --output "$Out"
if ($LASTEXITCODE -ne 0) { throw "asset check failed: $LASTEXITCODE" }
& "$Out\roo-engine.exe" --manifest "$Out\manifest.json" --native-bin "$Out\tts-server.exe" --data-dir "$EngineDir\dist\.smoke-data" --help | Out-Null
if ($LASTEXITCODE -ne 0) { throw "engine resource check failed: $LASTEXITCODE" }
Write-Host "OK: $Out (Vulkan linked; portable CPU fallback)"
