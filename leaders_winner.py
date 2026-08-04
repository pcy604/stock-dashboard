# -*- coding: utf-8 -*-
"""
승자 역분석 v2 — 세 가지 수정 반영
  ① 데이터 정제: 극단값 절단 · 재상장/합병 왜곡 종목 제외 · 저가주/저유동성 배제
  ② 밴드 내 정규화: 팩터 랭킹을 (시점 × 시총밴드) 안에서 수행
  ③ 밴드별 전용 스코어: 밴드마다 팩터를 따로 뽑아 따로 검증
  TRAIN 2018~2021 에서만 도출 → TEST 2022~2026 에 1회 적용
"""
import os, sqlite3
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "market.db")
pd.set_option("display.width", 250, "display.max_columns", 40)

import sys as _s
TRAIN_END = _s.argv[1] if len(_s.argv) > 1 else "2021-12-31"
FWD_W     = int(_s.argv[2]) if len(_s.argv) > 2 else 52
TEST_END  = _s.argv[3] if len(_s.argv) > 3 else "2099-12-31"
STEP      = int(_s.argv[4]) if len(_s.argv) > 4 else 13
BANDS = [("소형 $2~10B", 0, 10e9), ("중형 $10~50B", 10e9, 50e9), ("대형 $50B+", 50e9, 9e15)]
IC_MIN = 0.03
MAX_PLAUSIBLE = 20.0     # 1년 +2000% 초과 = 재상장/합병 왜곡으로 간주
WINS = 0.01              # 상하위 1% 절단

FACTORS = [
    "rev_yoy", "rev_qoq", "gpm", "gpm_qoq", "gpm_up2", "opm", "opm_qoq", "opm_up2",
    "npm", "npm_qoq", "npm_up2", "op_turn", "op_pos_streak",
    "dist_52w", "rs_4w", "rs_13w", "rs_26w", "above_ma20_52w", "break_ma20_52w",
    "close_gt_ma20", "ma10_gt_ma20", "hi_5w", "hi_20w", "hi_52w",
    "ret_4w", "ret_13w", "mdd_52w", "low_52w_dist", "vol_x_20w", "days_since_hi52",
    "earn_react_w0", "earn_react_d2", "weeks_since_earn",
    "psr", "per", "marcap",
]


def load():
    c = sqlite3.connect(DB)
    cols = ",".join(["as_of", "sym", "name", "close", "adv_20d"] + FACTORS)
    d = pd.read_sql(f"SELECT {cols} FROM factor_weekly WHERE factor_ver='v1'", c)
    c.close()
    d["as_of"] = pd.to_datetime(d.as_of)
    px = d.pivot(index="as_of", columns="sym", values="close").sort_index()
    fwd = (px.shift(-FWD_W) / px - 1).stack().rename("fwd52").reset_index()
    return d.merge(fwd, on=["as_of", "sym"], how="left").dropna(subset=["fwd52"])


# ───────────────────── ① 데이터 정제 ─────────────────────
def clean(d):
    n0 = len(d)
    # 재상장/합병 왜곡 종목 통째로 제외
    bad = d.groupby("sym").fwd52.max()
    bad = set(bad[bad > MAX_PLAUSIBLE].index)
    # 주간 100% 초과 급등이 3회 이상인 종목도 왜곡 의심
    px = d.pivot(index="as_of", columns="sym", values="close").sort_index()
    jump = ((px.pct_change().abs() > 1.0).sum())
    bad |= set(jump[jump >= 3].index)
    d = d[~d.sym.isin(bad)]
    n1 = len(d)
    # 저가주·저유동성 배제
    d = d[(d.close >= 5) & (d.adv_20d >= 5e6)]
    n2 = len(d)
    # 극단값 절단 (평가용 컬럼 별도 보관)
    lo, hi = d.fwd52.quantile(WINS), d.fwd52.quantile(1 - WINS)
    d = d.copy()
    d["fwd_w"] = d.fwd52.clip(lo, hi)
    print(f"정제: {n0:,} → 왜곡종목 {len(bad)}개 제외 {n1:,} → 저가/저유동성 제외 {n2:,}")
    print(f"      제외 종목 예: {sorted(list(bad))[:12]}")
    print(f"      winsorize [{lo*100:.0f}%, {hi*100:.0f}%]  평균 {d.fwd52.mean()*100:.1f}% → {d.fwd_w.mean()*100:.1f}%")
    return d


def assign_band(d):
    d = d.copy()
    d["band"] = None
    for lab, lo, hi in BANDS:
        d.loc[(d.marcap >= lo) & (d.marcap < hi), "band"] = lab
    return d.dropna(subset=["band"])


def cohort(d):
    dates = sorted(d.as_of.unique())
    return d[d.as_of.isin(set(dates[::STEP]))].copy()


# ───────────────── ② 밴드 내 정규화 ─────────────────
def band_rank(g, f):
    """(시점 × 밴드) 안에서 백분위 랭킹"""
    return g.groupby(["as_of", "band"])[f].rank(pct=True)


def ic_table(s, label):
    s = s.copy()
    s["y"] = s.groupby(["as_of", "band"]).fwd_w.rank(pct=True)
    rows = []
    for f in FACTORS:
        sub = s[[f, "y", "as_of", "band"]].dropna()
        if len(sub) < 300 or sub[f].nunique() < 3:
            continue
        r = sub.groupby(["as_of", "band"])[f].rank(pct=True)
        rows.append(dict(factor=f, IC=np.corrcoef(r, sub.y)[0, 1], n=len(sub)))
    t = pd.DataFrame(rows).sort_values("IC", key=abs, ascending=False)
    print(f"\n[{label}] 밴드 내 정규화 IC")
    print(t.head(14).round(3).to_string(index=False))
    return t


def make_score(df, picks, signs):
    z = pd.DataFrame(index=df.index)
    for f in picks:
        z[f] = band_rank(df, f) * signs[f]
    return z.mean(axis=1)


def evaluate(df, label):
    x = df.dropna(subset=["score"]).copy()
    x["dec"] = x.groupby(["as_of", "band"]).score.transform(
        lambda v: pd.qcut(v.rank(method="first"), 5, labels=False, duplicates="drop"))
    g = x.groupby("dec").agg(n=("fwd_w", "size"),
                             평균=("fwd_w", lambda v: v.mean()*100),
                             중앙=("fwd_w", lambda v: v.median()*100),
                             승률=("fwd_w", lambda v: (v > 0).mean()*100),
                             상위10p=("fwd_w", lambda v: v.quantile(.9)*100))
    print(f"\n  {label} — 스코어 5분위")
    print(g.round(1).to_string())
    if 4 in g.index and 0 in g.index:
        print(f"    최상위−최하위:  평균 {g.loc[4,'평균']-g.loc[0,'평균']:+.1f}%p · "
              f"중앙 {g.loc[4,'중앙']-g.loc[0,'중앙']:+.1f}%p · "
              f"승률 {g.loc[4,'승률']-g.loc[0,'승률']:+.1f}%p")
    return g


def main():
    d = clean(load())
    d = assign_band(d)
    s = cohort(d)
    tr = s[s.as_of <= TRAIN_END]
    te = s[(s.as_of > TRAIN_END) & (s.as_of <= TEST_END)]
    print(f"\n[설정] 평가지평 {FWD_W}주 · 샘플간격 {STEP}주 · "
          f"TRAIN~{TRAIN_END} · TEST~{TEST_END}")
    if len(te):
        print(f"       TEST 실제 사용 구간 {te.as_of.min().date()} ~ {te.as_of.max().date()} "
              f"({te.as_of.nunique()}개 시점)")
    print(f"\n전체 {len(s):,}관측 · {s.sym.nunique()}종 · {s.as_of.nunique()}시점")
    print(f"TRAIN {len(tr):,} / TEST {len(te):,}")

    print("\n" + "#" * 100)
    print("③ 밴드별 전용 스코어 — 밴드마다 팩터를 따로 뽑고 따로 검증")
    print("#" * 100)
    summary = []
    for lab, lo, hi in BANDS:
        btr, bte = tr[tr.band == lab], te[te.band == lab]
        if len(btr) < 500 or len(bte) < 300:
            print(f"\n### {lab}: 표본 부족 (TRAIN {len(btr)}, TEST {len(bte)})"); continue
        print(f"\n{'='*100}\n### {lab}   TRAIN {len(btr):,} · TEST {len(bte):,} · "
              f"종목 {btr.sym.nunique()}\n{'='*100}")
        T = ic_table(btr, f"{lab} TRAIN")
        picks = T[T.IC.abs() >= IC_MIN].factor.tolist()[:6]
        if not picks:
            print("  판별 팩터 없음"); continue
        signs = {f: np.sign(T.set_index("factor").IC[f]) for f in picks}
        print(f"\n  채택 팩터: " + ", ".join(f"{f}({'+' if signs[f]>0 else '−'})" for f in picks))
        gtr = evaluate(btr.assign(score=make_score(btr, picks, signs)), "TRAIN(인샘플)")
        gte = evaluate(bte.assign(score=make_score(bte, picks, signs)), "TEST(아웃샘플)")
        if 4 in gtr.index and 4 in gte.index:
            summary.append(dict(밴드=lab, 팩터수=len(picks),
                                TRAIN스프레드=gtr.loc[4, "중앙"] - gtr.loc[0, "중앙"],
                                TEST스프레드=gte.loc[4, "중앙"] - gte.loc[0, "중앙"],
                                TEST최상위중앙=gte.loc[4, "중앙"],
                                TEST최상위승률=gte.loc[4, "승률"],
                                유지율=(gte.loc[4, "중앙"]-gte.loc[0, "중앙"]) /
                                       max(gtr.loc[4, "중앙"]-gtr.loc[0, "중앙"], 1e-9) * 100))
    if summary:
        print("\n" + "#" * 100)
        print("최종 요약 — 유지율 = TEST스프레드 / TRAIN스프레드 (100%면 오버핏 없음)")
        print("#" * 100)
        print(pd.DataFrame(summary).round(1).to_string(index=False))


if __name__ == "__main__":
    main()
