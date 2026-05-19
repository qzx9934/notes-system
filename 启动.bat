@echo off
chcp 65001 >nul 2>&1
title WorkNotes System
echo ====================================================
echo   Power Plant Work Notes System
echo ====================================================
echo.

set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

echo [INFO] Work dir: %ROOT%
echo.

REM ---- Step 1: Find Python ----
set "PYTHON="

if exist "%ROOT%\python\python.exe" (
    set "PYTHON=%ROOT%\python\python.exe"
    echo [OK] Portable Python found
    goto :found_python
)

where python >nul 2>&1
if %errorlevel%==0 (
    for /f "delims=" %%i in ('where python') do (
        set "PYTHON=%%i"
        echo [OK] System Python: %%i
        goto :found_python
    )
)

echo [!] Python not found, setting up portable version...
echo.
call "%ROOT%\setup_portable.bat"
if exist "%ROOT%\python\python.exe" (
    set "PYTHON=%ROOT%\python\python.exe"
    goto :found_python
)
echo.
echo [X] Setup failed. Please install Python 3.10+
echo     https://www.python.org/downloads/
echo.
pause
exit /b 1

:found_python

echo [INFO] Python: %PYTHON%
"%PYTHON%" --version 2>nul
if %errorlevel% neq 0 (
    echo [X] Python cannot run, check installation
    pause
    exit /b 1
)
echo.

REM ---- Step 2: Install deps ----
echo [*] Checking dependencies...
"%PYTHON%" -c "import flask" 2>nul
if %errorlevel% neq 0 (
    echo [*] Installing flask flask-cors openpyxl ...
    "%PYTHON%" -m pip install flask flask-cors openpyxl
    if %errorlevel% neq 0 (
        echo [X] Install failed, check network
        pause
        exit /b 1
    )
    echo [OK] Dependencies installed
) else (
    echo [OK] Dependencies ready
)

REM ---- Step 3: Init DB ----
if not exist "%ROOT%\backend\notes.db" (
    echo [*] Initializing database...
    "%PYTHON%" "%ROOT%\backend\app.py" --init-only
    if %errorlevel% neq 0 (
        echo [X] DB init failed
        pause
        exit /b 1
    )
    echo [OK] Database initialized
)

REM ---- Step 4: Start server ----
echo.
echo [*] Starting server...
echo ====================================================
echo   URL: http://localhost:5000
echo   Press Ctrl+C to stop
echo ====================================================
echo.

"%PYTHON%" "%ROOT%\backend\app.py"

if %errorlevel% neq 0 (
    echo.
    echo [X] Server exited with error code: %errorlevel%
    pause
)
