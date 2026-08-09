# -*- coding: utf-8 -*-
"""
주도주 후보 리스트업 — 확정 규칙(⑥, 2026-08-08~)
  진입: RS13>1.5  AND  (흑자전환 OR 이익폭증)  AND  OPM>0  + 유동성/시총
  실측: CAGR 32.8% · MDD −37.7% · 회복배율 0.87 (SPY 14.2% / −31.8% / 0.45)
        워크포워드 CAGR 4/6 · 승률 43.4% · 연 16.7거래
  ※ 기각된 조건: 거래량 급증 · 신고가 근접 · 매출성장 · OPM QoQ 개선 · 불타기(피라미딩)

  PSR은 2026-08-08부로 의사결정에서 제외되고 표시용 참고지표로만 남는다.
  구 규칙⑤(PSR<3)는 MDD가 −23.9%로 더 좋았으나, 주도주 이력 종목의 17%(90/520)가
  8년간 PSR<3에 한 번도 진입하지 않는 구조적 사각지대가 확인되어 교체했다.
  → MDD가 SPY(−31.8%)보다 나빠지는 것을 감수한 결정이다.
"""
import os, sys
import numpy as np
import pandas as pd
import leaders_boost as B

pd.set_option("display.width", 270, "display.max_columns", 40)
BOOST = {"b_ophigh": "영업익신고점", "b_nihigh": "순익신고점",
         "b_opjump": "영업익QoQ+50%", "b_opmjump": "OPM QoQ+3%p"}


def main(week=None):
    import sqlite3
    d = B.build()
    d["as_of"] = pd.to_datetime(d.as_of)
    week = d.as_of.max() if week is None else pd.Timestamp(week)
    w = d[d.as_of == week].copy()
    # sim2.load()가 안 가져오는 표시용 컬럼 보충
    c = sqlite3.connect(B.DB)
    extra = pd.read_sql("SELECT sym,name,rs_26w FROM factor_weekly "
                        "WHERE as_of=? AND factor_ver='v1'", c,
                        params=(str(week.date()),))
    c.close()
    w = w.merge(extra, on="sym", how="left")
    base = w[(w.close >= 5) & (w.adv_20d >= 5e6) & (w.marcap >= 2e9)]

    sel = base[(base.rs_13w > 1.5) & (base.opm > 0) &
               ((base.op_turn == 1) | (base.b_any == 1))].copy()
    sel["시총B"] = (sel.marcap / 1e9).round(1)
    sel["거래대금M"] = (sel.adv_20d / 1e6).round(0)
    sel["트리거"] = sel.apply(
        lambda r: " ".join(([" 흑자전환"] if r.op_turn == 1 else []) +
                           [v for k, v in BOOST.items() if r[k] == 1]).strip() or "-", axis=1)
    sel = sel.sort_values("rs_13w", ascending=False)

    print("=" * 140)
    print(f"주도주 후보 — 기준 주차 {week.date()}   유니버스 {len(base)}종 (시총$2B+ · 거래대금$5M+)")
    print("  규칙⑥  RS13>1.5  AND  (흑자전환 OR 이익폭증)  AND  OPM>0   (PSR은 참고만)")
    print("=" * 140)
    if len(sel) == 0:
        print("  조건 충족 종목 없음")
    else:
        cols = ["sym", "name", "close", "rs_13w", "rs_26w", "psr", "per", "dist_52w",
                "opm", "opm_qoq", "시총B", "거래대금M", "트리거"]
        print(sel[cols].round(2).to_string(index=False))
        print(f"\n  → {len(sel)}종 충족.  보유 상한 8종이면 RS 상위 8종: "
              f"{', '.join(sel.sym.head(8))}")

    # 단계별 몇 종목이 걸러지는지
    print(f"\n{'-'*140}\n필터 단계별 잔존")
    steps = [("유니버스(유동성·시총)", base),
             ("+ RS13 > 1.5", base[base.rs_13w > 1.5]),
             ("+ OPM > 0", base[(base.rs_13w > 1.5) & (base.opm > 0)]),
             ("+ (흑자전환 OR 이익폭증)", sel),
             ("(참고) 여기에 PSR<3까지", sel[sel.psr < 3])]
    for lab, x in steps:
        print(f"  {lab:26s} {len(x):5d}종")
    if len(sel):
        print(f"\n  트리거 내역: 흑자전환 {int((sel.op_turn==1).sum())}종 · " +
              " · ".join(f"{v} {int(sel[k].sum())}종" for k, v in BOOST.items()))

    print(f"\n{'-'*140}")
    print("실행 규칙")
    print("  매수  목표비중을 2주에 나눠 (1주 전액 대비 CAGR −0.2%p / MDD +1.1%p 개선)")
    print("  비중  8종목 × 12.5%  또는  5종목 × 20%")
    print("  청산  고점 대비 −20% 트레일링 (종가 기준)")
    print("  불타기 ❌ 안 함 — 가격·이익 트리거 모두 회복배율 1.2 → 0.7로 악화")
    print("  중단  롤링 12개월 SPY 대비 초과수익 −30%p")
    print("\n⚠️ 조건 충족 종목의 기계적 출력이며 매수 권유 아님.")
    print("⚠️ 워크포워드 CAGR 4/6 — 절반 가까이 SPY에 진다. PSR/PER은 주식수 역산이라 부정확.")
    print("⚠️ MDD −37.7%는 SPY(−31.8%)보다 나쁘다. 이 규칙은 낙폭이 아니라 수익을 택한 선택이다.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
