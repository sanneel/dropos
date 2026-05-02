@echo off
setlocal

set SCRIPT_DIR=%~dp0
set BACKEND_DIR=%SCRIPT_DIR%backend
set FRONTEND=%SCRIPT_DIR%frontend\index.html
set PID_FILE=%SCRIPT_DIR%.backend.pid
set LOG_FILE=%SCRIPT_DIR%backend.log

echo.
echo   DropOS Backoffice
echo   -------------------------------

:: Find Python
set PY=
for %%P in (py python python3) do (
    if not defined PY (
        %%P -c "import sys; sys.exit(0 if sys.version_info>=(3,8) else 1)" >nul 2>&1
        if not errorlevel 1 set PY=%%P
    )
)

if not defined PY (
    echo [ERROR] Python 3.8+ not found. Install from python.org
    pause
    exit /b 1
)

for /f "tokens=*" %%V in ('%PY% --version 2^>^&1') do echo   Python: %%V

:: Kill old backend if running
if exist "%PID_FILE%" (
    set /p OLD_PID=<"%PID_FILE%"
    taskkill /PID %OLD_PID% /F >nul 2>&1
    del "%PID_FILE%"
)

:: Install dependencies if missing
echo   Checking dependencies...
cd /d "%BACKEND_DIR%"
%PY% -c "import fastapi,uvicorn,aiosqlite,httpx,apscheduler" >nul 2>&1
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
    %PY% -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/stats', timeout=2)" >nul 2>&1
    if not errorlevel 1 goto :ready
    set /a TRIES+=1
    if %TRIES% GEQ 20 goto :failed
    timeout /t 1 /nobreak >nul
    goto :wait_loop

:failed
echo [ERROR] Backend failed to start. Check backend.log for details:
type "%LOG_FILE%"
pause
exit /b 1

:ready
echo   DropOS is running!
echo   Dashboard: %FRONTEND%
echo   API:       http://localhost:8000
echo   Logs:      %LOG_FILE%
echo   Stop:      stop.bat
echo.

:: Open dashboard in default browser
start "" "%FRONTEND%"

:: Tail the log
echo Showing live log (Ctrl+C to stop tailing, backend keeps running):
powershell -Command "Get-Content '%LOG_FILE%' -Wait"
