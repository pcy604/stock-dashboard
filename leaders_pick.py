# -*- coding: utf-8 -*-
"""
주도주 후보 리스트업 — factor_weekly / v_pick 조회

  python leaders_pick.py               # 최신 주차
  python leaders_pick.py 2026-06-01    # 특정 주차 (과거 재현)
  python leaders_pick.py --hist        # 신호별 후속 성과 검증
"""
import os, sqlite3, sys
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "market.db")
pd.set_option("display.width", 250, "display.max_columns", 40)


def con():
    return sqlite3.connect(DB)


def listup(as_of=None):
    c = con()
    if as_of is None:
        as_of = c.execute("SELECT MAX(as_of) FROM factor_weekly").fetchone()[0]
    q = """
    SELECT sym, name, action, score, size_mult, close, dist_52w, rs_26w,
           earn_date, earn_react_w0, weeks_since_earn,
           opm, opm_qoq, npm_qoq, psr, per, adv_20d/1e6 AS adv_m
    FROM v_pick
    WHERE as_of = ? AND ok_base = 1 AND gate_v = 1 AND gate_t = 1
    ORDER BY score DESC, dist_52w DESC
    """
    d = pd.read_sql(q, c, params=(as_of,))
    print("=" * 132)
    print(f"주도주 후보 — 기준 주차 {as_of}   (V게이트 ∧ T게이트 ∧ 유동성)")
    print("=" * 132)
    if d.empty:
        print("  조건 충족 종목 없음")
    else:
        for act in ["BUY_1", "PYRAMID_2", "WATCH"]:
            s = d[d.action == act]
            if s.empty:
                continue
            lab = {"BUY_1": "🟡 1차 매집 (E-signal 점등)",
                   "PYRAMID_2": "🟢 2차 피라미딩 (52주 신고가 돌파)",
                   "WATCH": "🔵 추적 중 (8주 카운트다운)"}[act]
            print(f"\n{lab}   {len(s)}종")
            print(s.drop(columns=["action"]).round(2).to_string(index=False))
    # 전체 통계
    tot = pd.read_sql("SELECT COUNT(*) n, COUNT(DISTINCT sym) s FROM factor_weekly WHERE as_of=?",
                      c, params=(as_of,)).iloc[0]
    g = pd.read_sql("SELECT SUM(gate_v) v, SUM(gate_t) t, SUM(gate_v*gate_t*ok_base) both "
                    "FROM v_pick WHERE as_of=?", c, params=(as_of,)).iloc[0]
    print(f"\n[유니버스 {tot.s}종]  V게이트 {g.v:.0f}종 · T게이트 {g.t:.0f}종 · "
          f"둘 다+유동성 {g.both:.0f}종  ({g.both/max(tot.s,1)*100:.1f}%)")
    c.close()
    return d


def hist():
    """과거 신호의 후속 성과 — 생존편향 없는 첫 검증"""
    c = con()
    q = """
    WITH p AS (SELECT as_of, sym, close, gate_v, gate_t, ok_base, action, score
               FROM v_pick),
    fwd AS (SELECT a.as_of, a.sym, a.close, a.gate_v, a.gate_t, a.ok_base, a.action, a.score,
              (SELECT b.close FROM factor_weekly b
               WHERE b.sym=a.sym AND b.as_of=date(a.as_of,'+91 day')) AS c13,
              (SELECT b.close FROM factor_weekly b
               WHERE b.sym=a.sym AND b.as_of=date(a.as_of,'+182 day')) AS c26
            FROM p a)
    SELECT * FROM fwd WHERE c13 IS NOT NULL
    """
    d = pd.read_sql(q, c)
    if d.empty:
        print("과거 데이터 부족"); return
    d["r13"] = (d.c13 / d.close - 1) * 100
    d["r26"] = (d.c26 / d.close - 1) * 100
    print("=" * 100)
    print(f"신호 검증 — 유니버스 전체 {len(d):,}개 관측 (생존편향 있음: 현재 상장 종목만)")
    print("=" * 100)
    rows = []
    for lab, m in [("전체 (대조군)", d.index == d.index),
                   ("V게이트만", d.gate_v == 1),
                   ("T게이트만", d.gate_t == 1),
                   ("V ∧ T ∧ 유동성", (d.gate_v == 1) & (d.gate_t == 1) & (d.ok_base == 1)),
                   ("  └ BUY_1", (d.gate_v == 1) & (d.gate_t == 1) & (d.ok_base == 1) & (d.action == "BUY_1")),
                   ("  └ PYRAMID_2", (d.gate_v == 1) & (d.gate_t == 1) & (d.ok_base == 1) & (d.action == "PYRAMID_2")),
                   ("  └ score ≥ 8", (d.gate_v == 1) & (d.gate_t == 1) & (d.ok_base == 1) & (d.score >= 8))]:
        s = d[m]
        if len(s) < 20:
            continue
        rows.append(dict(신호=lab, 관측수=len(s),
                         r13중앙=s.r13.median(), r26중앙=s.r26.dropna().median(),
                         승률13=f"{(s.r13>0).mean()*100:.0f}%",
                         승률26=f"{(s.r26.dropna()>0).mean()*100:.0f}%",
                         상위10p=s.r13.quantile(.9)))
    print(pd.DataFrame(rows).round(1).to_string(index=False))
    c.close()


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else None
    if a == "--hist":
        hist()
    else:
        listup(a)
