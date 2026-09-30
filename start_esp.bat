@echo off
title CSNO ESP - one click
setlocal

rem ---- Tool paths come from config.json next to this file (format: see
rem      config.example.json). No config.json -> fall back to PATH tools.
rem      config.json is local-only (gitignored), nothing is hardcoded here.
set "PYTHON=python"
set "ADB=adb"
set "LDCONSOLE=ldconsole"
set "PKG=com.ledi.csno"
set "PYTHONIOENCODING=utf-8"
set "CFG=%~dp0config.json"
if exist "%CFG%" (
    echo [cfg] loading config.json ...
    for /f "usebackq tokens=1,* delims==" %%a in (`powershell -NoProfile -Command "try{$d=(Get-Content -Raw -LiteralPath '%CFG%' -Encoding UTF8)|ConvertFrom-Json}catch{exit 1}; if($d.python){'PYTHON='+$d.python}; if($d.adb){'ADB='+$d.adb}; if($d.ldconsole){'LDCONSOLE='+$d.ldconsole}"`) do set "%%a=%%b"
)
echo       python:    %PYTHON%
echo       adb:       %ADB%
echo       ldconsole: %LDCONSOLE%
rem Console-independent ~3 s delay. timeout.exe cannot be used here: it
rem aborts immediately when stdin is redirected, which turns the wait
rem loops below into tight infinite loops.
set "WAIT=%SystemRoot%\System32\ping.exe -n 4 127.0.0.1 >nul"

echo [1/4] checking emulator ...
"%ADB%" get-state >nul 2>&1
if not errorlevel 1 goto emu_ok
echo        starting LDPlayer ...
"%LDCONSOLE%" launch --index 0
set "RETRY=0"
:wait_emu
%WAIT%
set /a RETRY+=1
if %RETRY% GTR 60 goto emu_timeout
"%ADB%" get-state >nul 2>&1
if errorlevel 1 goto wait_emu
:emu_ok
echo        emulator online

echo [2/4] waiting for android boot ...
set "RETRY=0"
:wait_boot
%WAIT%
set /a RETRY+=1
if %RETRY% GTR 60 goto boot_timeout
"%ADB%" shell getprop sys.boot_completed 2>nul | findstr "^1" >nul
if errorlevel 1 goto wait_boot
echo        boot complete

echo [3/4] checking game ...
set "GAMEPID="
for /f "delims=" %%i in ('%ADB% shell pidof %PKG% 2^>nul') do set "GAMEPID=%%i"
if defined GAMEPID goto game_ok
echo        starting game ...
"%ADB%" shell am start -n %PKG%/com.kisak.csgo.CsnoLauncher >nul 2>&1
set "RETRY=0"
:wait_game
%WAIT%
set /a RETRY+=1
if %RETRY% GTR 60 goto game_timeout
set "GAMEPID="
for /f "delims=" %%i in ('%ADB% shell pidof %PKG% 2^>nul') do set "GAMEPID=%%i"
if not defined GAMEPID goto wait_game
:game_ok
echo        game running

echo [4/4] starting ESP supervisor ...
echo        (frida-server and overlay are managed automatically)
"%PYTHON%" "%~dp0esp_auto.py"
echo.
echo supervisor exited.
pause
exit /b 0

:emu_timeout
echo        ERROR: emulator did not come online within ~3 min
pause
exit /b 1

:boot_timeout
echo        ERROR: android boot did not complete within ~3 min
pause
exit /b 1

:game_timeout
echo        ERROR: game process did not start within ~3 min
pause
exit /b 1
