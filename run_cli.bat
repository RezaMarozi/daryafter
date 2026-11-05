@echo off
setlocal EnableExtensions
cd /d "%~dp0"
rem ===========================================================================
rem  Daryafter command-line downloader (no window).
rem  Usage:  run_cli.bat "https://example.com/file.zip" -o D:\Downloads
rem
rem  First run : installs only the libraries the command-line tool needs, from
rem              the Libs folder (no internet), or from the internet if Libs is
rem              empty. It uses the same .venv folder as run.bat.
rem  Next runs : starts at once.
rem ===========================================================================

rem Set up already (by this file or by run.bat)? Run at once.
if exist ".venv\.daryafter-ready" goto run
if exist ".venv\.daryafter-cli-ready" goto run

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
    exit /b 1
)

echo Setting up the Daryafter command-line tool. This happens only once.
if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv || goto fail
)

set "HAVE_LIBS="
if exist "Libs\*.whl" set "HAVE_LIBS=1"

if defined HAVE_LIBS (
    echo Installing the libraries from the Libs folder...
    ".venv\Scripts\python.exe" -m pip install --no-index --find-links "Libs" "httpx[http2,socks]>=0.27" "truststore>=0.9" --disable-pip-version-check
    if not errorlevel 1 goto ready
    echo.
    echo Installing from the Libs folder failed. Trying the internet instead...
) else (
    echo The Libs folder has no libraries. Downloading them from the internet...
)
".venv\Scripts\python.exe" -m pip install "httpx[http2,socks]>=0.27" "truststore>=0.9" --disable-pip-version-check
if errorlevel 1 goto fail

:ready
echo ready> ".venv\.daryafter-cli-ready"

:run
".venv\Scripts\python.exe" -m daryafter.cli %*
exit /b %errorlevel%

:fail
echo.
echo Setup failed. Common reasons:
echo  - the Libs folder was not downloaded for this Python version
echo  - there is no internet and the Libs folder is empty
echo The half-made .venv folder is removed so the next run starts clean.
rmdir /s /q ".venv" >nul 2>&1
exit /b 1
