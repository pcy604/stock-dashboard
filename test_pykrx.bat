@echo off
cd /d "%~dp0"
echo Testing pykrx trading-value-by-date for Samsung (005930)...
echo.
python -c "from pykrx import stock; df=stock.get_market_trading_value_by_date('20260501','20260613','005930'); print('COLUMNS:', list(df.columns)); print('SHAPE:', df.shape); print(df.tail(3))"
echo.
echo ----- if an error appeared above, that is the clue -----
pause
