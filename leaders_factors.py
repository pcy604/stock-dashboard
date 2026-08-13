# -*- coding: utf-8 -*-
"""
팩터 유의성 전수 스캔 — 기술 / 기본 / 밸류

방법론 (이 프로젝트에서 배운 것 반영)
  · IC(선형 순위상관)는 쓰지 않는다. U자 관계가 정확히 0으로 나오기 때문.
  · 대신 십분위 구간별 반응 곡선을 그리고 최고 리프트 구간을 찾는다.
  · "주도주가 많이 나온다"와 "돈을 번다"는 다른 질문이라 둘 다 잰다.
  · 단일 수치는 레짐 의존을 숨기므로 연도 집중도를 함께 보고한다.

주도주 = 그 시점 이후 52주 +150% 이상 (leaders_profile.py와 동일)
실행: python leaders_factors.py
"""
import os, sqlite3, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
pd.set_option("display.width", 250, "display.max_columns", 40)
BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "market.db")
CUT, MIN_N = 1.50, 3000

TECH = ["rs_4w", "rs_13w", "rs_26w", "ret_1w", "ret_4w", "ret_13w", "ret_ytd",
        "dist_52w", "days_since_hi52", "low_52w_dist", "mdd_52w",
        "above_ma20_52w", "break_ma20_52w", "vol_x_20w", "adv_20d"]
FUND = ["rev_yoy", "rev_qoq", "gpm", "gpm_qoq", "opm", "opm_qoq", "npm", "npm_qoq",
        "eps_yoy", "op_pos_streak", "earn_react_w0", "earn_react_d2", "earn_streak_pos"]
VALU = ["psr", "per", "pbr", "psr_pct5y", "marcap"]
FLAGS = ["op_turn", "gpm_up2", "opm_up2", "npm_up2", "close_gt_ma20", "ma10_gt_ma20",
         "hi_5w", "hi_10w", "hi_20w", "hi_52w", "earn_week_flag"]


def load():
    c = sqlite3.connect(DB)
    cols = TECH + FUND + VALU + FLAGS
    d = pd.read_sql(f"SELECT as_of,sym,close,{','.join(cols)} "
                    "FROM factor_weekly WHERE factor_ver='v1'", c)
    c.close()
    d["as_of"] = pd.to_datetime(d.as_of)
    px = d.pivot(index="as_of", columns="sym", values="close").sort_index()
    fwd = (px.shift(-52) / px - 1).stack().rename("fwd").reset_index()
    d = d.merge(fwd, on=["as_of", "sym"], how="left").dropna(subset=["fwd"])
    bad = set(d.groupby("sym").fwd.max().pipe(lambda s: s[s > 20]).index)   # 분할/오염 제거
    d = d[~d.sym.isin(bad)].copy()
    d["leader"] = (d.fwd >= CUT).astype(int)
    d["yr"] = d.as_of.dt.year
    return d


def scan(d, cols, base_rate, flag=False):
    rows = []
    for c in cols:
        # inf 제거 — 매출 0 분기의 opm 등이 inf로 들어와 qcut을 깨뜨린다
        x = d[[c, "leader", "fwd", "yr"]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(x) < MIN_N:
            continue
        if flag or x[c].nunique() <= 3:
            x["b"] = x[c].astype(int).astype(str)
        else:
            try:
                x["b"] = pd.qcut(x[c], 10, duplicates="drop")
            except Exception:
                continue
        g = x.groupby("b", observed=True).agg(
            n=("leader", "size"), lead=("leader", "sum"),
            rate=("leader", "mean"), med=("fwd", "median"), win=("fwd", lambda v: (v > 0).mean()))
        g = g[g.n >= MIN_N]
        if g.empty:
            continue
        g["lift"] = g["rate"] / base_rate
        best = g.lift.idxmax()
        b = g.loc[best]
        # 최고 구간의 연도 집중도 — 주도주 관측이 한 해에 몰려 있나
        sub = x[x.b == best]
        yc = sub[sub.leader == 1].yr.value_counts(normalize=True)
        # 2020 폭락 반등을 빼고도 리프트가 남는가 — 단일 수치는 레짐 의존을 숨긴다
        x20 = x[x.yr != 2020]
        s20 = x20[x20.b == best]
        lift20 = (s20.leader.mean() / x20.leader.mean()) if len(s20) >= MIN_N // 2 else np.nan
        rows.append(dict(팩터=c, 구간=str(best)[:22], 관측=int(b.n),
                         리프트=round(b.lift, 2),
                         리프트_2020제외=round(lift20, 2) if lift20 == lift20 else None,
                         수익중앙=round(b.med * 100, 1), 승률=round(b.win * 100, 1),
                         연도집중=round(yc.iloc[0] * 100, 0) if len(yc) else np.nan))
    return pd.DataFrame(rows).sort_values("리프트", ascending=False)


def cross(d, base_rate, pairs):
    print("\n" + "=" * 104)
    print("교차 — 상위 팩터를 겹쳤을 때 리프트가 더 오르나 (관측 1,500 이상만)")
    print("=" * 104)
    for (c1, q1, l1), (c2, q2, l2) in pairs:
        x = d.dropna(subset=[c1, c2])
        m1, m2 = q1(x[c1]), q2(x[c2])
        for lab, m in [(l1, m1 & ~m2), (l2, ~m1 & m2), (f"{l1} AND {l2}", m1 & m2)]:
            s = x[m]
            if len(s) < 1500:
                print(f"  {lab:38s} 관측 {len(s):6,} — 표본 부족"); continue
            print(f"  {lab:38s} 관측 {len(s):6,} · 리프트 {s.leader.mean()/base_rate:5.2f} · "
                  f"수익중앙 {s.fwd.median()*100:6.1f}% · 승률 {(s.fwd>0).mean()*100:4.1f}%")
        print()


def main():
    d = load()
    br = d.leader.mean()
    print(f"관측 {len(d):,} · 종목 {d.sym.nunique()} · 기간 {d.as_of.min():%Y-%m}~{d.as_of.max():%Y-%m}")
    print(f"주도주(이후 52주 +{int(CUT*100)}%↑) {int(d.leader.sum()):,}건 · 기준율 {br*100:.2f}%")
    print(f"※ 리프트 1.0 = 유니버스 평균. 각 구간 최소 관측 {MIN_N:,}\n")

    for title, cols, fl in [("기술적 팩터", TECH, False), ("기본적 팩터", FUND, False),
                            ("밸류에이션", VALU, False), ("불리언 플래그", FLAGS, True)]:
        t = scan(d, cols, br, fl)
        print("=" * 104); print(title); print("=" * 104)
        print(t.to_string(index=False) if len(t) else "  (측정 가능 팩터 없음)")
        print()

    cross(d, br, [
        ((("rs_13w"), lambda s: s > 1.5, "RS13>1.5"), (("op_turn"), lambda s: s == 1, "흑자전환")),
        ((("rs_13w"), lambda s: s > 1.5, "RS13>1.5"), (("opm"), lambda s: s > 0, "OPM>0")),
        ((("rs_13w"), lambda s: s > 1.5, "RS13>1.5"), (("psr"), lambda s: s < 3, "PSR<3")),
        ((("rs_13w"), lambda s: s > 1.5, "RS13>1.5"), (("marcap"), lambda s: s < 5e9, "시총<$5B")),
        ((("op_turn"), lambda s: s == 1, "흑자전환"), (("psr"), lambda s: s < 3, "PSR<3")),
    ])


if __name__ == "__main__":
    main()
