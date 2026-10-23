@echo off
setlocal
cd /d "%~dp0"
title DualQuill

rem Use an available Python 3.11+ runtime; no package installation is needed.
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if not errorlevel 1 (
    py -3 -X utf8 run.py %*
    goto finished
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if not errorlevel 1 (
    python -X utf8 run.py %*
    goto finished
)
set "NOVEL_WRITER_RUNTIME=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%NOVEL_WRITER_RUNTIME%" (
    "%NOVEL_WRITER_RUNTIME%" -X utf8 run.py %*
    goto finished
)
echo Python 3.11 or newer is required. Please install Python and try again.
echo See docs/getting-started.md for instructions.
pause
exit /b 1

:finished
if errorlevel 1 pause
endlocal
