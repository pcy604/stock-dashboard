# -*- coding: utf-8 -*-
"""PEAD 재검증 — 종목 선택 편향 제거판 (2026-10-20, 05 문서 §3·§4 후속)

배경: PEAD(실적 갭 ≥10% + 이익가속) 24.6% 는 2026-08-05 이벤트 테이블(현재 시총 $2B+ 1,249종,
     '나중에 커진 회사'를 미리 고른 집합)에서 나왔다. 복원한 leaders_events.py 로 universe 전체의
     이벤트를 다시 만든 뒤, **규칙은 05 문서 그대로 고정**하고 다시 잰다(새 주변값 탐색 없음).

정의(05 문서 고정): 실적 반응 갭 ≥ +10% 인 주부터 4주 안에 ACC==1 + 유동성(거래대금·시총) 통과 → 1주 지연 매수.
청산·사이징: ★(20칸 · 고점 대비 -20%) · 무작위 순서 10회 중앙값 · 비용 편도 0.3% · 현금 FEDFUNDS.

편향 크기를 직접 잰다:
  A. 전 종목(편향 없음)          ← 판정 대상
  B. 오늘 시총 $2B+ 종목만(옛 테이블 방식 재현) vs C. 나머지
  D. 상장폐지 충격 연 1% (CLAUDE.md: 생존편향은 크기를 잰다)
합격(05 문서 기준 재사용): A 의 CAGR 중앙값 > ★ 이고 p10 > ★ 중앙값, 2014~2019 에서 SPY 이상.

사용: python research/pead_recheck.py   (market.db 에 earnings_event 가 있어야 함 → leaders_events.py build)
"""
import os, sys, json, sqlite3, time
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
import portfolio_rules_sim as S
A = S.A

GAP, WIN, SEEDS = 10.0, 4, 10
OUT = os.path.join(ROOT, "results", "pead_recheck.json")


def pead_gate(M, px, ev):
    """M: matrices(ACC·adv·marcap) · ev: earnings_event(sym, as_of, react_gap)."""
    base = ((M["adv_20d"] >= A.MIN_ADV) & (M["marcap"] >= A.MIN_MC) & (M["ACC"] == 1)).fillna(False)
    hit = pd.DataFrame(False, index=px.index, columns=px.columns)
    e = ev[(ev.react_gap >= GAP) & ev.sym.isin(px.columns)]
    pos = px.index
    for sym, t in zip(e.sym, pd.to_datetime(e.as_of)):
        i = int(np.searchsorted(pos, t))
        if i < len(pos):
            hit.iloc[i:i + WIN + 1, hit.columns.get_loc(sym)] = True
    return (base & hit), int(len(e))


def med(px, g, cr, spy, **kw):
    R, curves = [], []
    for s in range(SEEDS):
        h, _ = S.run(px, g, slots=20, stop=20, delay=1, cash_r=cr, order="random", seed=100 + s, **kw)
        st, by = S.stats(h.v, spy)
        sub = h.v[(h.v.index >= "2014-01-01") & (h.v.index < "2020-01-01")]
        st["y14_19"] = S.stats(sub)[0]["CAGR"] if len(sub) > 52 else None
        R.append(st)
    D = pd.DataFrame(R)
    return dict(CAGR=float(D.CAGR.median()), p10=float(D.CAGR.quantile(.1)), MDD=float(D.MDD.median()),
                Sharpe=float(D.Sharpe.median()),
                y14_19=(float(D.y14_19.median()) if D.y14_19.notna().any() else None))


def main():
    t0 = time.time()
    px, g, spy, cr, mc = S.load()
    d = A.load()
    M = A.matrices(d, ["adv_20d", "marcap", "ACC"])
    con = sqlite3.connect(os.path.join(ROOT, "data", "market.db"))
    ev = pd.read_sql("SELECT sym, as_of, react_gap FROM earnings_event", con)
    con.close()
    gp, n_ev = pead_gate(M, px, ev)

    # 옛 테이블 재현: '오늘' 시총 $2B 이상(마지막 유효 시총)
    last_mc = M["marcap"].ffill().iloc[-1]
    big = set(last_mc[last_mc >= 2e9].index)
    cols_big = [c for c in px.columns if c in big]
    cols_rest = [c for c in px.columns if c not in big]

    spy_w = spy.dropna()
    spy_st = S.stats(spy_w)[0]
    sub = spy_w[(spy_w.index >= "2014-01-01") & (spy_w.index < "2020-01-01")]
    out = dict(
        run=time.strftime("%Y-%m-%d %H:%M"), factor_ver=A.VER,
        period=[str(px.index[0].date()), str(px.index[-1].date())], universe=int(px.shape[1]),
        events_gap10=n_ev, ev_syms=int(ev.sym.nunique()),
        signals_per_year=round(float(gp.sum().sum()) / max(1, (px.index[-1] - px.index[0]).days / 365.25), 1),
        overlap_with_star=round(float((gp & g).sum().sum()) / max(1, float(gp.sum().sum())), 3),
        SPY=dict(CAGR=spy_st["CAGR"], MDD=spy_st["MDD"], y14_19=S.stats(sub)[0]["CAGR"] if len(sub) > 52 else None),
        star=med(px, g, cr, spy),
        A_pead_all=med(px, gp, cr, spy),
        B_pead_big_today=med(px[cols_big], gp[cols_big], cr, spy),
        C_pead_rest=med(px[cols_rest], gp[cols_rest], cr, spy),
        D_pead_all_shock1=med(px, gp, cr, spy, shock=0.01 / 52),
        n_big=len(cols_big), n_rest=len(cols_rest),
        prev=dict(source="05 문서(2026-10-19, 1,249종 테이블)", CAGR=24.6, p10=21.4, MDD=-38.6, y14_19=18.7),
    )
    a, st = out["A_pead_all"], out["star"]
    out["verdict"] = dict(
        beats_star=a["CAGR"] > st["CAGR"], p10_beats_star=a["p10"] > st["CAGR"],
        y14_19_beats_spy=(a["y14_19"] is not None and out["SPY"]["y14_19"] is not None
                          and a["y14_19"] >= out["SPY"]["y14_19"]),
        bias_gap_pp=round(out["B_pead_big_today"]["CAGR"] - out["C_pead_rest"]["CAGR"], 1),
    )
    out["verdict"]["pass"] = all(out["verdict"][k] for k in ("beats_star", "p10_beats_star", "y14_19_beats_spy"))
    out["secs"] = round(time.time() - t0)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    v = out["verdict"]
    print(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"::notice title=PEAD 재검증 ({A.VER})::전 종목 {a['CAGR']}% (p10 {a['p10']}, MDD {a['MDD']}, 14~19 {a['y14_19']}) · "
          f"★ {st['CAGR']}% · SPY {out['SPY']['CAGR']}% · 오늘 $2B+ {out['B_pead_big_today']['CAGR']}% vs 나머지 "
          f"{out['C_pead_rest']['CAGR']}% · 충격1% {out['D_pead_all_shock1']['CAGR']}% · 판정 {'합격' if v['pass'] else '불합격'}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        print(tb)
        print("::error title=PEAD 재검증 예외::" + tb[-900:].replace("\n", " | "))
        sys.exit(1)
