@echo off
setlocal

where bash >nul 2>nul
if %errorlevel%==0 (
    set "BASH_EXE=bash"
) else if exist "C:\Program Files\Git\bin\bash.exe" (
    set "BASH_EXE=C:\Program Files\Git\bin\bash.exe"
) else (
    echo Could not find bash.exe. Install Git for Windows, or run this from Git Bash with: bash scripts/dev.sh
    exit /b 1
)

"%BASH_EXE%" "%~dp0dev.sh" %*
