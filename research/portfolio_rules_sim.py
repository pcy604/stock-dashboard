# -*- coding: utf-8 -*-
"""매매 원칙 검증용 포트폴리오 시뮬레이터 (2026-10-13, Claude 연구)
leaders_port_bt.run(6c0461c 에서 삭제됨)을 복원·확장했다. 결과: portfolio_rules_2026-10-13.csv
주봉 종가 체결 · 고점 대비 손절 · 진입 1주 지연 · 편도 비용 COST · 현금 이자 FEDFUNDS
추가 인자: take(최소보유/신고가 미갱신 익절) · pyr(불타기) · cap/trim · brake · order(동시신호 우선순위)
          · init_frac(분할진입) · shock(상장폐지 충격)
⚠️ 동시 신호 순서가 결과를 크게 바꾼다(알파벳 순 9.2% ↔ 시총 오름차순 13.2%, 같은 설정).
   비교는 order='random' 여러 시드의 중앙값으로 한다.
사용: FACTOR_VER=v13y python research/portfolio_rules_sim.py  (market.db 로드에 1~2분)"""
import numpy as np, pandas as pd, os, sys, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('FACTOR_VER', 'v13y')
import leaders_accel as A

COST = 0.003   # 편도(기존 연구와 같은 관례: 매수·매도 각각 0.3%)

def load():
    d = A.load()
    M = A.matrices(d, ["close", "marcap", "adv_20d", "ret_1w", "ACC"])
    px = M["close"]; g = A.gate_of(M)
    s = pd.read_csv(os.path.join(ROOT, 'data/leaders_cache/dy_SPY.csv'), index_col=0, parse_dates=True).Close
    w = s.resample('W-FRI').last(); w.index = w.index - pd.Timedelta(days=4)
    spy = w.reindex(px.index).ffill()
    m = pd.read_parquet(os.path.join(ROOT, 'data/macro_hist.parquet'))
    ff = m['FEDFUNDS'].reindex(px.index.union(m.index)).ffill().reindex(px.index).bfill()
    cash_r = (1 + ff / 100) ** (1 / 52) - 1          # 주간 현금 이자
    mcap = M["marcap"].values
    return px, g, spy, cash_r, mcap

def run(px, g, *, slots=20, stop=20, stop_min=0, take=None, pyr=None, cap=None,
        trim=None, replace=False, brake=None, delay=1, shock=0.0, seed=0, cash_r=None,
        pyr_first=True, order='alpha', mc=None, init_frac=1.0, red=None, red_exit=None, ratchet=None, lock=None, tstop=None):
    """
    stop      고점 대비 % (None=없음). stop_min 주 이전엔 미적용
    take      (min_wk, dry_wk): min_wk 보유 후, 진입 후 최고가를 dry_wk 주 못 넘으면 전량 매도
    pyr       dict(step=25, add=1.0, max_adds=2): 진입가 대비 +step%마다(신고가 갱신 주에만)
              최초 매수금액 × add 만큼 추가. cap% 를 넘기지 않는다
    cap       종목당 최대 비중 % (추가매수 상한)
    trim      종목 비중이 trim% 를 넘으면 cap(없으면 trim) 까지 덜어낸다
    replace   만석일 때 손실 중 최악 종목을 팔고 신규 진입
    brake     (dd%, mult): 계좌가 고점 대비 dd% 이상 빠져 있으면 신규·추가 매수 금액 × mult
    """
    rng = np.random.default_rng(seed)
    G = g.shift(delay).astype('boolean').fillna(False).astype(bool) if delay else g
    P = px.values; idx = px.index; cols = px.columns
    Gv = G.values
    cash = 1.0; pos = {}; hist = []; peak_eq = 1.0; trades = []; nadd = 0; ntrim = 0
    def price(j, i):
        v = P[i, j]
        if v == v and v > 0:
            pos[j]['last'] = v; return v
        return pos[j]['last']
    for i in range(len(idx)):
        if cash_r is not None and cash > 0:
            cash *= 1 + cash_r.iloc[i]
        if shock > 0:
            for j in list(pos):
                if rng.random() < shock:
                    trades.append((pos[j]['inv'], 0.0)); del pos[j]
        # 1) 청산
        for j in list(pos):
            e = pos[j]; c = price(j, i); e['wk'] += 1
            if c > e['peak']:
                e['peak'] = c; e['pk_wk'] = e['wk']
            ddp = (c / e['peak'] - 1) * 100
            out = False
            if stop is not None and e['wk'] > stop_min and ddp <= -stop: out = True
            if take and e['wk'] >= take[0] and (e['wk'] - e['pk_wk']) >= take[1]: out = True
            pg = (e['peak'] / e['entry'] - 1) * 100
            if red_exit is not None and red is not None and e['wk'] >= red_exit.get('min_wk', 1) \
               and pg >= red_exit.get('after_gain', -1e9) and red[i, j]:
                out = True
            if ratchet:
                w_ = None
                for thr, wd in ratchet:
                    if pg >= thr: w_ = wd
                if w_ is not None and ddp <= -w_: out = True
            if lock and pg >= lock[0]:
                floor = e['entry'] * (1 + lock[1] * pg / 100)
                if c <= floor: out = True
            if tstop and e['wk'] == tstop[0] and (c / e['entry'] - 1) * 100 < tstop[1]: out = True
            if out:
                v = e['sh'] * c * (1 - COST); cash += v; trades.append((e['inv'], v)); del pos[j]
        eq = cash + sum(pos[j]['sh'] * price(j, i) for j in pos)
        peak_eq = max(peak_eq, eq)
        mult = 1.0
        if brake and (eq / peak_eq - 1) * 100 <= -brake[0]: mult = brake[1]
        # 2) 비중 덜기
        if trim:
            tgt = (cap or trim) / 100
            for j in list(pos):
                c = price(j, i); val = pos[j]['sh'] * c
                if val / eq > trim / 100:
                    sell = val - tgt * eq
                    pos[j]['sh'] -= sell / c; cash += sell * (1 - COST); pos[j]['inv'] -= 0; ntrim += 1
                    trades.append((0.0, sell * (1 - COST)))
        def do_pyr():
            nonlocal cash, nadd
            if not pyr: return
            for j in list(pos):
                e = pos[j]; c = price(j, i)
                if e['adds'] >= pyr['max_adds'] or e['pk_wk'] != e['wk']: continue   # 신고가 주에만
                if (c / e['entry'] - 1) * 100 < pyr['step'] * (e['adds'] + 1): continue
                amt = e['base'] * pyr['add'] * mult
                if cap: amt = min(amt, cap / 100 * eq - e['sh'] * c)
                amt = min(amt, cash)
                if amt <= eq * 0.001: continue
                e['sh'] += amt / c * (1 - COST); cash -= amt; e['adds'] += 1; e['inv'] += amt; nadd += 1
        if pyr_first: do_pyr()
        # 3) 신규 진입
        hit = np.where(Gv[i])[0]
        if order == 'random': hit = rng.permutation(hit)
        elif order == 'mc_asc' and mc is not None: hit = hit[np.argsort(mc[i, hit])]
        elif order == 'mc_desc' and mc is not None: hit = hit[np.argsort(-mc[i, hit])]
        for j in hit:
            if j in pos: continue
            c = P[i, j]
            if not (c == c and c > 0): continue
            if len(pos) >= slots:
                if not replace: break
                worst = min(pos, key=lambda k: price(k, i) / pos[k]['entry'])
                wc = price(worst, i)
                if wc / pos[worst]['entry'] >= 1: break
                v = pos[worst]['sh'] * wc * (1 - COST); cash += v; trades.append((pos[worst]['inv'], v)); del pos[worst]
            amt = min(eq / slots * mult * init_frac, cash)
            if amt <= eq * 0.001: break
            pos[j] = dict(sh=amt / c * (1 - COST), entry=c, peak=c, wk=0, pk_wk=0, last=c, adds=0, base=amt, inv=amt)
            cash -= amt
        if not pyr_first: do_pyr()
        eq = cash + sum(pos[j]['sh'] * price(j, i) for j in pos)
        mx = max([pos[j]['sh'] * price(j, i) / eq for j in pos], default=0)
        hist.append((idx[i], eq, len(pos), cash / eq, mx))
    h = pd.DataFrame(hist, columns=['t', 'v', 'n', 'cash', 'mx']).set_index('t')
    return h, dict(trades=len(trades), adds=nadd, trims=ntrim)

def stats(v, bench=None):
    v = v.dropna(); yrs = (v.index[-1] - v.index[0]).days / 365.25
    cagr = (v.iloc[-1] / v.iloc[0]) ** (1 / yrs) - 1
    dd = (v / v.cummax() - 1).min()
    r = v.pct_change().dropna()
    sh = r.mean() / r.std() * np.sqrt(52)
    by = {int(y): (gg.iloc[-1] / gg.iloc[0] - 1) * 100 for y, gg in v.groupby(v.index.year) if len(gg) > 4}
    out = dict(CAGR=round(cagr * 100, 1), MDD=round(dd * 100, 1), Sharpe=round(sh, 2),
               Calmar=round(cagr / -dd, 2) if dd < 0 else None, worst_yr=round(min(by.values()), 1))
    if bench is not None:
        b = bench.reindex(v.index)
        bb = {int(y): (gg.iloc[-1] / gg.iloc[0] - 1) * 100 for y, gg in b.groupby(b.index.year) if len(gg) > 4}
        out['beat_yrs'] = f"{sum(by[y] > bb[y] for y in by)}/{len(by)}"
    return out, by

def blend(curves, weights, every=13):
    """여러 곡선을 비중대로 섞고 every 주마다 리밸런싱(비용 COST*회전율)"""
    R = pd.concat([c.pct_change().fillna(0) for c in curves], axis=1)
    w = np.array(weights, float); hold = w.copy(); v = 1.0; out = []
    for k, (t, row) in enumerate(R.iterrows()):
        hold = hold * (1 + row.values); v = hold.sum()
        if k % every == 0 and k > 0:
            new = w * v; turn = np.abs(new - hold).sum() / 2; v -= turn * COST; hold = w * v
        out.append(v)
    return pd.Series(out, index=R.index)


if __name__ == "__main__":
    px, g, spy, cr, mc = load()
    for name, kw in [("현행: 고점-20", dict(stop=20)),
                     ("제안: 손절없음+익절52/33+트림15→10", dict(stop=None, take=(52, 33), trim=15, cap=10))]:
        R = [stats(run(px, g, slots=20, delay=1, cash_r=cr, order="random", seed=100 + s, **kw)[0].v, spy)[0]
             for s in range(10)]
        D = pd.DataFrame(R)
        print(name, "CAGR 중앙", D.CAGR.median(), "MDD 중앙", D.MDD.median())
