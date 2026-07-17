@echo off
REM Roo Voice - one-command local server (Windows, NVIDIA GPU).
REM Sets up a venv, installs a CUDA PyTorch, downloads the INT4 model, warms it
REM up, and opens the UI.
setlocal
cd /d "%~dp0"

echo.
echo   ###### ROO VOICE ######   v1.1.0
echo.

where nvidia-smi >nul 2>&1
if errorlevel 1 (
  echo   No NVIDIA GPU detected. Roo Voice on Windows needs an NVIDIA CUDA GPU.
  echo   See recipes\nvidia-cuda.md
  exit /b 1
)

if "%ROO_MODEL%"=="" set "ROO_MODEL=abliter8-ai/Roo-Voice_MOSS_TTS_LT_int4"
if "%PORT%"=="" set "PORT=8080"
set "CUDA_INDEX=https://download.pytorch.org/whl/cu128"
set "LOGDIR=%~dp0logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo   Model: %ROO_MODEL%  (INT4 NF4 - default)

where python >nul 2>&1
if errorlevel 1 (
  echo   Python 3 not found. Install Python 3.12 from python.org and re-run.
  exit /b 1
)

if not exist ".venv" (
  echo   Creating virtual environment (.venv) ...
  python -m venv .venv
)
call .venv\Scripts\activate.bat

python -m pip install -q -U pip

REM ==========================================================================
REM  IP-176 RC2 - THE Windows bug.
REM  PyPI's win_amd64 torch wheel is ~122 MB and CPU-ONLY. Installing it made
REM  the app load, report healthy, open the UI, and never generate speech
REM  (it was silently running on CPU). The CUDA build (~2.5 GB) lives only on
REM  the PyTorch index. Install it explicitly, then PROVE CUDA is real.
REM ==========================================================================
echo   Installing PyTorch with CUDA (~2.5 GB, first run only) ...
python -m pip install -q torch torchaudio --index-url %CUDA_INDEX%
if errorlevel 1 (
  echo   Failed to install the CUDA PyTorch. See %LOGDIR%
  exit /b 1
)

echo   Installing dependencies (first run only) ...
python -m pip install -q -r server\requirements-cuda.txt
if errorlevel 1 (
  echo   Failed to install dependencies.
  exit /b 1
)

python -c "import torch,sys; sys.exit(0 if torch.version.cuda else 1)"
if errorlevel 1 (
  echo.
  echo   X A CPU-only PyTorch is installed - Roo Voice needs the CUDA build.
  echo     Fix:
  echo       pip install --force-reinstall torch torchaudio --index-url %CUDA_INDEX%
  echo.
  exit /b 1
)

python -c "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)"
if errorlevel 1 (
  echo.
  echo   X PyTorch has CUDA support but cannot see your GPU.
  echo     Check your NVIDIA driver and that nvidia-smi works, then re-run.
  echo.
  exit /b 1
)

echo.
echo   Starting Roo Voice on http://localhost:%PORT%/
echo   First start downloads the model, then WARMS IT UP (compiles CUDA kernels
echo   once). The browser opens when it is genuinely ready. Logs: %LOGDIR%
echo.

REM Open the browser only once /healthz reports ready:true (not merely listening).
start "" powershell -NoProfile -WindowStyle Hidden -Command ^
  "for($i=0;$i -lt 800;$i++){try{$r=Invoke-WebRequest -UseBasicParsing http://localhost:%PORT%/healthz -TimeoutSec 2; if(($r.Content ^| ConvertFrom-Json).ready){Start-Process 'http://localhost:%PORT%/'; break}}catch{}; Start-Sleep 3}"

python server\roo_serve.py --runtime transformers --model "%ROO_MODEL%" --reference reference.wav --port %PORT% --log-dir "%LOGDIR%"

endlocal
