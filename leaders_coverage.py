# -*- coding: utf-8 -*-
"""
데이터 커버리지 감사 — 2026년 후보 급증이 진짜인가, 수집 편향인가

supply.py에서 연도별 평균 후보 수가 A 0.5(2019) → 11.7(2026), R6 1.7 → 18.2로
20배 넘게 뛰었다. 신호가 진짜 늘었을 수도 있지만, 최신 분기 데이터가 더 촘촘히
잡히는 좌측 절단(left-censoring)일 수도 있다. 후자라면 백테스트 초반이 인위적으로
텅 비어 있었다는 뜻이고, WF·MDD·노출 전부가 흔들린다.

후보 수 = 유니버스 크기 × 조건 통과율 이므로 셋을 분해해서 본다.
  ① 유니버스   주차별 가격 유효 종목 수
  ② 커버리지   각 팩터가 non-null인 비율 (재무 데이터가 붙어 있는가)
  ③ 통과율     커버리지가 있는 종목 중 조건을 통과하는 비율

특히 b_any는 직전 8분기 rolling(min_periods=4)에 의존한다. 과거 분기 이력이
4개 미만이면 구조적으로 발화 자체가 불가능하다 — 이게 좌측 절단의 주범 후보다.
"""
import os, sqlite3, warnings
import numpy as np, pandas as pd
import leaders_boost as B

warnings.filterwarnings("ignore")
pd.set_option("display.width", 250, "display.max_columns", 40)
BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "market.db")


def quarter_history():
    """종목×분기 이력 — 8분기 rolling이 성립하는 시점이 언제부터인지"""
    c = sqlite3.connect(DB)
    d = pd.read_sql("""SELECT as_of,sym,period_end FROM factor_weekly
                       WHERE factor_ver='v1' AND period_end IS NOT NULL""", c)
    c.close()
    d["as_of"] = pd.to_datetime(d.as_of)
    q = (d.sort_values("as_of").drop_duplicates(["sym", "period_end"])
           .sort_values(["sym", "period_end"]).reset_index(drop=True))
    q["nq"] = q.groupby("sym").cumcount()          # 그 종목의 몇 번째 분기인가
    q["ok8"] = (q.nq >= 4).astype(int)             # min_periods=4 충족
    y = q.groupby(q.as_of.dt.year).agg(
        분기관측=("sym", "size"), 종목수=("sym", "nunique"),
        rolling가능=("ok8", lambda s: f"{s.mean()*100:.0f}%"))
    print("\n③ 분기 이력 축적 — b_any의 8분기 rolling(min_periods=4) 충족 여부")
    print("=" * 110)
    print(y.to_string())


def main():
    d = B.build(); d["as_of"] = pd.to_datetime(d.as_of)
    P, M = B.matrices(d)
    i0 = int(np.searchsorted(P.index, pd.Timestamp("2018-06-01")))
    idx = P.index[i0:]
    yr = idx.year

    def by_year(mat, how="cover"):
        """주차별 집계 후 연평균. how=cover면 non-null 개수, callable이면 조건 개수"""
        v = []
        for i in range(i0, len(P)):
            s = mat.iloc[i]
            v.append(s.notna().sum() if how == "cover" else int(how(s).sum()))
        return pd.Series(v, index=idx).groupby(yr).mean().round(1)

    price = pd.Series([P.iloc[i].notna().sum() for i in range(i0, len(P))],
                      index=idx).groupby(yr).mean().round(1)

    print("① 유니버스 · 팩터 커버리지 — 주차별 유효 종목 수의 연평균")
    print("=" * 110)
    cov = pd.DataFrame({"가격": price})
    for c in ("rs_13w", "marcap", "adv_20d", "opm", "per", "op_turn"):
        cov[c] = by_year(M[c])
    cov["b_any=1"] = by_year(M["b_any"], lambda s: s == 1)
    print(cov.to_string())

    print("\n② 개별 조건 통과 종목 수 (분모 아닌 절대 개수) — 연평균")
    print("=" * 110)
    C = pd.DataFrame({
        "RS13>1.5": by_year(M["rs_13w"], lambda s: s > 1.5),
        "RS13>1.7": by_year(M["rs_13w"], lambda s: s > 1.7),
        "OPM>0": by_year(M["opm"], lambda s: s > 0),
        "0<PER<20": by_year(M["per"], lambda s: (s > 0) & (s < 20)),
        "시총2B+": by_year(M["marcap"], lambda s: s >= 2e9),
        "거래대금5M+": by_year(M["adv_20d"], lambda s: s >= 5e6),
        "흑자전환": by_year(M["op_turn"], lambda s: s == 1),
        "이익폭증": by_year(M["b_any"], lambda s: s == 1),
    })
    print(C.to_string())

    print("\n②' 통과율 = 통과 종목 / 해당 팩터 커버리지 (%)")
    print("=" * 110)
    R = pd.DataFrame({
        "RS13>1.5": (C["RS13>1.5"] / cov["rs_13w"] * 100).round(1),
        "OPM>0": (C["OPM>0"] / cov["opm"] * 100).round(1),
        "0<PER<20": (C["0<PER<20"] / cov["per"] * 100).round(1),
        "흑자전환": (C["흑자전환"] / cov["op_turn"] * 100).round(1),
        "이익폭증": (C["이익폭증"] / cov["op_turn"] * 100).round(1),
    })
    print(R.to_string())

    quarter_history()

    print("\n④ 공시 지연 — as_of와 period_end 간격(주) 중앙값")
    print("=" * 110)
    c = sqlite3.connect(DB)
    q = pd.read_sql("""SELECT as_of,sym,period_end FROM factor_weekly
                       WHERE factor_ver='v1' AND period_end IS NOT NULL""", c)
    c.close()
    q["as_of"] = pd.to_datetime(q.as_of); q["period_end"] = pd.to_datetime(q.period_end)
    q = q.sort_values("as_of").drop_duplicates(["sym", "period_end"])
    q["lag_wk"] = ((q.as_of - q.period_end).dt.days / 7).round(1)
    print(q.groupby(q.as_of.dt.year).lag_wk.describe()[["count", "50%", "min", "max"]].to_string())

    cov.to_csv(os.path.join(BASE, "results", "coverage.csv"), encoding="utf-8-sig")


if __name__ == "__main__":
    main()
