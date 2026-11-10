@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows-start.ps1" %*
exit /b %ERRORLEVEL%
