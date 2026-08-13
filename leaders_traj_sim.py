# -*- coding: utf-8 -*-
"""궤적 규칙 백테스트 — 현행 규칙과 같은 조건에서 직접 비교."""
import os, sqlite3, warnings
import numpy as np, pandas as pd
import leaders_boost as B, leaders_sim2 as L2

warnings.filterwarnings("ignore")
pd.set_option("display.width", 250)
BASE = os.path.dirname(os.path.abspath(__file__))


def streak_up(s):
    up = (s.diff() > 0).astype(int)
    return up.groupby((up == 0).cumsum()).cumsum()


def panel():
    d = B.build()                      # 현행 규칙용 플래그(op_turn·b_any) 포함
    d["as_of"] = pd.to_datetime(d.as_of)
    c = sqlite3.connect(os.path.join(BASE, "data", "market.db"))
    x = pd.read_sql("SELECT as_of,sym,period_end,op_income,opm FROM factor_weekly "
                    "WHERE factor_ver='v1'", c)
    c.close()
    x["as_of"] = pd.to_datetime(x.as_of)
    q = (x.dropna(subset=["period_end"]).sort_values("as_of")
           .drop_duplicates(["sym", "period_end"]).sort_values(["sym", "period_end"]))
    g = q.groupby("sym")
    q["opi_up"] = g.op_income.transform(streak_up)
    q["opm_up"] = g.opm.transform(streak_up)
    # build()는 period_end를 안 내보내므로 '그 분기가 처음 반영된 주'에 붙이고
    # 다음 분기 값이 올 때까지 종목별로 전방 채움한다.
    d = d.merge(q[["sym", "as_of", "opi_up", "opm_up"]], on=["sym", "as_of"], how="left")
    d = d.sort_values(["sym", "as_of"])
    d[["opi_up", "opm_up"]] = d.groupby("sym")[["opi_up", "opm_up"]].ffill()
    return d


def main():
    d = panel()
    P, M = B.matrices(d)
    # matrices()는 정해진 컬럼만 피벗하므로 궤적 팩터를 직접 얹는다
    for c in ["opi_up", "opm_up"]:
        M[c] = d.pivot(index="as_of", columns="sym", values=c).reindex_like(P)
    S = L2.spy().reindex(P.index, method="nearest")
    SPL = [("2021", "2021-01-01", "2021-12-31"), ("2022", "2022-01-01", "2022-12-31"),
           ("2023", "2023-01-01", "2023-12-31"), ("2024", "2024-01-01", "2024-12-31"),
           ("2025", "2025-01-01", "2025-12-31"), ("2025H2~26", "2025-07-01", None)]

    def spy_cagr(a, b=None):
        s = S.loc[a:] if b is None else S.loc[a:b]
        y = (s.index[-1] - s.index[0]).days / 365.25
        return ((s.iloc[-1] / s.iloc[0]) ** (1 / y) - 1) * 100

    RULES = {
        "현행 RS1.5·(전환|폭증)·OPM>0":
            lambda M, i: (M["rs_13w"].iloc[i] > 1.5) & (M["opm"].iloc[i] > 0) &
                         ((M["op_turn"].iloc[i] == 1) | (M["b_any"].iloc[i] == 1)),
        "궤적 영업익2Q+·RS1.2·PSR<3":
            lambda M, i: (M["opi_up"].iloc[i] >= 2) & (M["rs_13w"].iloc[i] > 1.2) &
                         (M["psr"].iloc[i] < 3),
        "궤적 영업익2Q+·RS1.5·PSR<3":
            lambda M, i: (M["opi_up"].iloc[i] >= 2) & (M["rs_13w"].iloc[i] > 1.5) &
                         (M["psr"].iloc[i] < 3),
        "궤적 영업익3Q+·RS1.2·PSR<3":
            lambda M, i: (M["opi_up"].iloc[i] >= 3) & (M["rs_13w"].iloc[i] > 1.2) &
                         (M["psr"].iloc[i] < 3),
        "궤적 OPM3Q+·RS1.2·PSR<3":
            lambda M, i: (M["opm_up"].iloc[i] >= 3) & (M["rs_13w"].iloc[i] > 1.2) &
                         (M["psr"].iloc[i] < 3),
        "궤적 영업익2Q+·OPM2Q+·RS1.2·PSR<3":
            lambda M, i: (M["opi_up"].iloc[i] >= 2) & (M["opm_up"].iloc[i] >= 2) &
                         (M["rs_13w"].iloc[i] > 1.2) & (M["psr"].iloc[i] < 3),
    }

    def mk(fn):
        def sig(Mx, i, ent):
            ok = fn(Mx, i) & (Mx["adv_20d"].iloc[i] >= 5e6) & (Mx["marcap"].iloc[i] >= 2e9)
            return ok[ok.fillna(False)].index
        return sig

    rows = []
    for lab, fn in RULES.items():
        B.signal = mk(fn)
        for n in [8, 10, 12]:
            cfg = dict(trail=.20, maxpos=n, weight=1.0 / n, tiers=[1.0], ptrig="hi52", entry={})
            r = B.run(P, M, cfg)
            w = 0
            for _, a, b in SPL:
                rr = B.run(P, M, cfg, start=a, end=b)
                if rr["CAGR"] > spy_cagr(pd.Timestamp(a), pd.Timestamp(b) if b else None):
                    w += 1
            rows.append(dict(규칙=lab, 종목=n, CAGR=round(r["CAGR"], 1), MDD=round(r["MDD"], 1),
                             회복=round(r["회복"], 2), 거래=r["거래수"],
                             승률=round(r["승률"], 1), 노출=round(r["평균노출"], 1), WF=f"{w}/6"))
    R = pd.DataFrame(rows)
    print("=" * 112)
    print("궤적 규칙 vs 현행 — 확대 유니버스 · trail −20% · 전기간 + 워크포워드")
    print("=" * 112)
    print(R.to_string(index=False))
    sc = spy_cagr(P.index[0]); sm = (S / S.cummax() - 1).min() * 100
    print(f"\n[SPY] CAGR {sc:.1f}% · MDD {sm:.1f}% · 회복 {sc/abs(sm):.2f}")
    R.to_csv(os.path.join(BASE, "results", "traj_sim.csv"), index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
