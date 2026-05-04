@echo off
set PID_FILE=%~dp0.backend.pid
if exist "%PID_FILE%" (
    set /p PID=<"%PID_FILE%"
    taskkill /PID %PID% /F >nul 2>&1
    del "%PID_FILE%"
    echo Backend stopped.
) else (
    echo No running backend found.
)
