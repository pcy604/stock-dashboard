# -*- coding: utf-8 -*-
"""
백테스트 감사(audit) — 주차별 포트폴리오 상태와 매매를 전부 기록

leaders_boost.run()과 동일한 로직을 로깅 버전으로 재현한다.
CAGR·MDD가 어디서 나왔는지 사람이 직접 검증할 수 있게 만드는 것이 목적이다.

출력
  exports/audit_weekly.csv   주차별 NAV·현금·노출·보유종목·평가액
  exports/audit_trades.csv   거래별 진입·청산·수익률·보유주수·청산사유
  exports/audit_events.csv   주차별 매수/매도 이벤트

실행: python leaders_audit.py [전략키]
"""
import os, sys, sqlite3, warnings
import numpy as np, pandas as pd
import leaders_boost as B, leaders_sim2 as L2

warnings.filterwarnings("ignore")
pd.set_option("display.width", 240)
BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "exports")
END, TRAIL, FEE = "2026-08-03", 0.20, 0.001

STRATS = {
    # 회복배율 1위
    "s13": ("이익폭증 + PER<20 + RS>1.5 · 12종목", 12,
            lambda M, i: ((M["b_any"].iloc[i] == 1) & (M["per"].iloc[i] > 0) &
                          (M["per"].iloc[i] < 20) & (M["rs_13w"].iloc[i] > 1.5) &
                          (M["adv_20d"].iloc[i] >= 1e6))),
    # MDD -51.3% 사례
    "rs17": ("(흑자전환|이익폭증) + RS>1.7 · 8종목", 8,
             lambda M, i: ((((M["op_turn"].iloc[i] == 1) | (M["b_any"].iloc[i] == 1)) &
                            (M["rs_13w"].iloc[i] > 1.7) & (M["adv_20d"].iloc[i] >= 1e6)))),
}


def run_audit(key):
    label, maxpos, cond = STRATS[key]
    d = B.build(); d["as_of"] = pd.to_datetime(d.as_of)
    P, M = B.matrices(d)
    c = sqlite3.connect(os.path.join(BASE, "data", "market.db"))
    nm = dict(c.execute("SELECT DISTINCT sym,name FROM factor_weekly "
                        "WHERE factor_ver='v1'").fetchall())
    c.close()
    idx = P.index[P.index <= pd.Timestamp(END)]
    i0 = int(np.searchsorted(P.index, pd.Timestamp("2018-06-01")))
    unit = 1.0 / maxpos

    cash, pos = 1.0, {}
    wk_rows, ev_rows, trades = [], [], []

    for i in range(i0, len(idx)):
        dt = P.index[i]
        px = P.iloc[i]
        val = sum(o["sh"] * px.get(s, np.nan) for s, o in pos.items()
                  if px.get(s, np.nan) == px.get(s, np.nan))
        val = val if val == val else 0.0
        V = cash + val
        if V <= 0:
            break

        # ── 청산: 주봉 종가가 진입 후 고점 대비 −20% ──
        for s in list(pos):
            p = px.get(s, np.nan)
            if p != p:
                continue
            o = pos[s]
            o["peak"] = max(o["peak"], p)
            if p <= o["peak"] * (1 - TRAIL):
                proceeds = o["sh"] * p * (1 - FEE)
                cash += proceeds
                ret = (p / o["avg"] - 1) * 100
                trades.append(dict(종목=s, 이름=nm.get(s, s), 진입일=o["dt"].date(),
                                   진입가=round(o["avg"], 4), 청산일=dt.date(),
                                   청산가=round(p, 4), 수익률=round(ret, 2),
                                   보유주수=i - o["i0"], 고점가=round(o["peak"], 4),
                                   고점대비=round((p / o["peak"] - 1) * 100, 2),
                                   청산사유="고점 −20% 이탈"))
                ev_rows.append(dict(주차=dt.date(), 구분="매도", 종목=s,
                                    가격=round(p, 4), 수익률=round(ret, 2),
                                    비중=round(proceeds / V * 100, 2)))
                del pos[s]

        # ── 진입: 슬롯이 비면 조건 충족 종목을 RS 순으로 ──
        if len(pos) < maxpos:
            ok = cond(M, i)
            cand = [s for s in ok[ok.fillna(False)].index
                    if s not in pos and px.get(s, np.nan) == px.get(s, np.nan)]
            rs = M["rs_13w"].iloc[i]
            cand.sort(key=lambda s: -(rs.get(s, -999) if rs.get(s, -999) == rs.get(s, -999) else -999))
            for s in cand[:maxpos - len(pos)]:
                amt = min(unit * V, cash)
                if amt < 1e-6:
                    break
                p = px[s]
                sh = amt / p * (1 - FEE)
                pos[s] = dict(sh=sh, avg=p, peak=p, i0=i, dt=dt)
                cash -= amt
                ev_rows.append(dict(주차=dt.date(), 구분="매수", 종목=s,
                                    가격=round(p, 4), 수익률=None,
                                    비중=round(amt / V * 100, 2)))

        hold = {s: o["sh"] * px.get(s, np.nan) for s, o in pos.items()}
        hold = {s: v for s, v in hold.items() if v == v}
        wk_rows.append(dict(주차=dt.date(), NAV=round(V, 4), 현금=round(cash, 4),
                            현금비중=round(cash / V * 100, 1),
                            노출=round(sum(hold.values()) / V * 100, 1),
                            보유수=len(pos),
                            보유종목=" ".join(f"{s}:{v/V*100:.1f}%"
                                          for s, v in sorted(hold.items(), key=lambda x: -x[1]))))

    W = pd.DataFrame(wk_rows)
    W["고점NAV"] = W.NAV.cummax()
    W["낙폭%"] = ((W.NAV / W.고점NAV - 1) * 100).round(2)
    T = pd.DataFrame(trades)
    E = pd.DataFrame(ev_rows)

    os.makedirs(OUT, exist_ok=True)
    W.to_csv(os.path.join(OUT, f"audit_weekly_{key}.csv"), index=False, encoding="utf-8-sig")
    T.to_csv(os.path.join(OUT, f"audit_trades_{key}.csv"), index=False, encoding="utf-8-sig")
    E.to_csv(os.path.join(OUT, f"audit_events_{key}.csv"), index=False, encoding="utf-8-sig")

    yrs = (pd.Timestamp(W.주차.iloc[-1]) - pd.Timestamp(W.주차.iloc[0])).days / 365.25
    cagr = ((W.NAV.iloc[-1] / W.NAV.iloc[0]) ** (1 / yrs) - 1) * 100
    print(f"[{key}] {label}")
    print(f"  기간 {W.주차.iloc[0]} ~ {W.주차.iloc[-1]} ({yrs:.1f}년) · 주차 {len(W)}")
    print(f"  NAV {W.NAV.iloc[0]:.3f} → {W.NAV.iloc[-1]:.3f} · TSR {(W.NAV.iloc[-1]-1)*100:.0f}%"
          f" · CAGR {cagr:.1f}% · MDD {W['낙폭%'].min():.1f}%")
    print(f"  거래 {len(T)}건 · 승률 {(T.수익률>0).mean()*100:.1f}% · 평균노출 {W.노출.mean():.1f}%")
    lo = W.loc[W['낙폭%'].idxmin()]
    print(f"  최악 낙폭 주차 {lo.주차} · NAV {lo.NAV:.3f} · 보유 {lo.보유수}종 · 현금 {lo.현금비중}%")
    print(f"  → exports/audit_weekly_{key}.csv · audit_trades_{key}.csv · audit_events_{key}.csv")
    return W, T, E


if __name__ == "__main__":
    for k in (sys.argv[1:] or ["s13", "rs17"]):
        run_audit(k); print()
