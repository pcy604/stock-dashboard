import sys
import subprocess
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import os
script_dir = os.path.dirname(os.path.abspath(__file__))
python = sys.executable

tasks = [
    {
        'name': 'StockScreener_Weekly',
        'script': os.path.join(script_dir, 'weekly_run.py'),
        'schedule': 'WEEKLY',
        'day': 'SAT',
        'time': '08:00',
        'desc': '주봉 분석 (매주 토요일 08:00)',
    },
    {
        'name': 'StockScreener_Monthly',
        'script': os.path.join(script_dir, 'monthly_run.py'),
        'schedule': 'MONTHLY',
        'day': '1',
        'time': '08:00',
        'desc': '월봉 분석 (매월 1일 08:00)',
    },
]

print()
print('═══════════════════════════════════════')
print('  자동 실행 스케줄러 등록')
print('═══════════════════════════════════════')
print()

for t in tasks:
    if t['schedule'] == 'WEEKLY':
        cmd = (
            f'schtasks /create /tn "{t["name"]}" '
            f'/tr "{python} {t["script"]}" '
            f'/sc WEEKLY /d {t["day"]} /st {t["time"]} '
            f'/ru "{os.environ.get("USERNAME", "")}" /f'
        )
    else:
        cmd = (
            f'schtasks /create /tn "{t["name"]}" '
            f'/tr "{python} {t["script"]}" '
            f'/sc MONTHLY /d {t["day"]} /st {t["time"]} '
            f'/ru "{os.environ.get("USERNAME", "")}" /f'
        )

    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        print(f'  [OK] {t["desc"]}')
    else:
        print(f'  [실패] {t["name"]}: {result.stderr.strip()}')

print()
print('  등록된 스케줄:')
print('  - 주봉 리포트: 매주 토요일 08:00')
print('  - 월봉 리포트: 매월 1일 08:00')
print()
print('  ※ PC가 켜져 있어야 자동 실행됩니다.')
print('  ※ 변경: 작업 스케줄러 앱 → StockScreener_ 검색')
print()
