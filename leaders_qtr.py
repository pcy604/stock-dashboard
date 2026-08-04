# -*- coding: utf-8 -*-
"""
'1년에 4번만 본다' 분석 — 실적 반응 주에만 판단
  성과 = 다음 실적 반응 주까지의 수익률 (ret_to_next) ★ 관측 겹침 없음
  비용 = 그 사이 최대 낙폭 (dd_to_next) ★ 분기 점검의 대가
  python leaders_qtr.py [TRAIN_END]
"""
import os, sqlite3, sys
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "market.db")
pd.set_option("display.width", 240, "display.max_columns", 30)
TRAIN_END = sys.argv[1] if len(sys.argv) > 1 else "2022-12-31"
BANDS = [("소형 $2~10B", 0, 10e9), ("중형 $10~50B", 10e9, 50e9), ("대형 $50B+", 50e9, 9e15)]

FACTORS = ["react_gap", "react_d0", "react_w0", "react_streak",
           "rev_yoy", "rev_qoq", "gpm", "gpm_qoq", "opm", "opm_qoq", "opm_up2",
           "npm", "npm_qoq", "npm_up2", "op_turn", "op_pos_streak",
           "dist_52w", "rs_4w", "rs_13w", "rs_26w", "above_ma20_52w", "break_ma20_52w",
           "close_gt_ma20", "ma10_gt_ma20", "hi_52w", "ret_4w", "ret_13w_y",
           "mdd_52w", "low_52w_dist", "vol_x_20w", "psr", "per", "marcap"]
# ※ ret_13w_y = factor_weekly의 '과거 13주 수익률'(팩터).
#    ret_13w_x = 이벤트 테이블의 '향후 13주 수익률'(정답) — 절대 팩터로 쓰면 안 됨


def load():
    c = sqlite3.connect(DB)
    d = pd.read_sql("SELECT * FROM earnings_event", c)
    c.close()
    d["as_of"] = pd.to_datetime(d.as_of)
    d = d[d.dist_52w.notna()]                      # 팩터 결합된 것만 (2018+)
    d = d[(d.close >= 5) & (d.adv_20d >= 5e6)]     # 저가·저유동성 배제
    d = d.dropna(subset=["ret_to_next"])
    # 극단값 절단
    lo, hi = d.ret_to_next.quantile(.01), d.ret_to_next.quantile(.99)
    d["y"] = d.ret_to_next.clip(lo, hi)
    d["band"] = None
    for lab, l, h in BANDS:
        d.loc[(d.marcap >= l) & (d.marcap < h), "band"] = lab
    d = d.dropna(subset=["band"])
    d["q"] = d.as_of.dt.to_period("Q").astype(str)
    print(f"이벤트 {len(d):,} · {d.sym.nunique()}종 · {d.as_of.min().date()}~{d.as_of.max().date()}")
    print(f"  winsorize [{lo:.0f}%, {hi:.0f}%]")
    return d


def cost(d):
    print("\n" + "=" * 96)
    print("① 분기 점검의 비용 — 실적과 실적 사이에 얼마나 빠졌나")
    print("=" * 96)
    v = d.dd_to_next.dropna()
    print(f"  실적 사이 최대낙폭  중앙 {v.median():.1f}%  ·  25%지점 {v.quantile(.25):.1f}%  "
          f"·  10%지점 {v.quantile(.10):.1f}%  ·  최악 {v.min():.1f}%")
    for t in (-10, -15, -20, -30):
        print(f"    {t}% 이하로 빠진 분기 비율: {(v <= t).mean()*100:5.1f}%")
    print(f"\n  → 분기 점검만 하면 이 낙폭을 '보고도 못 팔거나, 아예 못 본다'")
    print(f"  보유주수 중앙 {d.hold_wk.median():.0f}주 (25% {d.hold_wk.quantile(.25):.0f} / "
          f"75% {d.hold_wk.quantile(.75):.0f})")


def ic(d, label):
    x = d.copy()
    x["yr"] = x.groupby("q").y.rank(pct=True)
    rows = []
    for f in FACTORS:
        s = x[[f, "yr", "q"]].dropna()
        if len(s) < 500 or s[f].nunique() < 3:
            continue
        r = s.groupby("q")[f].rank(pct=True)
        rows.append(dict(factor=f, IC=np.corrcoef(r, s.yr)[0, 1], n=len(s)))
    t = pd.DataFrame(rows).sort_values("IC", key=abs, ascending=False)
    print(f"\n[{label}] 팩터 IC — 다음 실적까지 수익률 기준 (분기 내 랭킹)")
    print(t.head(16).round(3).to_string(index=False))
    return t


def run_band(d, lab):
    b = d[d.band == lab]
    tr, te = b[b.as_of <= TRAIN_END], b[b.as_of > TRAIN_END]
    if len(tr) < 800 or len(te) < 400:
        print(f"\n### {lab}: 표본 부족 ({len(tr)}/{len(te)})"); return None
    print(f"\n{'='*96}\n### {lab}  TRAIN {len(tr):,} · TEST {len(te):,} · 종목 {b.sym.nunique()}\n{'='*96}")
    T = ic(tr, f"{lab} TRAIN")
    picks = T[T.IC.abs() >= 0.03].factor.tolist()[:6]
    if not picks:
        print("  판별 팩터 없음"); return None
    sg = {f: np.sign(T.set_index("factor").IC[f]) for f in picks}
    print("\n  채택: " + ", ".join(f"{f}({'+' if sg[f]>0 else '−'})" for f in picks))

    def sc(x):
        z = pd.DataFrame(index=x.index)
        for f in picks:
            z[f] = x.groupby("q")[f].rank(pct=True) * sg[f]
        return z.mean(axis=1)
    out = {}
    for nm, x in [("TRAIN", tr), ("TEST", te)]:
        x = x.assign(score=sc(x)).dropna(subset=["score"])
        x["dec"] = x.groupby("q").score.transform(
            lambda v: pd.qcut(v.rank(method="first"), 5, labels=False, duplicates="drop"))
        g = x.groupby("dec").agg(n=("y", "size"), 평균=("y", "mean"), 중앙=("y", "median"),
                                 승률=("y", lambda v: (v > 0).mean()*100),
                                 상위10p=("y", lambda v: v.quantile(.9)),
                                 낙폭중앙=("dd_to_next", "median"))
        print(f"\n  {nm} — 스코어 5분위 (다음 실적까지 수익률 %)")
        print(g.round(1).to_string())
        out[nm] = g
    if 4 in out["TRAIN"].index and 4 in out["TEST"].index:
        a = out["TRAIN"].loc[4, "중앙"] - out["TRAIN"].loc[0, "중앙"]
        c_ = out["TEST"].loc[4, "중앙"] - out["TEST"].loc[0, "중앙"]
        print(f"    스프레드  TRAIN {a:+.1f}%p → TEST {c_:+.1f}%p   유지율 {c_/a*100 if a else 0:.0f}%")
        return dict(밴드=lab, TRAIN=a, TEST=c_, 유지율=c_/a*100 if a else np.nan,
                    TEST최상위=out["TEST"].loc[4, "중앙"], 승률=out["TEST"].loc[4, "승률"],
                    낙폭=out["TEST"].loc[4, "낙폭중앙"])
    return None


def main():
    d = load()
    cost(d)
    print("\n" + "#" * 96)
    print(f"② 밴드별 검증  TRAIN ~{TRAIN_END} / TEST 이후")
    print("#" * 96)
    res = [r for lab, _, _ in BANDS if (r := run_band(d, lab))]
    if res:
        print("\n" + "#" * 96 + "\n최종 요약\n" + "#" * 96)
        print(pd.DataFrame(res).round(1).to_string(index=False))


if __name__ == "__main__":
    main()
