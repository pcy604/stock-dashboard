"""주도주 결손 진단 (2026-10-19) — 9월엔 신호가 있었는데 지금 0회인 종목이 왜 빠졌나.
market.db(factor_weekly) 에서 종목별 이력 주수·재무 결측·가속 계산 가능 여부를 찍는다."""
import json, sqlite3, subprocess, sys, collections
import pandas as pd

SYMS = sys.argv[1:] or ['NVDA', 'PLTR', 'AXTI', 'MU', 'BE', 'MPWR', 'PLUG', 'ENPH', 'TSLA', 'AAPL']
c = sqlite3.connect('data/market.db')
q = lambda s, *a: c.execute(s, a).fetchall()
print('factor_weekly 전체:', q("SELECT COUNT(*), COUNT(DISTINCT sym), MIN(as_of), MAX(as_of) FROM factor_weekly WHERE factor_ver='v1'"))
u = pd.read_csv('data/leaders_cache/_universe.csv') if __import__('os').path.exists('data/leaders_cache/_universe.csv') else None
for s in SYMS:
    r = q("""SELECT COUNT(*), MIN(as_of), MAX(as_of), SUM(revenue IS NULL), SUM(op_income IS NULL),
                    SUM(period_end IS NULL), COUNT(DISTINCT period_end), SUM(marcap IS NULL), SUM(adv_20d IS NULL)
             FROM factor_weekly WHERE factor_ver='v1' AND sym=?""", s)[0]
    inu = (s in set(u.sym)) if u is not None else '?'
    pr = q("SELECT COUNT(*), MIN(date), MAX(date) FROM prices WHERE sym=?", s) if q("SELECT name FROM sqlite_master WHERE name='prices'") else '?'
    print(f"::notice title=diag {s}::주수 {r[0]} ({r[1]}~{r[2]}) · 매출결측 {r[3]} · 영업익결측 {r[4]} · "
          f"period_end결측 {r[5]} · 분기수 {r[6]} · 시총결측 {r[7]} · 거래대금결측 {r[8]} · 유니버스 {inu} · prices {pr}")
# 9월에 신호가 있었는데 지금 0회인 종목 전체를 원인별로 분류
old = json.loads(subprocess.check_output(['git', 'show', 'daca601:results/leaders_accel.json']))
new = json.load(open('results/leaders_accel.json'))
cut = max(old['weeks'])
oc = collections.Counter(r['sym'] for k, v in old['weeks'].items() for r in v)
nc = collections.Counter(r['sym'] for k, v in new['weeks'].items() if k <= cut for r in v)
lost = [s for s in oc if nc.get(s, 0) == 0]
cat = collections.Counter()
ex = collections.defaultdict(list)
for s in lost:
    r = q("SELECT COUNT(*), SUM(revenue IS NULL), COUNT(DISTINCT period_end) FROM factor_weekly WHERE factor_ver='v1' AND sym=?", s)[0]
    k = ('DB에 없음' if r[0] == 0 else '이력 52주 미만' if r[0] < 52 else
         '재무 전부 결측' if r[1] == r[0] else '분기 5개 미만' if (r[2] or 0) < 5 else '데이터는 있음(다른 원인)')
    cat[k] += 1
    if len(ex[k]) < 12:
        ex[k].append(s)
for k, n in cat.most_common():
    print(f"::warning title=사라진 {len(lost)}종 분류::{k} {n}종 — 예: {', '.join(ex[k])}")
