@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ── 페이퍼 트레이딩 주간 갱신 ──
python paper_trade.py log
python paper_trade.py update
python paper_trade.py weights
python paper_trade.py report
echo.
echo 완료. 대시보드 "📒 페이퍼 트레이딩" 탭에서 확인하세요.
pause
