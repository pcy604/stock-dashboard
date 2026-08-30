# -*- coding: utf-8 -*-
"""
불타기 재설계 — 무엇을 트리거로, 손절은 어떻게 나눌까

08-03에 피라미딩은 TSR 694%→535%로 불리 판정을 받았다. 그런데 그때 트리거는
`hi_52w`(52주 신고가)였고, 신고가 근접은 유니버스 검증에서 네 번 기각된
조건(리프트 0.4~0.7)이다. **기각된 신호로 비중을 늘리고 있었다.**

두 번째 의심: 불타기와 트레일링 손절은 구조적으로 상충한다.
  100에 1차 → 150에 2차 → 평단 125
  고점 150에서 −20% = 120 청산 → 평단 대비 −4%
  1차만 들고 있었으면 +20%
즉 **불타기가 승리를 무승부로 바꾼다.** 이게 진짜 원인이면 트리거를 바꿔도
소용없고 손절 구조를 나눠야 한다.

세 축을 교차한다.
  트리거   없음 / 신고가 / 이익재확인 / 생존8주 / 수익+25%
  손절     공통−20 / 분리(코어−35·추가−20) / 확대(불타기 후 전체−25)
  사이징   균형(1차60+2차40=슬롯100%) / 확대(1차100+2차50=슬롯150%)

사이징 '확대'가 사용자가 말한 비중플레이다 — 확인된 종목에만 슬롯을 넘겨 담는다.
"""
import os, warnings
import numpy as np, pandas as pd
import leaders_boost as B, leaders_sim2 as L2

warnings.filterwarnings("ignore")
pd.set_option("display.width", 260)
BASE = os.path.dirname(os.path.abspath(__file__))
START, END, FEE = "2019-01-01", "2026-08-03", 0.001
TRAIL, MAXPOS = 0.20, 12

RULES = {
    "A": lambda M, i: ((M["b_any"].iloc[i] == 1) & (M["per"].iloc[i] > 0) &
                       (M["per"].iloc[i] < 20) & (M["rs_13w"].iloc[i] > 1.5) &
                       (M["adv_20d"].iloc[i] >= 1e6)),
    "R6": lambda M, i: ((M["rs_13w"].iloc[i] > 1.5) & (M["opm"].iloc[i] > 0) &
                        ((M["op_turn"].iloc[i] == 1) | (M["b_any"].iloc[i] == 1)) &
                        (M["marcap"].iloc[i] >= 2e9) & (M["adv_20d"].iloc[i] >= 5e6)),
}
SIZING = {"균형": (0.60, 0.40), "확대": (1.00, 0.50)}
EXITS = ("공통-20", "분리35/20", "확대-25")
TRIGS = ("없음", "신고가", "이익재확인", "생존8주", "수익25")


def precompute(P, M, cond):
    rs, out = M["rs_13w"], []
    for i in range(len(P)):
        ok = cond(M, i).fillna(False) & P.iloc[i].notna()
        r = rs.iloc[i]
        out.append(sorted(ok[ok].index,
                          key=lambda s: -(r.get(s, -999) if r.get(s, -999) == r.get(s, -999) else -999)))
    return out


def run(P, M, cand, entry_ok, trig="없음", exit_mode="공통-20", sizing="균형"):
    w1, w2 = SIZING[sizing]
    idx = P.index
    i0 = int(np.searchsorted(idx, pd.Timestamp(START)))
    iN = min(len(idx), int(np.searchsorted(idx, pd.Timestamp(END))) + 1)
    unit = 1.0 / MAXPOS
    cash, pos, eq, dates, trades, expo, adds = 1.0, {}, [], [], [], [], 0
    HI, BA, AGE = M["hi_52w"], M["b_any"], M["boost_age"]

    for i in range(i0, iN):
        px = P.iloc[i]
        val = sum(sum(l["sh"] for l in o["lots"]) * px.get(s, np.nan)
                  for s, o in pos.items() if px.get(s, np.nan) == px.get(s, np.nan))
        val = val if val == val else 0.0
        V = cash + val
        if V <= 0:
            break
        expo.append(val / V)

        for s in list(pos):                       # 청산 — 로트별 트레일
            p = px.get(s, np.nan)
            if p != p:
                continue
            o = pos[s]
            o["peak"] = max(o["peak"], p)
            keep = []
            for l in o["lots"]:
                if p <= o["peak"] * (1 - l["trail"]):
                    cash += l["sh"] * p * (1 - FEE)
                    trades.append(dict(ret=(p / l["px"] - 1) * 100, wk=i - o["i0"],
                                       tier=l["tier"]))
                else:
                    keep.append(l)
            o["lots"] = keep
            if not keep:
                del pos[s]

        if trig != "없음":                          # 불타기
            for s, o in list(pos.items()):
                p = px.get(s, np.nan)
                if p != p or o["tier"] >= 2 or i <= o["i0"]:
                    continue
                if trig == "신고가":
                    go = HI.iloc[i].get(s, 0) == 1
                elif trig == "이익재확인":
                    go = (BA.iloc[i].get(s, 0) == 1 and AGE.iloc[i].get(s, 999) <= 1)
                elif trig == "생존8주":
                    go = (i - o["i0"]) >= 8
                else:                              # 수익25
                    go = p >= o["lots"][0]["px"] * 1.25
                if not go:
                    continue
                amt = min(unit * V * w2, cash)
                if amt < 1e-6:
                    continue
                tr = 0.25 if exit_mode == "확대-25" else TRAIL
                if exit_mode == "분리35/20":
                    for l in o["lots"]:
                        l["trail"] = 0.35          # 기존 물량을 코어로 승격
                if exit_mode == "확대-25":
                    for l in o["lots"]:
                        l["trail"] = 0.25
                o["lots"].append(dict(sh=amt / p * (1 - FEE), px=p, trail=tr, tier=2))
                o["tier"] = 2; cash -= amt; adds += 1

        if entry_ok[i] and len(pos) < MAXPOS:       # 신규 진입
            for s in [x for x in cand[i] if x not in pos][:MAXPOS - len(pos)]:
                amt = min(unit * V * w1, cash)
                if amt < 1e-6:
                    break
                p = px[s]
                pos[s] = dict(peak=p, i0=i, tier=1,
                              lots=[dict(sh=amt / p * (1 - FEE), px=p, trail=TRAIL, tier=1)])
                cash -= amt
        eq.append(V); dates.append(idx[i])

    E = pd.Series(eq, index=dates); T = pd.DataFrame(trades)
    y = (E.index[-1] - E.index[0]).days / 365.25
    cagr = ((E.iloc[-1] / E.iloc[0]) ** (1 / y) - 1) * 100
    mdd = (E / E.cummax() - 1).min() * 100
    t2 = T[T.tier == 2] if len(T) else T
    return dict(mult=E.iloc[-1] / E.iloc[0], CAGR=cagr, MDD=mdd,
                recov=cagr / abs(mdd) if mdd else np.nan, n=len(T), adds=adds,
                win=(T.ret > 0).mean() * 100 if len(T) else np.nan,
                win2=(t2.ret > 0).mean() * 100 if len(t2) else np.nan,
                ret2=t2.ret.mean() if len(t2) else np.nan,
                expo=np.mean(expo) * 100)


def main():
    d = B.build(); d["as_of"] = pd.to_datetime(d.as_of)
    P, M = B.matrices(d)
    S = L2.spy().reindex(P.index, method="nearest")
    mon = set(pd.Series(P.index, index=P.index)
              .groupby(P.index.to_period("M")).max().values)
    OPS = {"A": ("주/주", np.ones(len(P), bool)),
           "R6": ("월/주", np.array([t in mon for t in P.index]))}
    print(f"{START}~{END} · 손절 −{int(TRAIL*100)}% 기본 · {MAXPOS}종", flush=True)

    rows = []
    for k, cond in RULES.items():
        cand = precompute(P, M, cond)
        tag, ent = OPS[k]
        for sz in SIZING:
            for tg in TRIGS:
                for ex in (EXITS if tg != "없음" else ("공통-20",)):
                    r = run(P, M, cand, ent, tg, ex, sz)
                    rows.append(dict(규칙=k, 운용=tag, 사이징=sz, 트리거=tg, 손절=ex,
                                     자산배수=round(r["mult"], 2), CAGR=round(r["CAGR"], 1),
                                     MDD=round(r["MDD"], 1), 회복=round(r["recov"], 2),
                                     노출=round(r["expo"], 1), 거래=r["n"], 불타기=r["adds"],
                                     승률=round(r["win"], 1),
                                     추가분승률=round(r["win2"], 1) if r["win2"] == r["win2"] else None,
                                     추가분수익=round(r["ret2"], 1) if r["ret2"] == r["ret2"] else None))
                    print(f"  {k:2s} {sz} {tg:6s} {ex:9s} → {r['mult']:6.2f}배 "
                          f"MDD {r['MDD']:6.1f} 회복 {r['recov']:5.2f} 노출 {r['expo']:5.1f} "
                          f"불타기 {r['adds']:3d}건", flush=True)

    T = pd.DataFrame(rows)
    T.to_csv(os.path.join(BASE, "results", "pyramid.csv"), index=False, encoding="utf-8-sig")
    print("\n" + "=" * 150)
    print("불타기 트리거 × 손절 구조 × 사이징")
    print("=" * 150)
    for k in RULES:
        print(f"\n[{k}]")
        print(T[T.규칙 == k].drop(columns="규칙").to_string(index=False))
    sp = S.loc[START:END]
    y = (sp.index[-1] - sp.index[0]).days / 365.25
    print(f"\n[SPY] 배수 {sp.iloc[-1]/sp.iloc[0]:.2f} · CAGR {((sp.iloc[-1]/sp.iloc[0])**(1/y)-1)*100:.1f}")


if __name__ == "__main__":
    main()
