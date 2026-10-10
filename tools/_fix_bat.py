# -*- coding: utf-8 -*-
"""run_leaders_weekly.bat 의 원격 검증 줄을 안전하게 다시 쓴다 (일회성)."""
import io

P = r"C:\Users\lg\Desktop\stock_screener\run_leaders_weekly.bat"
GOOD = (
    r'"%DIR%\..\..\AppData\Local\Python\bin\python.exe" -c "'
    r"import subprocess,sys,json,os;"
    r"d=os.environ['DIR'];"
    r"r=subprocess.run(['git','show','origin/main:results/leaders_accel.json'],"
    r"capture_output=True,cwd=d);"
    r"w=json.loads(r.stdout.decode('utf-8'))['signal_week'] if r.returncode==0 else '?';"
    r"l=json.load(open(os.path.join(d,'results','leaders_accel.json'),encoding='utf-8'))['signal_week'];"
    r"print('[OK] 원격 반영 확인 - 주차 '+w) if w==l else "
    r"(print('[WARN] 원격이 아직 옛 주차: 원격 '+str(w)+' vs 로컬 '+str(l)) or sys.exit(4))"
    r'"'
)

lines = io.open(P, encoding="utf-8", errors="replace").read().split("\n")
out, done = [], False
for ln in lines:
    if "leaders_accel.json" in ln and "python.exe" in ln and "원격 반영" in ln:
        out.append(GOOD)
        done = True
    else:
        out.append(ln)
assert done, "대상 줄을 못 찾았다"
io.open(P, "w", encoding="utf-8").write("\n".join(out))

chk = io.open(P, encoding="utf-8").read().split("\n")
for i, ln in enumerate(chk, 1):
    if "leaders_accel.json" in ln and "python.exe" in ln:
        print("행", i)
        print("  Python 경로 OK:", r"AppData\Local\Python\bin\python.exe" in ln)
        print("  os.environ['DIR'] 사용:", "os.environ['DIR']" in ln)
        print("  제어문자 없음:", not any(c in ln for c in "\r\b\x0c\x07"))
