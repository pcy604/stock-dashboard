@echo off
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo [!] Python not found on PATH.
  echo     Install from https://www.python.org/downloads/  ^(check "Add Python to PATH"^)
  echo     then double-click this file again.
  pause
  exit /b 1
)

echo [1/2] Checking libraries ^(first run may take a few minutes^)...
python -m pip install --quiet streamlit plotly yfinance finance-datareader requests pandas

echo [2/2] Opening dashboard... your browser will open shortly.
echo       To stop, just close this window.
echo.
python -m streamlit run dashboard.py

pause
