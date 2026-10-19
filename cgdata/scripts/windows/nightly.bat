@echo off
rem Nightly cgdata render, 10pm-7am. Registered by register_nightly.ps1.
rem Edit the paths below once; everything else lives in run_batch.
setlocal
set REPO=C:\path\to\dughogan
set LIBRARY=D:\cgdata\LIBRARY
set BLENDER=C:\Program Files\Blender Foundation\Blender 5.2\blender.exe
set NUKE=C:\Program Files\Nuke16.0vX\Nuke16.0.exe
set COMFYAUDIT_PATH=C:\ai\ComfyUI\custom_nodes
rem Studio signing key and ledger for witnessed provenance (keep the key file private):
rem set COMFYAUDIT_HISTORY_KEY_FILE=D:\cgdata\keys\studio.key
rem set COMFYAUDIT_HISTORY_LEDGER=D:\cgdata\LIBRARY\provenance\ledger.jsonl
set COUNT=500
set SEED=1

cd /d "%REPO%" || exit /b 1
call .venv\Scripts\activate.bat || exit /b 1
if not exist "%LIBRARY%" mkdir "%LIBRARY%"
echo ==== %DATE% %TIME% start >> "%LIBRARY%\batch.log"
python -m cgdata.run_batch --count %COUNT% --seed %SEED% --quality pilot --style-pairs ^
  --library "%LIBRARY%" --blender "%BLENDER%" --nuke "%NUKE%" --stop-at 07:00 >> "%LIBRARY%\batch.log" 2>&1
echo ==== %DATE% %TIME% end (exit %ERRORLEVEL%) >> "%LIBRARY%\batch.log"
endlocal
