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
Write-Host "== [3/3] bundled resources =="
& "$Venv\Scripts\python.exe" "$Here\prepare-assets.py" --output "$Out"
if ($LASTEXITCODE -ne 0) { throw "asset preparation failed: $LASTEXITCODE" }
& "$Venv\Scripts\python.exe" "$Here\prepare-assets.py" --check --output "$Out"
if ($LASTEXITCODE -ne 0) { throw "asset check failed: $LASTEXITCODE" }
& "$Out\roo-engine.exe" --manifest "$Out\manifest.json" --native-bin "$Out\tts-server.exe" --data-dir "$EngineDir\dist\.smoke-data" --help | Out-Null
if ($LASTEXITCODE -ne 0) { throw "engine resource check failed: $LASTEXITCODE" }
Write-Host "OK: $Out (Vulkan linked; portable CPU fallback)"
