# -*- coding: utf-8 -*-
"""
3축 독립 평가 + 교집합 — 펀더멘탈 / 차트 / 밸류에이션

각 축을 따로 순위화한 뒤 교집합을 본다. 축을 섞어 한꺼번에 조건을 거는 것과 달리
"어느 축이 실제로 기여하는가"와 "겹칠 때 상승효과가 있는가"를 분리해서 볼 수 있다.

  · 순위는 매주 단면(cross-section) 백분위 — 레짐이 달라도 비교 가능하게
  · TRAIN 2018~2021 / TEST 2022~ 분리. 교집합 설계는 TRAIN만 보고 TEST로 확인
  · 거래 가능 영역(시총 $2B+ · 거래대금 $5M+ · 주가 $5+)에서만

신고가는 개별 기간이 아니라 '동시 달성 개수'(5·10·20·52주 중 몇 개)로도 잰다.
"""
import os, sqlite3, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
pd.set_option("display.width", 250, "display.max_columns", 40)
BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "market.db")
CUT, TRAIN_END = 1.50, "2021-12-31"

# 축 정의 — (컬럼, 방향). +1이면 클수록 좋다고 가정, -1이면 작을수록.
CHART = [("rs_13w", +1), ("rs_26w", +1), ("ret_13w", +1),
         ("dist_52w", +1), ("vol_x_20w", +1), ("above_ma20_52w", +1)]
FUND = [("rev_yoy", +1), ("opm", +1), ("opm_qoq", +1), ("gpm_qoq", +1),
        ("npm_qoq", +1), ("op_pos_streak", +1)]
VALU = [("psr", -1), ("per", -1), ("pbr", -1)]


def load():
    c = sqlite3.connect(DB)
    cols = [x for x, _ in CHART + FUND + VALU]
    d = pd.read_sql(f"SELECT as_of,sym,close,marcap,adv_20d,op_turn,"
                    f"hi_5w,hi_10w,hi_20w,hi_52w,{','.join(cols)} "
                    "FROM factor_weekly WHERE factor_ver='v1'", c)
    c.close()
    d["as_of"] = pd.to_datetime(d.as_of)
    px = d.pivot(index="as_of", columns="sym", values="close").sort_index()
    fwd = (px.shift(-52) / px - 1).stack().rename("fwd").reset_index()
    d = d.merge(fwd, on=["as_of", "sym"], how="left").dropna(subset=["fwd"])
    bad = set(d.groupby("sym").fwd.max().pipe(lambda s: s[s > 20]).index)
    d = d[~d.sym.isin(bad)]
    d = d[(d.marcap >= 2e9) & (d.adv_20d >= 5e6) & (d.close >= 5)].copy()
    d["leader"] = (d.fwd >= CUT).astype(int)
    d["hi_cnt"] = d[["hi_5w", "hi_10w", "hi_20w", "hi_52w"]].fillna(0).sum(axis=1)
    return d.replace([np.inf, -np.inf], np.nan)


def axis_score(d, spec, name):
    """매주 단면 백분위의 평균 = 축 점수 (0~100). 결측 팩터는 그 종목에서 제외."""
    parts = []
    for col, sign in spec:
        r = d.groupby("as_of")[col].rank(pct=True) * 100
        parts.append(r if sign > 0 else 100 - r)
    s = pd.concat(parts, axis=1)
    d[name] = s.mean(axis=1, skipna=True)
    d[name + "_n"] = s.notna().sum(axis=1)
    return d


def band(d, col, br, label, bins=(0, 50, 70, 85, 95, 100)):
    x = d.dropna(subset=[col]).copy()
    x["b"] = pd.cut(x[col], bins, include_lowest=True)
    g = x.groupby("b", observed=True).agg(
        관측=("leader", "size"), 리프트=("leader", lambda v: v.mean() / br),
        수익중앙=("fwd", lambda v: v.median() * 100),
        승률=("fwd", lambda v: (v > 0).mean() * 100))
    print(f"\n[{label}]")
    print(g.round(2).to_string())


def main():
    d = load()
    for spec, nm in [(CHART, "chart"), (FUND, "fund"), (VALU, "valu")]:
        d = axis_score(d, spec, nm)
    # 축별 최소 팩터 수 미달은 제외 (결측이 많은 종목의 점수는 못 믿는다)
    d = d[(d.chart_n >= 4) & (d.fund_n >= 3) & (d.valu_n >= 2)].copy()

    tr, te = d[d.as_of <= TRAIN_END], d[d.as_of > TRAIN_END]
    br_tr, br_te = tr.leader.mean(), te.leader.mean()
    print(f"거래가능·3축 산출 가능 관측 {len(d):,} · 종목 {d.sym.nunique()}")
    print(f"TRAIN {len(tr):,} (주도주 {br_tr*100:.2f}%) · TEST {len(te):,} ({br_te*100:.2f}%)")

    print("\n" + "=" * 96)
    print("① 축 단독 — 백분위 구간별 (TRAIN)")
    print("=" * 96)
    for nm, lab in [("chart", "차트 축"), ("fund", "펀더멘탈 축"), ("valu", "밸류에이션 축(저평가일수록 높음)")]:
        band(tr, nm, br_tr, lab)

    print("\n" + "=" * 96)
    print("② 신고가 동시 달성 개수 (5·10·20·52주 중) — TRAIN")
    print("=" * 96)
    g = tr.groupby("hi_cnt").agg(관측=("leader", "size"),
                                 리프트=("leader", lambda v: v.mean() / br_tr),
                                 수익중앙=("fwd", lambda v: v.median() * 100),
                                 승률=("fwd", lambda v: (v > 0).mean() * 100))
    print(g.round(2).to_string())

    print("\n" + "=" * 96)
    print("③ 교집합 — 각 축 상위 X% 를 겹쳤을 때 (TRAIN → TEST)")
    print("=" * 96)
    hdr = f"{'조합':34s}{'TR관측':>8s}{'TR리프트':>9s}{'TR수익':>8s}{'TE관측':>8s}{'TE리프트':>9s}{'TE수익':>8s}{'TE승률':>8s}"
    print(hdr)
    for thr in [70, 80, 90]:
        combos = [("차트", ["chart"]), ("펀더", ["fund"]), ("밸류", ["valu"]),
                  ("차트+펀더", ["chart", "fund"]), ("차트+밸류", ["chart", "valu"]),
                  ("펀더+밸류", ["fund", "valu"]), ("3축 전부", ["chart", "fund", "valu"])]
        for lab, axes in combos:
            mt = np.logical_and.reduce([tr[a] >= thr for a in axes])
            ms = np.logical_and.reduce([te[a] >= thr for a in axes])
            a, b = tr[mt], te[ms]
            if len(a) < 200 or len(b) < 200:
                print(f"{f'상위{100-thr}% {lab}':34s}{len(a):>8,}{'표본부족':>9s}")
                continue
            print(f"{f'상위{100-thr}% {lab}':34s}{len(a):>8,}{a.leader.mean()/br_tr:>9.2f}"
                  f"{a.fwd.median()*100:>7.1f}%{len(b):>8,}{b.leader.mean()/br_te:>9.2f}"
                  f"{b.fwd.median()*100:>7.1f}%{(b.fwd>0).mean()*100:>7.1f}%")
        print()


if __name__ == "__main__":
    main()
