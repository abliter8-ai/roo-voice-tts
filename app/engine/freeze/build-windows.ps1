# IP-178 — freeze roo-engine (Windows x64) into a self-contained onedir bundle.
# DRAFT: authored on macOS, validated on CI / design8-snap2 (emulated x64) —
# treat first run as a test, not a given.
#
# Output: app\engine\dist\roo-engine\
#   roo-engine.exe + _internal\        frozen python + onnxruntime + phonemizer
#   espeak-ng.dll + espeak-ng-data\    from the official espeak-ng MSI (admin-extract)
#   llama-server.exe + *.dll           official ggml-org win-vulkan-x64 build
#                                      (Vulkan covers NVIDIA/AMD/Intel; no 370MB cudart)
$ErrorActionPreference = "Stop"

$Here      = Split-Path -Parent $MyInvocation.MyCommand.Path   # app\engine\freeze
$EngineDir = Split-Path -Parent $Here                          # app\engine
$Venv      = if ($env:ROO_FREEZE_ENV) { $env:ROO_FREEZE_ENV } else { "$EngineDir\.freeze-venv" }
$LlamaTag  = if ($env:LLAMA_TAG) { $env:LLAMA_TAG } else { "b10068" }
$EspeakVer = if ($env:ESPEAK_VER) { $env:ESPEAK_VER } else { "1.52.0" }
$Out       = "$EngineDir\dist\roo-engine"

Write-Host "== [1/4] freeze venv =="
if (-not (Test-Path "$Venv\Scripts\python.exe")) {
    python -m venv $Venv
    & "$Venv\Scripts\pip" install --quiet phonemizer onnxruntime numpy pyinstaller
}

Write-Host "== [2/4] PyInstaller freeze =="
Set-Location $EngineDir
& "$Venv\Scripts\pyinstaller" --noconfirm --clean --onedir --name roo-engine `
    --distpath dist --workpath build --specpath build `
    --collect-data language_tags --collect-data csvw --collect-data segments `
    --collect-data phonemizer `
    --paths . freeze\freeze_entry.py
if (-not (Test-Path "$Out\roo-engine.exe")) { throw "freeze produced no exe" }

Write-Host "== [3/4] vendor espeak-ng $EspeakVer =="
$Tmp = Join-Path $env:TEMP "espeak-extract"
Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $Tmp | Out-Null
$Msi = Join-Path $Tmp "espeak-ng.msi"
Invoke-WebRequest -Uri "https://github.com/espeak-ng/espeak-ng/releases/download/$EspeakVer/espeak-ng.msi" -OutFile $Msi
Start-Process msiexec -ArgumentList "/a `"$Msi`" /qn TARGETDIR=`"$Tmp\x`"" -Wait
$EspeakRoot = Get-ChildItem -Recurse -Path "$Tmp\x" -Filter "espeak-ng.dll" | Select-Object -First 1
if (-not $EspeakRoot) { throw "espeak-ng.dll not found in MSI extract" }
Copy-Item $EspeakRoot.FullName "$Out\espeak-ng.dll"
$Data = Get-ChildItem -Recurse -Path "$Tmp\x" -Directory -Filter "espeak-ng-data" | Select-Object -First 1
Copy-Item -Recurse $Data.FullName "$Out\espeak-ng-data"

Write-Host "== [4/4] official llama-server (win-vulkan-x64) =="
$Zip = Join-Path $Tmp "llama.zip"
Invoke-WebRequest -Uri "https://github.com/ggml-org/llama.cpp/releases/download/$LlamaTag/llama-$LlamaTag-bin-win-vulkan-x64.zip" -OutFile $Zip
Expand-Archive -Path $Zip -DestinationPath "$Tmp\llama" -Force
$Srv = Get-ChildItem -Recurse -Path "$Tmp\llama" -Filter "llama-server.exe" | Select-Object -First 1
Copy-Item "$($Srv.DirectoryName)\*.exe" $Out
Copy-Item "$($Srv.DirectoryName)\*.dll" $Out

& "$Out\roo-engine.exe" --phonemize "The quick brown fox."
Write-Host "OK: $Out"
