@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\platform-launcher.ps1" %*
set "launcherExitCode=%errorlevel%"
popd
if not "%~1"=="" exit /b %launcherExitCode%
if not "%launcherExitCode%"=="0" pause
exit /b %launcherExitCode%
