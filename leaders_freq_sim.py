# -*- coding: utf-8 -*-
"""
손절폭 × 관측주기 스윕 — 주봉 vs 월봉

  · 손절폭: 고점 대비 −8% ~ −30%
  · 주기: 주봉(매주 확인) vs 월봉(한 달에 한 번만 확인)
    월봉은 각 달의 마지막 주차만 남겨 신호 확인·청산 판정을 모두 월 단위로 돌린다.
    "일을 덜 한다"의 정확한 형태 — 중간에 무슨 일이 있어도 월말에만 본다.

청산은 늘 동일: 진입 후 종가 고점 대비 X% 이탈 시 그 종가에 전량.
"""
import os, warnings, sqlite3
import numpy as np, pandas as pd
import leaders_boost as B, leaders_sim2 as L2

warnings.filterwarnings("ignore")
pd.set_option("display.width", 250)
BASE = os.path.dirname(os.path.abspath(__file__))
END = "2026-08-03"
SPL = [("2021", "2021-01-01", "2021-12-31"), ("2022", "2022-01-01", "2022-12-31"),
       ("2023", "2023-01-01", "2023-12-31"), ("2024", "2024-01-01", "2024-12-31"),
       ("2025", "2025-01-01", "2025-12-31"), ("2025H2~26", "2025-07-01", END)]
TRAILS = [.08, .10, .15, .20, .25, .30]


def main():
    d = B.build(); d["as_of"] = pd.to_datetime(d.as_of)
    P, M = B.matrices(d)
    S = L2.spy().reindex(P.index, method="nearest")

    # 월봉: 각 달의 마지막 주차만 남긴다
    mon = pd.Series(P.index, index=P.index).groupby(P.index.to_period("M")).max().values
    Pm = P.loc[mon]
    Mm = {k: v.loc[mon] for k, v in M.items()}
    Sm = S.loc[mon]
    print(f"주봉 {len(P)}행 · 월봉 {len(Pm)}행")

    R = {
        "A 이익폭증·PER<20·RS>1.5":
            lambda M, i: ((M["b_any"].iloc[i] == 1) & (M["per"].iloc[i] > 0) &
                          (M["per"].iloc[i] < 20) & (M["rs_13w"].iloc[i] > 1.5) &
                          (M["adv_20d"].iloc[i] >= 1e6)),
        "B (전환|폭증)·RS>1.7":
            lambda M, i: ((((M["op_turn"].iloc[i] == 1) | (M["b_any"].iloc[i] == 1)) &
                           (M["rs_13w"].iloc[i] > 1.7) & (M["adv_20d"].iloc[i] >= 1e6))),
        "R6 RS>1.5·(전환|폭증)·OPM>0·$2B+":
            lambda M, i: ((M["rs_13w"].iloc[i] > 1.5) & (M["opm"].iloc[i] > 0) &
                          ((M["op_turn"].iloc[i] == 1) | (M["b_any"].iloc[i] == 1)) &
                          (M["marcap"].iloc[i] >= 2e9) & (M["adv_20d"].iloc[i] >= 5e6)),
    }

    def mk(fn):
        def sig(Mx, i, ent):
            ok = fn(Mx, i)
            return ok[ok.fillna(False)].index
        return sig

    rows = []
    for freq, (PP, MM, SS) in [("주봉", (P, M, S)), ("월봉", (Pm, Mm, Sm))]:
        def spy_cagr(a, b):
            s = SS.loc[a:b]
            y = (s.index[-1] - s.index[0]).days / 365.25
            return ((s.iloc[-1] / s.iloc[0]) ** (1 / y) - 1) * 100
        for lab, fn in R.items():
            B.signal = mk(fn)
            for tr in TRAILS:
                cfg = dict(trail=tr, maxpos=12, weight=1 / 12, tiers=[1.0],
                           ptrig="hi52", entry={}, sort="rs_13w")
                r = B.run(PP, MM, cfg, end=END)
                w = sum(1 for _, a, b in SPL
                        if B.run(PP, MM, cfg, start=a, end=b)["CAGR"] >
                        spy_cagr(pd.Timestamp(a), pd.Timestamp(b)))
                rows.append(dict(주기=freq, 규칙=lab[:14], 손절=f"−{int(tr*100)}%",
                                 CAGR=round(r["CAGR"], 1), MDD=round(r["MDD"], 1),
                                 회복=round(r["회복"], 2), 거래=r["거래수"],
                                 승률=round(r["승률"], 1),
                                 보유=round(r["평균보유주"], 1),
                                 노출=round(r["평균노출"], 1), WF=f"{w}/6"))
                print(f"  {freq} {lab[:12]} {tr:.2f} → CAGR {r['CAGR']:.1f} "
                      f"MDD {r['MDD']:.1f} 회복 {r['회복']:.2f}", flush=True)
    T = pd.DataFrame(rows)
    T.to_csv(os.path.join(BASE, "results", "freq_sim.csv"), index=False, encoding="utf-8-sig")
    print("\n" + "=" * 124)
    print("손절폭 × 주기 — 12종목 고정 · 종료 2026-08-03")
    print("=" * 124)
    for f in ("주봉", "월봉"):
        print(f"\n── {f} ──")
        print(T[T.주기 == f].drop(columns="주기").to_string(index=False))
    print("\n[상위 10 · 회복배율]")
    print(T.sort_values("회복", ascending=False).head(10).to_string(index=False))


if __name__ == "__main__":
    main()
