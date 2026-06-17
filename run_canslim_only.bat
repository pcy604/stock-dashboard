@echo off
cd /d "%~dp0"
echo ====================================================================
echo  CANSLIM only - diagnostic run
echo  Full KR universe + Naver scraping + pykrx. May take 10-30 minutes.
echo  Do NOT close this window until you see "DONE".
echo  If a red error appears, copy the LAST ~15 lines and send them.
echo ====================================================================
echo.
python -m pip install --quiet pykrx beautifulsoup4 finance-datareader requests pandas lxml
echo.
python canslim_run.py
echo.
echo ===================== DONE (or error above) ========================
pause
