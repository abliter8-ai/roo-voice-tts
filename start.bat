@echo off
REM Roo Voice - one-command local server (Windows, NVIDIA GPU).
REM Sets up a venv, installs deps, downloads the INT8 model, opens the UI.
setlocal
cd /d "%~dp0"

echo.
echo   ###### ROO VOICE ######
echo.

where nvidia-smi >nul 2>&1
if errorlevel 1 (
  echo   No NVIDIA GPU detected. Roo Voice on Windows needs an NVIDIA CUDA GPU.
  echo   See recipes\nvidia-cuda.md
  exit /b 1
)

if "%ROO_MODEL%"=="" set "ROO_MODEL=abliter8-ai/Roo-Voice_MOSS_TTS_LT_int8"
if "%PORT%"=="" set "PORT=8080"

where python >nul 2>&1
if errorlevel 1 (
  echo   Python 3 not found. Install Python 3.10+ from python.org and re-run.
  exit /b 1
)

if not exist ".venv" (
  echo   Creating virtual environment (.venv) ...
  python -m venv .venv
)
call .venv\Scripts\activate.bat

echo   Installing dependencies (first run only) ...
python -m pip install -q -U pip
python -m pip install -q -r server\requirements-cuda.txt

echo.
echo   Starting Roo Voice on http://localhost:%PORT%/
echo   (first start also downloads the model - please wait)
echo.

start "" http://localhost:%PORT%/
python server\roo_serve.py --runtime transformers --model "%ROO_MODEL%" --reference reference.wav --port %PORT%

endlocal
