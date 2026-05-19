@echo off
chcp 65001 >nul 2>&1
title Stop Server
echo Stopping Work Notes server...
taskkill /f /fi "WINDOWTITLE eq WorkNotes System" >nul 2>&1
for /f "tokens=2" %%a in ('tasklist /fi "imagename eq python.exe" /fo list ^| find "PID"') do (
    wmic process where "ProcessId=%%a" get CommandLine 2>nul | find "app.py" >nul && taskkill /f /pid %%a >nul 2>&1
)
echo Server stopped.
timeout /t 2 /nobreak >nul
