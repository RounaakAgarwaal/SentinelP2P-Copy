@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows-stop.ps1" %*
exit /b %ERRORLEVEL%
