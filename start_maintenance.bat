@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Python environment was not found: .venv\Scripts\python.exe
    echo.
    pause
    exit /b 1
)

echo Starting the maintenance server...
echo The browser will open automatically.
echo Press Ctrl+C to stop the server.
echo.

".venv\Scripts\python.exe" "src\maintenance_server.py"

if errorlevel 1 (
    echo.
    echo The maintenance server stopped with an error.
    pause
)
