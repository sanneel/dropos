@echo off
setlocal EnableDelayedExpansion

set SCRIPT_DIR=%~dp0
set BACKEND_DIR=%SCRIPT_DIR%backend
set PID_FILE=%SCRIPT_DIR%.backend.pid
set LOG_FILE=%SCRIPT_DIR%backend.log
set URL=http://localhost:8000

echo.
echo   DropOS Backoffice
echo   -------------------------------

:: Find Python
set PY=
for %%P in (py python python3) do (
    if not defined PY (
        %%P -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
        if not errorlevel 1 set PY=%%P
    )
)

if not defined PY (
    echo [ERROR] Python 3.10+ not found. Install from python.org
    pause
    exit /b 1
)

for /f "tokens=*" %%V in ('%PY% --version 2^>^&1') do echo   Python: %%V

:: Load .env (KEY=VALUE lines; '#' comments skipped). Values are not expanded.
if exist "%SCRIPT_DIR%.env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%SCRIPT_DIR%.env") do (
        if not "%%A"=="" set "%%A=%%B"
    )
    echo   Loaded .env
) else (
    echo   [WARN] No .env found - copy .env.example to .env first
)

if not defined DATABASE_URL (
    echo [ERROR] DATABASE_URL is not set. Add it to .env
    pause
    exit /b 1
)

:: Kill old backend if running
if exist "%PID_FILE%" (
    set /p OLD_PID=<"%PID_FILE%"
    taskkill /PID !OLD_PID! /F >nul 2>&1
    del "%PID_FILE%"
)

:: Install dependencies if missing
echo   Checking dependencies...
cd /d "%BACKEND_DIR%"
%PY% -c "import fastapi,uvicorn,asyncpg,httpx,apscheduler,bcrypt,jwt,slowapi" >nul 2>&1
if errorlevel 1 (
    echo   Installing dependencies...
    %PY% -m pip install -r requirements.txt -q
)

:: Start backend
echo   Starting backend on port 8000...
start /B "" %PY% -m uvicorn main:app --host 0.0.0.0 --port 8000 > "%LOG_FILE%" 2>&1
timeout /t 1 /nobreak >nul

:: Save PID (uvicorn launched by start /B)
for /f "tokens=2" %%P in ('tasklist /fi "IMAGENAME eq python.exe" /fo LIST ^| findstr "PID"') do (
    echo %%P > "%PID_FILE%"
    goto :pid_saved
)
for /f "tokens=2" %%P in ('tasklist /fi "IMAGENAME eq py.exe" /fo LIST ^| findstr "PID"') do (
    echo %%P > "%PID_FILE%"
    goto :pid_saved
)
:pid_saved

:: Wait for backend to be ready
echo   Waiting for backend...
set /a TRIES=0
:wait_loop
    %PY% -c "import urllib.request; urllib.request.urlopen('%URL%/health', timeout=2)" >nul 2>&1
    if not errorlevel 1 goto :ready
    set /a TRIES+=1
    if %TRIES% GEQ 30 goto :failed
    timeout /t 1 /nobreak >nul
    goto :wait_loop

:failed
echo [ERROR] Backend failed to start. Check backend.log for details:
type "%LOG_FILE%"
pause
exit /b 1

:ready
echo.
echo   DropOS is running!
echo   Dashboard: %URL%
echo   Logs:      %LOG_FILE%
echo   Stop:      stop.bat
echo.
start "" "%URL%"
endlocal
