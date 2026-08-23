@echo off
set PID_FILE=%~dp0.backend.pid
set STOPPED=0
if exist "%PID_FILE%" (
    set /p PID=<"%PID_FILE%"
    taskkill /PID %PID% /F >nul 2>&1 && set STOPPED=1
    del "%PID_FILE%"
)
:: Fallback: whatever is still listening on :8000
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    taskkill /PID %%P /F >nul 2>&1 && set STOPPED=1
)
if "%STOPPED%"=="1" (echo Backend stopped.) else (echo No running backend found.)
