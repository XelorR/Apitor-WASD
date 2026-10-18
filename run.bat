@echo off
rem Apitor remote - double-click launcher for Windows.
rem
rem The batch file does everything by itself:
rem   1) creates the .venv environment next to itself (if it is missing);
rem   2) installs the apitor-ble library from requirements.txt (if it is missing);
rem   3) runs apitor_remote.py and passes all arguments to it.
rem
rem Only Python 3.10+ has to be installed - nothing else.
rem Double-click run.bat (or make a shortcut to it) to play.
rem
rem Examples:
rem   run.bat                                the usual remote
rem   run.bat --tui                          full-screen interface
rem   run.bat --simulate                     no robot: print command frames
rem   run.bat --program examples\square.txt  a program at start
rem   run.bat --lang en                      English interface

setlocal
cd /d "%~dp0"

if not exist "apitor_remote.py" (
  echo [run] apitor_remote.py was not found next to run.bat.
  echo [run] Put run.bat into the folder of the remote.
  pause
  exit /b 1
)

rem --- Python: the py launcher first, then python from PATH ---------------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo [run] Python was not found. Install Python 3.10+ from python.org
  echo [run] and tick "Add python.exe to PATH" while installing.
  pause
  exit /b 1
)

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 (
  echo [run] Python 3.10 or newer is required, but the system has:
  %PY% -V
  pause
  exit /b 1
)

rem --- .venv next to this file --------------------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo [run] first run: creating the .venv environment...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo [run] could not create .venv.
    pause
    exit /b 1
  )
)

set "VPY=.venv\Scripts\python.exe"

"%VPY%" -m pip --version >nul 2>nul
if errorlevel 1 (
  echo [run] no pip inside .venv - rebuilding the environment...
  %PY% -m venv --clear .venv
)

rem --- the only dependency: apitor-ble ------------------------------------
"%VPY%" -c "import apitor_ble" >nul 2>nul
if errorlevel 1 (
  echo [run] installing the apitor-ble library ^(once, needs the internet^)...
  "%VPY%" -m pip install --quiet --disable-pip-version-check -r requirements.txt
  if errorlevel 1 (
    echo [run] could not install the dependencies: check the internet and try again.
    pause
    exit /b 1
  )
)

echo [run] starting the remote... ^(Ctrl+C quits^)
"%VPY%" apitor_remote.py %*
if errorlevel 1 pause
