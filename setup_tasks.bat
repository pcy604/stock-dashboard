@echo off
chcp 65001 >nul
rem 노트북 예약 작업 두 개(주문 봇·토스 동기화)를 한 번에 다시 등록 — 마우스 오른쪽 → '관리자 권한으로 실행'
rem 멈춰 있는 기존 실행을 먼저 끝낸다.
powershell -NoProfile -Command "Stop-ScheduledTask -TaskName StockScreener_Daily -ErrorAction SilentlyContinue; Stop-ScheduledTask -TaskName buza_live_bot -ErrorAction SilentlyContinue"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_tasks.ps1"
pause
