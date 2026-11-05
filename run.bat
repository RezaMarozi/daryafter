@echo off
setlocal EnableExtensions
cd /d "%~dp0"
rem ===========================================================================
rem  Daryafter launcher.
rem  First run : creates a private Python environment (.venv) and installs the
rem              libraries from the Libs folder (no internet needed). If Libs
rem              has no libraries, it downloads them from the internet instead.
rem  Next runs : starts the program at once.
rem  Extra arguments are passed on, for example:  run.bat --private
rem ===========================================================================

rem Already set up? Start straight away. The marker file is only written after a
rem fully successful setup, so a half-finished setup is repeated, not skipped.
if exist ".venv\.daryafter-ready" goto start

rem ---- first run: find Python 3.12 or newer ---------------------------------
set "PY="
for %%V in (3.12 3.13 3.14) do if not defined PY (
    py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
)
if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo Python 3.12 or newer was not found on this computer.
    echo Install Python 3.12.10 from python.org and tick "Add python.exe to PATH"
    echo in the installer, then run this file again.
    pause
    exit /b 1
)

echo Setting up Daryafter for the first time. This happens only once.
if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv || goto fail
)

rem ---- install the libraries -------------------------------------------------
set "HAVE_LIBS="
if exist "Libs\*.whl" set "HAVE_LIBS=1"

if defined HAVE_LIBS (
    echo Installing the libraries from the Libs folder...
    ".venv\Scripts\python.exe" -m pip install --no-index --find-links "Libs" -r requirements.txt --disable-pip-version-check
    if not errorlevel 1 goto ready
    echo.
    echo Installing from the Libs folder failed. Trying the internet instead...
) else (
    echo The Libs folder has no libraries. Downloading them from the internet...
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 goto fail

:ready
echo ready> ".venv\.daryafter-ready"

:start
start "" ".venv\Scripts\pythonw.exe" -m daryafter %*
exit /b 0

:fail
echo.
echo Setup failed. Nothing was started. Common reasons:
echo  - the Libs folder was not downloaded for this Python version
echo  - there is no internet and the Libs folder is empty
echo The half-made .venv folder is removed so the next run starts clean.
rmdir /s /q ".venv" >nul 2>&1
pause
exit /b 1
