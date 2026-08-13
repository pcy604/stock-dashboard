# -*- coding: utf-8 -*-
"""
규칙 자동 탐색 — 사람이 조건을 고르지 않는다

"가장 많이 오른 종목이 어떤 프레임에 걸리는가"를 데이터가 찾게 한다.
단 승자만 보면 이 프로젝트가 이미 당한 함정(25종 표본 특징이 유니버스에서 전멸)에
그대로 빠지므로, 모든 조건을 승자·패자가 함께 있는 유니버스에서 평가한다.

  · 원자 조건 자동 생성: 모든 수치 팩터 × 십분위 임계 × 방향(초과/미만)
  · 탐욕적 결합: 조건을 하나씩 붙이며 리프트가 오르는 동안만 확장 (최대 3개)
  · TRAIN(2018-06~2021-12)에서만 탐색 → TEST(2022~)에서 그대로 적용해 확인
  · 거래 가능 영역(시총 $2B+ · 거래대금 $5M+ · 주가 $5+)에서만 평가

리프트 = 조건 통과분의 주도주율 ÷ 유니버스 주도주율.
포착률 = 유니버스 전체 주도주 중 이 조건이 잡은 비율(재현율).
"""
import os, sqlite3, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
pd.set_option("display.width", 250, "display.max_columns", 40)
BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "market.db")
CUT = 1.50
TRAIN_END = "2021-12-31"
MIN_N, MAX_DEPTH = 400, 3

FACTORS = ["rs_4w", "rs_13w", "rs_26w", "ret_4w", "ret_13w", "ret_ytd", "dist_52w",
           "low_52w_dist", "mdd_52w", "days_since_hi52", "above_ma20_52w", "vol_x_20w",
           "rev_yoy", "rev_qoq", "gpm", "gpm_qoq", "opm", "opm_qoq", "npm", "npm_qoq",
           "op_pos_streak", "earn_react_w0", "psr", "per", "marcap", "adv_20d"]
BINARY = ["op_turn", "gpm_up2", "opm_up2", "npm_up2", "close_gt_ma20", "ma10_gt_ma20",
          "hi_5w", "hi_10w", "hi_20w", "hi_52w"]


def load():
    c = sqlite3.connect(DB)
    d = pd.read_sql(f"SELECT as_of,sym,close,{','.join(FACTORS + BINARY)} "
                    "FROM factor_weekly WHERE factor_ver='v1'", c)
    c.close()
    d["as_of"] = pd.to_datetime(d.as_of)
    px = d.pivot(index="as_of", columns="sym", values="close").sort_index()
    fwd = (px.shift(-52) / px - 1).stack().rename("fwd").reset_index()
    d = d.merge(fwd, on=["as_of", "sym"], how="left").dropna(subset=["fwd"])
    bad = set(d.groupby("sym").fwd.max().pipe(lambda s: s[s > 20]).index)
    d = d[~d.sym.isin(bad)]
    d = d[(d.marcap >= 2e9) & (d.adv_20d >= 5e6) & (d.close >= 5)].copy()   # 거래 가능 영역
    d["leader"] = (d.fwd >= CUT).astype(int)
    return d.replace([np.inf, -np.inf], np.nan)


def atoms(tr):
    """원자 조건 자동 생성 — 사람이 고르지 않는다."""
    out = []
    for f in FACTORS:
        s = tr[f].dropna()
        if len(s) < MIN_N * 5:
            continue
        for q in [.1, .2, .3, .5, .7, .8, .9]:
            t = s.quantile(q)
            if not np.isfinite(t):
                continue
            out.append((f"{f}>{t:.4g}", lambda d, f=f, t=t: d[f] > t))
            out.append((f"{f}<{t:.4g}", lambda d, f=f, t=t: d[f] < t))
    for f in BINARY:
        if tr[f].notna().sum() >= MIN_N * 5:
            out.append((f"{f}=1", lambda d, f=f: d[f] == 1))
            out.append((f"{f}=0", lambda d, f=f: d[f] == 0))
    return out


def ev(d, mask, br, n_lead_all):
    s = d[mask]
    if len(s) < MIN_N:
        return None
    return dict(n=len(s), lift=s.leader.mean() / br, med=s.fwd.median() * 100,
                win=(s.fwd > 0).mean() * 100, recall=s.leader.sum() / n_lead_all * 100)


def main():
    d = load()
    tr, te = d[d.as_of <= TRAIN_END], d[d.as_of > TRAIN_END]
    br_tr, br_te = tr.leader.mean(), te.leader.mean()
    nl_tr, nl_te = tr.leader.sum(), te.leader.sum()
    print(f"거래가능 관측 {len(d):,} · 종목 {d.sym.nunique()}")
    print(f"TRAIN {tr.as_of.min():%Y-%m}~{tr.as_of.max():%Y-%m} 관측 {len(tr):,} · "
          f"주도주 {nl_tr:,} ({br_tr*100:.2f}%)")
    print(f"TEST  {te.as_of.min():%Y-%m}~{te.as_of.max():%Y-%m} 관측 {len(te):,} · "
          f"주도주 {nl_te:,} ({br_te*100:.2f}%)\n")

    A = atoms(tr)
    print(f"자동 생성된 원자 조건 {len(A)}개 — TRAIN에서 단독 성능 평가\n")

    singles = []
    for name, fn in A:
        r = ev(tr, fn(tr), br_tr, nl_tr)
        if r and r["lift"] >= 1.2:
            singles.append((name, fn, r))
    singles.sort(key=lambda x: -x[2]["lift"])
    print("=" * 112)
    print("① 단독 조건 상위 15 (TRAIN)")
    print("=" * 112)
    print(f"{'조건':28s}{'관측':>8s}{'리프트':>8s}{'수익중앙':>10s}{'승률':>8s}{'포착률':>8s}")
    for name, _, r in singles[:15]:
        print(f"{name:28s}{r['n']:>8,}{r['lift']:>8.2f}{r['med']:>9.1f}%{r['win']:>7.1f}%{r['recall']:>7.1f}%")

    # ── 탐욕적 결합 ──
    print("\n" + "=" * 112)
    print(f"② 조건 결합 — 리프트가 오르는 동안만 확장 (최대 {MAX_DEPTH}개)")
    print("=" * 112)
    best = []
    for seed_name, seed_fn, seed_r in singles[:12]:
        names, fns, cur = [seed_name], [seed_fn], seed_r
        for _ in range(MAX_DEPTH - 1):
            cand = None
            for name, fn, _ in singles:
                if name in names or name.split(">")[0].split("<")[0].split("=")[0] in \
                   [n.split(">")[0].split("<")[0].split("=")[0] for n in names]:
                    continue
                m = np.logical_and.reduce([f(tr) for f in fns + [fn]])
                r = ev(tr, m, br_tr, nl_tr)
                if r and r["lift"] > cur["lift"] * 1.05 and (cand is None or r["lift"] > cand[2]["lift"]):
                    cand = (name, fn, r)
            if cand is None:
                break
            names.append(cand[0]); fns.append(cand[1]); cur = cand[2]
        best.append((names, fns, cur))
    seen, uniq = set(), []
    for names, fns, r in sorted(best, key=lambda x: -x[2]["lift"]):
        k = tuple(sorted(names))
        if k in seen:
            continue
        seen.add(k); uniq.append((names, fns, r))

    print(f"{'규칙':52s}{'관측':>7s}{'리프트':>7s}{'수익중앙':>9s}{'승률':>7s}{'포착':>7s}")
    for names, fns, r in uniq[:10]:
        lab = " & ".join(names)[:50]
        print(f"{lab:52s}{r['n']:>7,}{r['lift']:>7.2f}{r['med']:>8.1f}%{r['win']:>6.1f}%{r['recall']:>6.1f}%")

    # ── TEST 적용 ──
    print("\n" + "=" * 112)
    print("③ 같은 규칙을 TEST 기간에 그대로 적용 — 재현되는가")
    print("=" * 112)
    print(f"{'규칙':52s}{'TRAIN리프트':>11s}{'TEST리프트':>11s}{'TEST수익중앙':>13s}{'TEST승률':>10s}")
    for names, fns, r in uniq[:10]:
        m = np.logical_and.reduce([f(te) for f in fns])
        t = ev(te, m, br_te, nl_te)
        lab = " & ".join(names)[:50]
        if t is None:
            print(f"{lab:52s}{r['lift']:>11.2f}{'표본부족':>11s}")
        else:
            print(f"{lab:52s}{r['lift']:>11.2f}{t['lift']:>11.2f}{t['med']:>12.1f}%{t['win']:>9.1f}%")


if __name__ == "__main__":
    main()
