@echo off
REM ====================================================================
REM  Register dashboard to auto-start at Windows logon (hidden window).
REM  Run this ONCE. After that the dashboard is always at localhost:8501
REM ====================================================================
schtasks /delete /tn "StockDashboard_AutoStart" /f 2>nul
schtasks /create /tn "StockDashboard_AutoStart" /tr "wscript.exe C:\Users\lg\Desktop\stock_screener\dashboard_hidden.vbs" /sc onlogon /rl HIGHEST /f

echo.
echo  Registered. The dashboard will start automatically every time you log in.
echo  It runs hidden in the background. Just open:  http://localhost:8501
echo.
echo  Starting it now too (so you do not have to reboot)...
wscript.exe "C:\Users\lg\Desktop\stock_screener\dashboard_hidden.vbs"
echo  Wait ~20 seconds, then open http://localhost:8501
pause
