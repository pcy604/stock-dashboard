# -*- coding: utf-8 -*-
"""
궤적(trajectory) 팩터 — 값이 아니라 '경로'를 잰다

지금까지는 전부 시점 값(십분위·임계·단일분기 변화)만 봤다. 여기서는 연속된
분기의 흐름 자체를 팩터로 만든다.

  · 흑자전환 이후 경과 분기와, 그 뒤 영업이익이 연속 증가한 분기 수
  · OPM이 하락하다 저점을 찍고 연속 상승으로 돌아선 궤적
  · YoY 증가율이 연속으로 커지는(가속이 지속되는) 궤적
  · 흑자전환 + 거래대금 증가 (기관 자금 유입 대리지표)

TRAIN 2018~2021 / TEST 2022~ 분리, 거래 가능 영역에서만 평가.
"""
import os, sqlite3, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
pd.set_option("display.width", 250, "display.max_columns", 40)
BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "market.db")
CUT, TRAIN_END, MIN_N = 1.50, "2021-12-31", 150


def streak_up(s):
    """직전 대비 증가가 몇 분기 연속인가 (증가 아니면 0으로 리셋)."""
    up = (s.diff() > 0).astype(int)
    grp = (up == 0).cumsum()
    return up.groupby(grp).cumsum()


def load():
    c = sqlite3.connect(DB)
    d = pd.read_sql("SELECT as_of,sym,close,marcap,adv_20d,period_end,"
                    "op_income,net_income,revenue,opm,rs_13w,psr,vol_x_20w "
                    "FROM factor_weekly WHERE factor_ver='v1'", c)
    c.close()
    d["as_of"] = pd.to_datetime(d.as_of)

    # ── 분기 단위 궤적 ──
    q = (d.dropna(subset=["period_end"]).sort_values("as_of")
           .drop_duplicates(["sym", "period_end"]).sort_values(["sym", "period_end"])
           .reset_index(drop=True))
    g = q.groupby("sym")
    prev_op = g.op_income.shift(1)

    # 흑자전환: 직전 적자 → 이번 흑자
    q["turn"] = ((prev_op <= 0) & (q.op_income > 0)).astype(int)
    # 흑자전환 이후 경과 분기 (전환 분기 = 0). 다시 적자로 가면 무효(NaN)
    grp = q.groupby("sym").turn.cumsum()
    age = q.groupby(["sym", grp]).cumcount()
    q["turn_age"] = np.where(grp > 0, age, np.nan)
    q.loc[q.op_income <= 0, "turn_age"] = np.nan

    # 영업이익·OPM·매출 연속 증가 분기 수
    q["opi_up"] = g.op_income.transform(streak_up)
    q["opm_up"] = g.opm.transform(streak_up)
    q["rev_up"] = g.revenue.transform(streak_up)

    # OPM 턴어라운드: 직전 2분기 하락 후 이번에 상승
    dn2 = (g.opm.diff().shift(1) < 0) & (g.opm.diff().shift(2) < 0)
    q["opm_trough"] = (dn2 & (g.opm.diff() > 0)).astype(int)

    # YoY 증가율의 연속 가속 (증가율이 계속 커지는가)
    p4 = g.op_income.shift(4)
    yoy = pd.Series(np.where(p4 > 0, (q.op_income / p4 - 1) * 100, np.nan), index=q.index)
    q["opi_yoy"] = yoy
    q["opi_acc_up"] = yoy.groupby(q.sym).transform(streak_up)

    keep = ["sym", "period_end", "turn", "turn_age", "opi_up", "opm_up", "rev_up",
            "opm_trough", "opi_yoy", "opi_acc_up"]
    d = d.merge(q[keep], on=["sym", "period_end"], how="left")

    px = d.pivot(index="as_of", columns="sym", values="close").sort_index()
    fwd = (px.shift(-52) / px - 1).stack().rename("fwd").reset_index()
    d = d.merge(fwd, on=["as_of", "sym"], how="left").dropna(subset=["fwd"])
    bad = set(d.groupby("sym").fwd.max().pipe(lambda s: s[s > 20]).index)
    d = d[~d.sym.isin(bad)]
    d = d[(d.marcap >= 2e9) & (d.adv_20d >= 5e6) & (d.close >= 5)].copy()
    d["leader"] = (d.fwd >= CUT).astype(int)
    return d.replace([np.inf, -np.inf], np.nan)


def show(title, tr, te, br_tr, br_te, cases):
    print("\n" + "=" * 104); print(title); print("=" * 104)
    print(f"{'조건':40s}{'TR관측':>8s}{'TR리프트':>9s}{'TR수익':>8s}"
          f"{'TE관측':>8s}{'TE리프트':>9s}{'TE수익':>8s}{'TE승률':>8s}")
    for lab, fn in cases:
        a, b = tr[fn(tr)], te[fn(te)]
        if len(a) < MIN_N or len(b) < MIN_N:
            print(f"{lab:40s}{len(a):>8,}{'표본부족':>9s}{'':>8s}{len(b):>8,}")
            continue
        print(f"{lab:40s}{len(a):>8,}{a.leader.mean()/br_tr:>9.2f}{a.fwd.median()*100:>7.1f}%"
              f"{len(b):>8,}{b.leader.mean()/br_te:>9.2f}{b.fwd.median()*100:>7.1f}%"
              f"{(b.fwd>0).mean()*100:>7.1f}%")


def main():
    d = load()
    tr, te = d[d.as_of <= TRAIN_END], d[d.as_of > TRAIN_END]
    br_tr, br_te = tr.leader.mean(), te.leader.mean()
    print(f"거래가능 관측 {len(d):,} · 종목 {d.sym.nunique()}")
    print(f"TRAIN {len(tr):,} (주도주 {br_tr*100:.2f}%) · TEST {len(te):,} ({br_te*100:.2f}%)")

    show("① 흑자전환 이후 경과 — 언제가 가장 좋은가", tr, te, br_tr, br_te,
         [("흑자전환 당분기 (age=0)", lambda x: x.turn_age == 0),
          ("전환 후 1분기", lambda x: x.turn_age == 1),
          ("전환 후 2분기", lambda x: x.turn_age == 2),
          ("전환 후 3분기", lambda x: x.turn_age == 3),
          ("전환 후 4~7분기", lambda x: x.turn_age.between(4, 7)),
          ("전환 후 8분기+", lambda x: x.turn_age >= 8)])

    show("② 흑자전환 후 + 이익이 계속 늘고 있는가 (네 가설의 핵심)", tr, te, br_tr, br_te,
         [("전환 후 0~3분기 · 영업익 증가 1분기+", lambda x: (x.turn_age <= 3) & (x.opi_up >= 1)),
          ("전환 후 0~3분기 · 영업익 증가 2분기+", lambda x: (x.turn_age <= 3) & (x.opi_up >= 2)),
          ("전환 후 0~3분기 · 영업익 증가 3분기+", lambda x: (x.turn_age <= 3) & (x.opi_up >= 3)),
          ("전환 후 0~7분기 · 영업익 증가 2분기+", lambda x: (x.turn_age <= 7) & (x.opi_up >= 2)),
          ("전환 무관 · 영업익 증가 3분기+", lambda x: x.opi_up >= 3),
          ("전환 무관 · 영업익 증가 4분기+", lambda x: x.opi_up >= 4)])

    show("③ OPM 턴어라운드 — 하락하다 저점 찍고 상승 전환", tr, te, br_tr, br_te,
         [("OPM 저점 전환 당분기", lambda x: x.opm_trough == 1),
          ("OPM 연속 상승 2분기+", lambda x: x.opm_up >= 2),
          ("OPM 연속 상승 3분기+", lambda x: x.opm_up >= 3),
          ("OPM 연속 상승 4분기+", lambda x: x.opm_up >= 4),
          ("OPM 저점전환 + 흑자전환 후 0~3분기",
           lambda x: (x.opm_trough == 1) & (x.turn_age <= 3))])

    show("④ 증가율이 연속으로 커지는가 (가속 지속)", tr, te, br_tr, br_te,
         [("영업익 YoY 가속 2분기 연속", lambda x: x.opi_acc_up >= 2),
          ("영업익 YoY 가속 3분기 연속", lambda x: x.opi_acc_up >= 3),
          ("매출 연속증가 3분기+ · 영업익 연속증가 2분기+",
           lambda x: (x.rev_up >= 3) & (x.opi_up >= 2)),
          ("영업익·OPM 동시 2분기 연속 증가", lambda x: (x.opi_up >= 2) & (x.opm_up >= 2))])

    show("⑤ 자금 유입 대리지표와 결합 (거래대금·강세)", tr, te, br_tr, br_te,
         [("전환 후 0~3분기 · 거래량 1.2배+", lambda x: (x.turn_age <= 3) & (x.vol_x_20w > 1.2)),
          ("전환 후 0~3분기 · RS13>1.2", lambda x: (x.turn_age <= 3) & (x.rs_13w > 1.2)),
          ("영업익 증가 2분기+ · RS13>1.2", lambda x: (x.opi_up >= 2) & (x.rs_13w > 1.2)),
          ("영업익 증가 2분기+ · RS13>1.2 · PSR<3",
           lambda x: (x.opi_up >= 2) & (x.rs_13w > 1.2) & (x.psr < 3))])


if __name__ == "__main__":
    main()
