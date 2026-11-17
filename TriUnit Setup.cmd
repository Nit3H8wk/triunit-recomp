@echo off
rem TriUnit Recomp: opens the launcher (triunit.exe), building it first when it is missing or older than its sources.
rem The games are prepared inside the launcher from your own ROM files. Nothing is downloaded.
setlocal
cd /d "%~dp0"
title TriUnit Recomp Setup

set "PY="
python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY goto no_python

%PY% tools\launcher\build.py --if-stale
if not errorlevel 1 goto open
if not exist triunit.exe goto no_build
echo The launcher could not be rebuilt; opening the existing triunit.exe.
goto open

:no_python
if exist triunit.exe goto open
echo Python 3 was not found.
echo Install Python 3 for Windows and run this file again. See README.md, section Requirements.
pause
exit /b 1

:no_build
echo The launcher could not be built. It needs MSYS2 MinGW-w64 g++ 16.1.0 at C:\msys64\mingw64\bin\g++.exe.
echo See README.md, section Requirements.
pause
exit /b 1

:open
start "" "%~dp0triunit.exe"
exit /b 0
