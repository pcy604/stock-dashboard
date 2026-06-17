@echo off
chcp 65001 >nul
cd /d "%~dp0"
REM ====================================================================
REM  대시보드 열기 — 더블클릭하면 브라우저에서 대시보드가 자동으로 열립니다
REM  (끄려면 이 검은 창을 닫으세요)
REM ====================================================================
set PYTHON=C:\Users\lg\AppData\Local\Python\bin\python.exe
if not exist "%PYTHON%" set PYTHON=python

echo [1/2] 필요한 라이브러리 확인 (최초 1회만 느림)...
%PYTHON% -m pip install --quiet streamlit plotly yfinance finance-datareader requests pandas

echo [2/2] 대시보드를 엽니다... 잠시 후 브라우저가 자동으로 열립니다.
echo.
echo  ※ 데이터가 묵었으면 먼저 run_update.bat 을 돌려 갱신하세요.
echo  ※ 종료하려면 이 창을 닫으면 됩니다.
echo.
%PYTHON% -m streamlit run dashboard.py

pause
