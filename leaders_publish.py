# -*- coding: utf-8 -*-
"""
대시보드용 JSON 출력 — market.db는 gitignore라 클라우드에서 못 읽으므로
로컬에서 계산한 결과만 results/leaders_signal.json 으로 떨궈 커밋한다.
  python leaders_publish.py
"""
import json, os
from datetime import date
import pandas as pd
import leaders_boost as B

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "results", "leaders_signal.json")
LEDGER = os.path.join(BASE, "results", "leaders_paper.json")

BOOST = {"b_ophigh": "영업익 신고점", "b_nihigh": "순익 신고점",
         "b_opjump": "영업익 QoQ+50%", "b_opmjump": "OPM QoQ+3%p"}
BACKTEST = dict(
    period="2018-06 ~ 2026-08 · 미국 1,271종", cagr=32.8, mdd=-37.7, recover=0.87,
    spy_cagr=14.2, spy_mdd=-31.8, spy_recover=0.45,
    trades=136, winrate=43.4, hold_wk=20.7, med_ret=-5.9,
    wf_cagr="4/6", wf_recover="2/6",     # 구 규칙⑤는 4/6 · 3/6
    # 2026-08-08 규칙 전환. PSR<3(구 규칙⑤)은 CAGR 27.7 / MDD −23.9 / 회복 1.16 이었다.
    # MDD가 SPY(−31.8%)보다 나빠지는 것을 받아들이고 CAGR +5.1%p와 사각지대 해소를 택했다.
    prev_rule=dict(name="⑤ PSR<3", cagr=27.7, mdd=-23.9, recover=1.16,
                   why_changed="주도주 이력 종목 520개 중 90개(17%)가 8년간 PSR<3에 "
                               "한 번도 진입하지 않아 구조적 사각지대. NVDA는 신호 주차 "
                               "PSR 최소 10.5로 포착 불가."),
    rejected=["거래량 급증(어떤 임계도 무효)", "52주 신고가 근접(리프트 0.4)",
              "매출 성장률(상방을 깎음)", "OPM QoQ 개선(워크포워드 2~3/6)",
              "피라미딩(가격·이익 트리거 모두 회복배율 악화)",
              "PSR 컷 완화(<10 시 MDD −41.0%)·고PSR 슬리브 분리(수익만 희석)"])


def main():
    d = B.build()
    d["as_of"] = pd.to_datetime(d.as_of)
    wk = d.as_of.max()
    w = d[d.as_of == wk]
    base = w[(w.close >= 5) & (w.adv_20d >= 5e6) & (w.marcap >= 2e9)]
    # 규칙⑥ (2026-08-08~): PSR<3 → OPM>0. PSR은 표시용 참고지표로만 남는다.
    sel = base[(base.rs_13w > 1.5) & (base.opm > 0) &
               ((base.op_turn == 1) | (base.b_any == 1))].sort_values("rs_13w", ascending=False)

    import sqlite3
    c = sqlite3.connect(os.path.join(BASE, "data", "market.db"))
    nm = dict(c.execute("SELECT sym,name FROM factor_weekly WHERE as_of=? AND factor_ver='v1'",
                        (str(wk.date()),)).fetchall())
    c.close()

    def row(r):
        trig = (["흑자전환"] if r.op_turn == 1 else []) + [v for k, v in BOOST.items() if r[k] == 1]
        return dict(sym=r.sym, name=nm.get(r.sym, r.sym), close=round(float(r.close), 2),
                    rs_13w=round(float(r.rs_13w), 2), rs_26w=None,
                    psr=round(float(r.psr), 2),
                    per=(None if pd.isna(r.per) else round(float(r.per), 1)),
                    dist_52w=round(float(r.dist_52w), 1),
                    opm=(None if pd.isna(r.opm) else round(float(r.opm), 1)),
                    opm_qoq=(None if pd.isna(r.opm_qoq) else round(float(r.opm_qoq), 1)),
                    marcap_b=round(float(r.marcap) / 1e9, 1),
                    adv_m=round(float(r.adv_20d) / 1e6, 0), triggers=trig)

    funnel = [("유니버스 (시총$2B+ · 거래대금$5M+)", int(len(base))),
              ("+ RS13 > 1.5", int((base.rs_13w > 1.5).sum())),
              ("+ OPM > 0", int(((base.rs_13w > 1.5) & (base.opm > 0)).sum())),
              ("+ 흑자전환 OR 이익폭증", int(len(sel))),
              ("(참고) 위에 PSR<3까지 걸면", int(((base.rs_13w > 1.5) & (base.opm > 0) &
                                            (base.psr < 3) &
                                            ((base.op_turn == 1) | (base.b_any == 1))).sum()))]

    paper = None
    if os.path.exists(LEDGER):
        L = json.load(open(LEDGER, encoding="utf-8"))
        T = L.get("trades", [])
        cl = [t for t in T if t["status"] == "closed"]
        op = [t for t in T if t["status"] == "open"]
        paper = dict(created=L.get("created"), updated=L.get("updated"),
                     n_total=len(T), n_open=len(op), n_closed=len(cl),
                     open=[dict(sym=t["sym"], log_date=t["log_date"], entry=t["entry_px"],
                                peak=t["peak_px"], rs=t.get("rs_13w"), psr=t.get("psr"),
                                triggers=t.get("triggers", [])) for t in op],
                     closed=[dict(sym=t["sym"], entry=t["entry_px"], exit=t["exit_px"],
                                  ret=t["ret_pct"], hold_wk=t["hold_wk"],
                                  exit_date=t["exit_date"]) for t in cl])
        if cl:
            r = pd.DataFrame(cl)
            paper["live"] = dict(avg=round(r.ret_pct.mean(), 1), med=round(r.ret_pct.median(), 1),
                                 winrate=round((r.ret_pct > 0).mean() * 100, 0),
                                 hold_wk=round(r.hold_wk.mean(), 1))

    out = dict(
        generated=str(date.today()), signal_week=str(wk.date()),
        rule="RS13 > 1.5  AND  (흑자전환 OR 이익폭증)  AND  OPM > 0",
        exit="고점 대비 −20% 트레일링 · 8종목 × 12.5% · 2주 분할매수 · 불타기 없음",
        universe=int(len(base)), n=int(len(sel)),
        funnel=funnel, candidates=[row(r) for _, r in sel.iterrows()],
        backtest=BACKTEST, paper=paper)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"→ {OUT}")
    print(f"  기준 주차 {out['signal_week']} · 후보 {out['n']}종 · 유니버스 {out['universe']}종")
    if paper:
        print(f"  페이퍼: 보유 {paper['n_open']} · 청산 {paper['n_closed']}")


if __name__ == "__main__":
    main()
