# -*- coding: utf-8 -*-
"""
대조군 — 펀더멘털 조건이 종목을 고르는가, 사는 횟수만 줄이는가

지금까지 A·B·R6는 서로 간의 순위만 매겼을 뿐, "규칙이 무작위보다 나은가"를
잰 적이 없다. 오늘 밝혀진 세 가지(좋은 MDD의 실체는 현금 / 종목수는 자유도
없음 / 청산이 선정보다 성과를 좌우)는 전부 "무엇을 사느냐"가 아니라
"얼마나 자주 사느냐" 쪽 이야기다. 그렇다면 펀더멘털 조건이 단지 후보를
3.8개로 줄여 현금을 남기는 장치일 가능성이 있다.

모든 것을 고정하고 "그 주에 어떤 종목을 슬롯에 넣는가"만 바꾼다.

  실제      규칙 그대로
  대조군0   base 게이트(RS·유동성·시총)만. 펀더멘털 제거, RS 내림차순 상위 12
  대조군1   base 풀에서 무작위 12종
  대조군2   base 풀에서 무작위 n_t종 (n_t = 그 주 실제 규칙의 후보 수)  ← 핵심

대조군2가 핵심인 이유: 후보 수를 매칭해야 노출·타이밍 프로파일이 실제 규칙과
같아진다. 그래야 "현금 덕분"이라는 설명이 양쪽에 동일하게 걸리고, 남는 차이가
오직 종목 선택이 된다. 대조군1처럼 항상 12종을 채우면 노출이 65% vs 95%로
벌어져 비교 자체가 성립하지 않는다.

생존편향은 대조군에도 똑같이 걸리므로 상쇄된다 — 절대 수치는 여전히 못 믿지만
"규칙이 무작위보다 나은가"는 오염된 데이터로도 정직하게 답할 수 있다.
"""
import os, warnings
import numpy as np, pandas as pd
import leaders_boost as B, leaders_sim2 as L2

warnings.filterwarnings("ignore")
pd.set_option("display.width", 250)
BASE = os.path.dirname(os.path.abspath(__file__))
START, END, FEE = "2019-01-01", "2026-08-03", 0.001
TRAIL, MAXPOS, SEEDS = 0.20, 12, 100

# (full = 규칙 전체, base = 가격·유동성·시총 게이트만 — 펀더멘털을 걷어낸 것)
RULES = {
    "A": dict(
        full=lambda M, i: ((M["b_any"].iloc[i] == 1) & (M["per"].iloc[i] > 0) &
                           (M["per"].iloc[i] < 20) & (M["rs_13w"].iloc[i] > 1.5) &
                           (M["adv_20d"].iloc[i] >= 1e6)),
        base=lambda M, i: ((M["rs_13w"].iloc[i] > 1.5) & (M["adv_20d"].iloc[i] >= 1e6)),
        over="이익폭증 · 0<PER<20"),
    "B": dict(
        full=lambda M, i: (((M["op_turn"].iloc[i] == 1) | (M["b_any"].iloc[i] == 1)) &
                           (M["rs_13w"].iloc[i] > 1.7) & (M["adv_20d"].iloc[i] >= 1e6)),
        base=lambda M, i: ((M["rs_13w"].iloc[i] > 1.7) & (M["adv_20d"].iloc[i] >= 1e6)),
        over="흑자전환 OR 이익폭증"),
    "R6": dict(
        full=lambda M, i: ((M["rs_13w"].iloc[i] > 1.5) & (M["opm"].iloc[i] > 0) &
                           ((M["op_turn"].iloc[i] == 1) | (M["b_any"].iloc[i] == 1)) &
                           (M["marcap"].iloc[i] >= 2e9) & (M["adv_20d"].iloc[i] >= 5e6)),
        base=lambda M, i: ((M["rs_13w"].iloc[i] > 1.5) & (M["marcap"].iloc[i] >= 2e9) &
                           (M["adv_20d"].iloc[i] >= 5e6)),
        over="OPM>0 · (흑자전환 OR 이익폭증)"),
}


def precompute(P, M, cond):
    """주차별 통과 종목을 RS 내림차순으로 미리 뽑아둔다.

    시드 100회를 돌리려면 매 런마다 pandas 불리언 연산을 반복할 수 없다.
    한 번만 계산해두면 이후 시뮬은 리스트 조회로 끝난다.
    """
    rs, out = M["rs_13w"], []
    for i in range(len(P)):
        ok = cond(M, i).fillna(False) & P.iloc[i].notna()
        r = rs.iloc[i]
        out.append(sorted(ok[ok].index,
                          key=lambda s: -(r.get(s, -999) if r.get(s, -999) == r.get(s, -999) else -999)))
    return out


def run(P, cand, entry_ok, trail=TRAIL, maxpos=MAXPOS, start=START, end=END):
    """cand[i] = 그 주차의 후보(순서 있음). 앞에서부터 빈 슬롯만큼 채운다."""
    idx = P.index
    i0 = int(np.searchsorted(idx, pd.Timestamp(start)))
    iN = min(len(idx), int(np.searchsorted(idx, pd.Timestamp(end))) + 1)
    unit = 1.0 / maxpos
    cash, pos, eq, dates, trades, expo = 1.0, {}, [], [], [], []

    for i in range(i0, iN):
        px = P.iloc[i]
        val = sum(o["sh"] * px.get(s, np.nan) for s, o in pos.items()
                  if px.get(s, np.nan) == px.get(s, np.nan))
        val = val if val == val else 0.0
        V = cash + val
        if V <= 0:
            break
        expo.append(val / V)

        for s in list(pos):
            p = px.get(s, np.nan)
            if p != p:
                continue
            o = pos[s]
            o["peak"] = max(o["peak"], p)
            if p <= o["peak"] * (1 - trail):
                cash += o["sh"] * p * (1 - FEE)
                trades.append((p / o["avg"] - 1) * 100)
                del pos[s]

        if entry_ok[i] and len(pos) < maxpos:
            for s in [x for x in cand[i] if x not in pos][:maxpos - len(pos)]:
                amt = min(unit * V, cash)
                if amt < 1e-6:
                    break
                p = px[s]
                pos[s] = dict(sh=amt / p * (1 - FEE), avg=p, peak=p)
                cash -= amt
        eq.append(V); dates.append(idx[i])

    E = pd.Series(eq, index=dates)
    y = (E.index[-1] - E.index[0]).days / 365.25
    cagr = ((E.iloc[-1] / E.iloc[0]) ** (1 / y) - 1) * 100
    mdd = (E / E.cummax() - 1).min() * 100
    T = np.array(trades)
    return dict(mult=E.iloc[-1] / E.iloc[0], CAGR=cagr, MDD=mdd,
                recov=cagr / abs(mdd) if mdd else np.nan, n=len(T),
                win=(T > 0).mean() * 100 if len(T) else np.nan,
                expo=np.mean(expo) * 100)


def shuffled(pool, rng, k=None):
    """base 풀을 섞어 그 주차 후보로 쓴다. k가 주어지면 그 수만큼만."""
    out = []
    for i, p in enumerate(pool):
        if not p:
            out.append([]); continue
        q = list(p)
        rng.shuffle(q)
        out.append(q if k is None else q[:k[i]])
    return out


def pct(dist, v):
    """분포 안에서 v가 몇 퍼센타일인가 (높을수록 좋음 기준)"""
    d = np.asarray(dist)
    return (d < v).mean() * 100


def main():
    d = B.build(); d["as_of"] = pd.to_datetime(d.as_of)
    P, M = B.matrices(d)
    S = L2.spy().reindex(P.index, method="nearest")
    mon = set(pd.Series(P.index, index=P.index)
              .groupby(P.index.to_period("M")).max().values)
    OPS = (("월/주", np.array([t in mon for t in P.index])),
           ("주/주", np.ones(len(P), bool)))
    print(f"{START}~{END} · 손절 −{int(TRAIL*100)}% · {MAXPOS}종 · 시드 {SEEDS}개", flush=True)

    rows, dists = [], {}
    for k, R in RULES.items():
        cf = precompute(P, M, R["full"])
        cb = precompute(P, M, R["base"])
        nt = [len(x) for x in cf]
        print(f"\n[{k}] 펀더멘털 조건 = {R['over']}", flush=True)
        print(f"  후보 수  실제 평균 {np.mean(nt):.1f}개 · base 풀 평균 {np.mean([len(x) for x in cb]):.1f}개",
              flush=True)

        for tag, ent in OPS:
            act = run(P, cf, ent)
            c0 = run(P, cb, ent)                      # 대조군0 — RS 내림차순 상위 12
            rows += [dict(규칙=k, 운용=tag, 구분="실제", **{m: act[m] for m in
                          ("mult", "CAGR", "MDD", "recov", "expo", "n", "win")}),
                     dict(규칙=k, 운용=tag, 구분="대조0_RS만", **{m: c0[m] for m in
                          ("mult", "CAGR", "MDD", "recov", "expo", "n", "win")})]

            for lab, kk in (("대조1_무작위12", None), ("대조2_수매칭", nt)):
                res = []
                for sd in range(SEEDS):
                    rng = np.random.default_rng(sd)
                    res.append(run(P, shuffled(cb, rng, kk), ent))
                Rd = pd.DataFrame(res)
                dists[(k, tag, lab)] = Rd
                rows.append(dict(규칙=k, 운용=tag, 구분=lab,
                                 mult=Rd.mult.median(), CAGR=Rd.CAGR.median(),
                                 MDD=Rd.MDD.median(), recov=Rd.recov.median(),
                                 expo=Rd.expo.median(), n=Rd.n.median(), win=Rd.win.median()))
                print(f"  {tag} {lab:12s} 배수 중앙 {Rd.mult.median():5.2f} "
                      f"[p10 {Rd.mult.quantile(.1):5.2f} · p90 {Rd.mult.quantile(.9):5.2f}] "
                      f"회복 중앙 {Rd.recov.median():.2f} │ 실제 배수 {act['mult']:5.2f} "
                      f"= {pct(Rd.mult, act['mult']):.0f}%ile · "
                      f"회복 {act['recov']:.2f} = {pct(Rd.recov, act['recov']):.0f}%ile", flush=True)

    T = pd.DataFrame(rows).round(2)
    T.to_csv(os.path.join(BASE, "results", "control.csv"), index=False, encoding="utf-8-sig")
    print("\n" + "=" * 130)
    print("실제 vs 대조군 — 중앙값 기준")
    print("=" * 130)
    print(T.to_string(index=False))

    print("\n" + "=" * 130)
    print("퍼센타일 판정 — 실제 규칙이 무작위 분포의 어디에 앉는가")
    print("=" * 130)
    pr = []
    for (k, tag, lab), Rd in dists.items():
        a = T[(T.규칙 == k) & (T.운용 == tag) & (T.구분 == "실제")].iloc[0]
        pr.append(dict(규칙=k, 운용=tag, 대조군=lab,
                       실제배수=a["mult"], 배수ile=round(pct(Rd.mult, a["mult"])),
                       실제회복=a["recov"], 회복ile=round(pct(Rd.recov, a["recov"])),
                       실제MDD=a["MDD"], MDDile=round(pct(-Rd.MDD, -a["MDD"])),
                       실제노출=a["expo"], 대조노출=round(Rd.expo.median(), 1)))
    print(pd.DataFrame(pr).to_string(index=False))
    sp = S.loc[START:END]
    y = (sp.index[-1] - sp.index[0]).days / 365.25
    print(f"\n[SPY] 배수 {sp.iloc[-1]/sp.iloc[0]:.2f} · "
          f"CAGR {((sp.iloc[-1]/sp.iloc[0])**(1/y)-1)*100:.1f}")


if __name__ == "__main__":
    main()
