@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start_anima_v3.ps1"
set "ANIMA_EXIT=%ERRORLEVEL%"
if not "%ANIMA_EXIT%"=="0" pause
exit /b %ANIMA_EXIT%
