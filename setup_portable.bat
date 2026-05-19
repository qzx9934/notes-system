@echo off
chcp 65001 >nul 2>&1
title Setup Portable Python
echo ====================================================
echo   Portable Python Auto Setup
echo ====================================================
echo.

set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

REM ---- Check existing ----
if exist "%ROOT%\python\python.exe" (
    echo [OK] Portable Python already exists
    echo     Path: %ROOT%\python\python.exe
    pause
    exit /b 0
)

REM ---- Download embedded Python ----
set "PY_VER=3.10.11"
set "PY_FILE=python-%PY_VER%-embed-amd64.zip"
set "PY_URL=https://www.python.org/ftp/python/%PY_VER%/%PY_FILE%"
set "PY_ZIP=%ROOT%\%PY_FILE%"

echo [1/5] Downloading Python %PY_VER% embedded...
echo       URL: %PY_URL%
echo.

if exist "%PY_ZIP%" (
    echo [OK] Download file exists, skip
) else (
    echo       Downloading (~8MB)...
    curl -L -o "%PY_ZIP%" "%PY_URL%" 2>nul
    if not exist "%PY_ZIP%" (
        echo [!] curl failed, trying PowerShell...
        powershell -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%PY_ZIP%'" 2>nul
    )
    if not exist "%PY_ZIP%" (
        echo [X] Download failed, please download manually:
        echo     %PY_URL%
        echo     Save to: %ROOT%\
        pause
        exit /b 1
    )
)
echo [OK] Download complete

REM ---- Extract ----
echo.
echo [2/5] Extracting Python...
if exist "%ROOT%\python" rd /s /q "%ROOT%\python"
powershell -Command "Expand-Archive -Path '%PY_ZIP%' -DestinationPath '%ROOT%\python' -Force" 2>nul
if not exist "%ROOT%\python\python.exe" (
    echo [X] Extract failed
    pause
    exit /b 1
)
echo [OK] Extract complete

REM ---- Enable pip ----
echo.
echo [3/5] Configuring pip support...
powershell -Command "(Get-Content '%ROOT%\python\python310._pth') -replace '#import site', 'import site' | Set-Content '%ROOT%\python\python310._pth'"
echo [OK] site-packages enabled

REM ---- Install pip ----
echo.
echo [4/5] Installing pip...
set "GETPIP=%ROOT%\python\get-pip.py"
if not exist "%GETPIP%" (
    curl -L -o "%GETPIP%" https://bootstrap.pypa.io/get-pip.py 2>nul
    if not exist "%GETPIP%" (
        powershell -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile '%GETPIP%'" 2>nul
    )
)
if exist "%GETPIP%" (
    "%ROOT%\python\python.exe" "%GETPIP%" --no-warn-script-location 2>nul
    echo [OK] pip installed
) else (
    echo [!] pip install failed, will retry on first launch
)

REM ---- Install deps ----
echo.
echo [5/5] Installing project dependencies...
"%ROOT%\python\python.exe" -m pip install flask flask-cors openpyxl -q 2>nul
if %errorlevel% neq 0 (
    echo [!] Some deps failed, will retry on first launch
) else (
    echo [OK] Dependencies installed
)

REM ---- Cleanup ----
del "%PY_ZIP%" 2>nul

echo.
echo ====================================================
echo   Portable Python setup complete!
echo   Double-click startup.bat to run
echo ====================================================
echo.
pause
