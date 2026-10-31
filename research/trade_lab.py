# -*- coding: utf-8 -*-
"""🎮 매매 실험실 — 일봉·스탑 체결로 '종목 게임(A) × 지수 게임(B)' 조합을 잰다 (2026-10-31)
사전 등록: research/trade_lab_prereg_2026-10-31.md (결과 보기 전 커밋)
표본: results/trade_px.parquet(🪜 래칫과 같은 승자100·대조100, 미국·한국) · 지수 results/trade_idx.parquet
결과: results/trade_lab.json
"""
import os, sys, json, time
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import trade_rules as T
import stock_rules as R

OUT = os.path.join(ROOT, "results", "trade_lab.json")


def series(P, I):
    """종목별 (market, grp, sym, o,h,l,c, ix, start) — 창 첫날 = 그 시장 래칫 창 시작일."""
    info = json.load(open(os.path.join(ROOT, "results", "stock_ratchet.json"), encoding="utf-8"))["info"]
    out = []
    for (mkt, grp, sym), g in P.groupby(["market", "grp", "sym"], sort=False):
        g = g.sort_values("date")
        d0 = pd.Timestamp((info.get(mkt) or {}).get("window", ["2021-11-12"])[0])
        idx = pd.DatetimeIndex(g.date)
        s = int(np.searchsorted(idx, d0))
        if s >= len(idx) - 250:
            continue
        ix = I[T.INDEX_OF[mkt]].reindex(idx).ffill().values if T.INDEX_OF[mkt] in I else None
        out.append((mkt, grp, sym, g.o.values, g.h.values, g.l.values, g.c.values, ix, s))
    return out


def run(S, a, b):
    by = {}
    for mkt, grp, sym, o, h, l, c, ix, s in S:
        by.setdefault((mkt, grp), []).append(T.summarize(o, h, l, c, ix, s, a, b))
    return {f"{k[0]}|{k[1]}": R.aggregate(v) for k, v in by.items()}


def main():
    t0 = time.time()
    P = pd.read_parquet(os.path.join(ROOT, "results", "trade_px.parquet"))
    I = pd.read_parquet(os.path.join(ROOT, "results", "trade_idx.parquet"))
    I.index = pd.to_datetime(I.index)
    S = series(P, I)
    res = {}
    for an, a in T.PRESETS_A.items():
        for bn, b in T.PRESETS_B.items():
            res[f"{an} ‖ {bn}"] = run(S, a, b)
        print(f"{an} {time.time()-t0:.0f}s", flush=True)
    # 판정(사전 등록): 시장별 · 기준 = '그냥 보유 ‖ 지수 대비 없음'
    base = res["그냥 보유 ‖ 지수 대비 없음"]
    verdict = {}
    for key, r in res.items():
        v = {}
        for mkt in ("US", "KR"):
            w, c0 = r.get(f"{mkt}|승자100"), r.get(f"{mkt}|대조100")
            bw, bc = base.get(f"{mkt}|승자100"), base.get(f"{mkt}|대조100")
            if not (w and c0 and bw and bc):
                continue
            ok1 = c0["mdd_med"] - bc["mdd_med"] >= 0.10                  # 대조 MDD 10%p 이상 개선
            ok2 = w["mult_med"] >= 0.6 * bw["mult_med"]                   # 승자 배수 60% 이상 유지
            ok3 = c0["mult_med"] >= bc["mult_med"]                        # 대조 배수 악화 없음
            v[mkt] = dict(mdd=ok1, keep=ok2, ctl=ok3, ok=bool(ok1 and ok2 and ok3))
        v["passed"] = bool(v) and all(x["ok"] for x in v.values() if isinstance(x, dict))
        verdict[key] = v
    json.dump(dict(asof=str(pd.Timestamp.today().date()), prereg="research/trade_lab_prereg_2026-10-31.md",
                   n={f"{m}|{g}": sum(1 for x in S if x[0] == m and x[1] == g) for m in ("US", "KR") for g in ("승자100", "대조100")},
                   results=res, verdict=verdict, presets_a=T.PRESETS_A, presets_b=T.PRESETS_B,
                   note="일봉 · 스탑 체결(손절은 손절선, 재매수는 판 가격, 갭이면 시가) · 지수 비중은 다음 날 시가 · 편도 0.3%"),
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1,
              default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print(f"끝 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
