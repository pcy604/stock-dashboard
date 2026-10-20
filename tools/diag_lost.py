"""9월(daca601)엔 신호가 있었는데 지금 0회인 종목 — 왜 빠졌나 종목별로 (2026-10-20).

10-19 진단 때 62종 → universe_ever·fixcap·복수종류주식 폴백 후 27종이 남았다(결과 파일 대조).
여기서는 그 종목들의 '옛 신호 주차'에서 지금 DB 값이 게이트의 어느 칸에서 떨어지는지 찍는다.
읽기 전용. 결과는 ::notice 주석 + results/diag_lost.json(커밋은 워크플로가 결정)."""
import json, os, sqlite3, subprocess, sys, collections
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import leaders_accel as A

old = json.loads(subprocess.check_output(['git', 'show', 'daca601:results/leaders_accel.json']))
new = json.load(open('results/leaders_accel.json'))
cut = max(old['weeks'])
ow = collections.defaultdict(list)
for k, v in old['weeks'].items():
    for r in v:
        ow[r['sym']].append(k)
nc = collections.Counter(r['sym'] for k, v in new['weeks'].items() if k <= cut for r in v)
lost = sorted(s for s in ow if nc.get(s, 0) == 0)
print(f"9월 신호 {len(ow)}종 · 지금 {len(nc)}종 · 사라짐 {len(lost)}종: {' '.join(lost)}")

d = A.load()
d = d[d.sym.isin(lost)]
mc = pd.read_csv('data/us_marketcap.csv').set_index('Symbol')['marketcap'] if os.path.exists('data/us_marketcap.csv') else pd.Series(dtype=float)
ever = set(pd.read_csv('data/universe_ever.csv').sym) if os.path.exists('data/universe_ever.csv') else set()
out, cat = {}, collections.Counter()
for s in lost:
    x = d[d.sym == s].set_index('as_of')
    wks = pd.to_datetime(ow[s])
    rec = dict(old_weeks=ow[s], fw_rows=int(len(x)), in_marketcap=bool(s in mc.index),
               mcap_now=(float(mc[s]) if s in mc.index else None), in_universe_ever=s in ever)
    rec['fq_file'] = os.path.exists(f'data/leaders_cache/fq_{s}.csv')
    rec['dy_file'] = os.path.exists(f'data/leaders_cache/dy_{s}.csv')
    try:
        import price_store
        _w = price_store.get(s, 'US')
        rec['prices_wk'] = 0 if _w is None else int(len(_w))
    except Exception as _e:
        rec['prices_wk'] = f'err {str(_e)[:40]}'
    if len(x):
        _y = x.reindex(pd.to_datetime(ow[s]))
        rec['marcap_at_old_B'] = [None if v != v else round(float(v) / 1e9, 3) for v in _y.marcap.tolist()][:6]
        rec['close_at_old'] = [None if v != v else round(float(v), 2) for v in _y.close.tolist()][:6]
    if not len(x):
        k = ('DB 없음 · 재무파일(fq_) 없음' if not rec['fq_file'] else
             'DB 없음 · 주봉 80주 미만' if not rec['prices_wk'] or (isinstance(rec['prices_wk'], int) and rec['prices_wk'] < 80) else
             'DB 없음 · 재무·주봉 있음(적재 누락)')
    else:
        y = x.reindex(wks)
        rec.update(rows_at_old_weeks=int(y.close.notna().sum()),
                   marcap_null=int(y.marcap.isna().sum()), adv_null=int(y.adv_20d.isna().sum()),
                   acc1=int((y.ACC == 1).sum()), adv_ok=int((y.adv_20d >= A.MIN_ADV).sum()),
                   mc_ok=int((y.marcap >= A.MIN_MC).sum()), surge_ok=int((y.ret_1w >= A.SURGE).sum()),
                   last_as_of=str(x.index.max().date()))
        if rec['rows_at_old_weeks'] == 0:
            k = '옛 신호 주차의 행이 없음(이력 결손)'
        elif rec['marcap_null'] == rec['rows_at_old_weeks']:
            k = '시총 NULL'
        elif rec['acc1'] == 0:
            k = '이익가속 재계산 결과 불충족(재무 개정)'
        elif rec['mc_ok'] == 0:
            k = '시총 하한 미달'
        elif rec['adv_ok'] == 0:
            k = '거래대금 하한 미달'
        elif rec['surge_ok'] == 0:
            k = '주간 수익률 조건 미달(가격 개정)'
        else:
            k = '조건은 통과 — 산출 단계 확인 필요'
    rec['reason'] = k
    cat[k] += 1
    out[s] = rec
    print(f"::notice title=사라진 {s}::{k} · " + json.dumps({kk: vv for kk, vv in rec.items() if kk != 'old_weeks'},
                                                          ensure_ascii=False)[:900])
for k, n in cat.most_common():
    print(f"::warning title=사라진 {len(lost)}종 분류::{k} {n}종 — {' '.join(s for s in lost if out[s]['reason'] == k)}")
json.dump(dict(cut=cut, lost=len(lost), by_reason=dict(cat), detail=out),
          open('results/diag_lost.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
