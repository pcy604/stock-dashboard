# -*- coding: utf-8 -*-
"""
주도주 포워드 페이퍼 트레이딩 — 규칙⑤ 신호를 실시간으로 추적
  진입: RS13>1.5 AND (흑자전환 OR 이익폭증) AND PSR<3   (leaders_listup 과 동일)
  청산: 고점 대비 −20% 트레일링  ← 고정 기간이 아니므로 매 갱신마다 고점을 추적한다
  목적: 백테스트(CAGR 27.7% / 승률 38% / 손익비 5.5)가 실전에서 재현되는지 대조

CLI
  python leaders_paper.py log      # 이번 주 신호를 가상진입 기록 (주 1회)
  python leaders_paper.py update   # 시세 갱신 → 고점·트레일링 청산 판정
  python leaders_paper.py report   # 실전 vs 백테스트 대조
"""
import json, os, sys
from datetime import date, datetime
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(BASE, "results", "leaders_paper.json")
TRAIL = 0.20            # 고점 대비 −20% 트레일링
MAXPOS = 8              # 동시 보유 상한
COST = 0.25 / 100       # 왕복 비용 근사

# 백테스트 기대값 (2018~2026, 규칙⑤ · trail-20 · 8종목 12.5%)
REF = dict(avg_ret=23.1, med_ret=-6.9, winrate=38.0, hold_wk=21.0,
           payoff=5.5, cagr=27.7, mdd=-23.9)


def _fdr():
    import FinanceDataReader as fdr
    return fdr


def price_now(sym):
    try:
        d = _fdr().DataReader(sym, (date.today() - pd.Timedelta(days=15)).isoformat())
        c = d["Close"].dropna()          # 당일 미체결 바는 Close=NaN
        if len(c) == 0:
            return None, None
        return float(c.iloc[-1]), str(c.index[-1].date())
    except Exception:
        return None, None


def price_series(sym, start):
    try:
        return _fdr().DataReader(sym, start)["Close"].dropna()
    except Exception:
        return None


def load():
    if os.path.exists(LEDGER):
        return json.load(open(LEDGER, encoding="utf-8"))
    return dict(created=str(date.today()), rule="⑤ RS13>1.5 & (흑자전환 OR 이익폭증) & PSR<3",
                exit="고점 대비 -20% 트레일링", ref=REF, trades=[])


def save(d):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    json.dump(d, open(LEDGER, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


# ────────────────────────── log ──────────────────────────
def cmd_log():
    import leaders_boost as B
    d = B.build()
    d["as_of"] = pd.to_datetime(d.as_of)
    wk = d.as_of.max()
    w = d[d.as_of == wk]
    base = w[(w.close >= 5) & (w.adv_20d >= 5e6) & (w.marcap >= 2e9)]
    sel = base[(base.rs_13w > 1.5) & (base.psr < 3) &
               ((base.op_turn == 1) | (base.b_any == 1))].sort_values("rs_13w", ascending=False)

    led = load()
    open_syms = {t["sym"] for t in led["trades"] if t["status"] == "open"}
    room = MAXPOS - len(open_syms)
    print(f"기준 주차 {wk.date()} · 조건 충족 {len(sel)}종 · 현재 보유 {len(open_syms)}종 · 여유 {room}")
    if room <= 0:
        print("  보유 상한 도달 — 신규 진입 없음"); return

    added = 0
    for _, r in sel.iterrows():
        if added >= room:
            break
        if r.sym in open_syms:
            continue
        px, pdate = price_now(r.sym)
        if px is None:
            print(f"  SKIP {r.sym} 시세 조회 실패"); continue
        trig = ([" 흑자전환"] if r.op_turn == 1 else []) + \
               [k for k in ("b_ophigh", "b_nihigh", "b_opjump", "b_opmjump") if r[k] == 1]
        led["trades"].append(dict(
            id=f"{r.sym}_{date.today()}", sym=r.sym, market="US",
            signal_week=str(wk.date()), log_date=str(date.today()),
            entry_px=round(px, 4), entry_px_date=pdate,
            peak_px=round(px, 4), peak_date=pdate,
            rs_13w=round(float(r.rs_13w), 2), psr=round(float(r.psr), 2),
            dist_52w=round(float(r.dist_52w), 1),
            triggers=[t.strip() for t in trig],
            status="open", exit_px=None, exit_date=None, ret_pct=None, hold_wk=None,
            marks={}))
        added += 1
        print(f"  LOG  {r.sym:6s} ${px:>9,.2f}  RS {r.rs_13w:.2f}  PSR {r.psr:.2f}  {' '.join(trig)}")
    led["updated"] = str(date.today())
    save(led)
    print(f"\n기록 {added}건 → {LEDGER}")


# ───────────────────────── update ─────────────────────────
def cmd_update():
    led = load()
    ops = [t for t in led["trades"] if t["status"] == "open"]
    if not ops:
        print("열린 포지션 없음"); return
    print(f"열린 포지션 {len(ops)}건 갱신")
    for t in ops:
        s = price_series(t["sym"], t["entry_px_date"])
        if s is None or len(s) == 0:
            print(f"  SKIP {t['sym']} 시세 실패"); continue
        peak = float(s.max()); last = float(s.iloc[-1])
        t["peak_px"] = round(peak, 4)
        t["peak_date"] = str(s.idxmax().date())
        hold = (pd.Timestamp(s.index[-1]) - pd.Timestamp(t["entry_px_date"])).days / 7
        # 고정 지평 마크 (백테스트 대조용)
        for lab, wks in (("4w", 4), ("13w", 13), ("26w", 26)):
            if hold >= wks and lab not in t["marks"]:
                cut = pd.Timestamp(t["entry_px_date"]) + pd.Timedelta(weeks=wks)
                sub = s[s.index <= cut]
                if len(sub):
                    t["marks"][lab] = round((float(sub.iloc[-1]) / t["entry_px"] - 1) * 100, 2)
        # 트레일링 청산 판정 (종가 기준)
        hit = s[s <= peak * (1 - TRAIL)]
        hit = hit[hit.index > pd.Timestamp(t["entry_px_date"])]
        if len(hit):
            xp = float(hit.iloc[0]); xd = str(hit.index[0].date())
            t.update(status="closed", exit_px=round(xp, 4), exit_date=xd,
                     ret_pct=round(((xp / t["entry_px"]) * (1 - COST) - 1) * 100, 2),
                     hold_wk=round((pd.Timestamp(xd) - pd.Timestamp(t["entry_px_date"])).days / 7, 1))
            print(f"  EXIT {t['sym']:6s} {t['ret_pct']:+7.1f}%  {t['hold_wk']:.0f}주  "
                  f"(고점 ${peak:,.2f} → −20%)")
        else:
            cur = ((last / t["entry_px"]) - 1) * 100
            dd = (last / peak - 1) * 100
            print(f"  HOLD {t['sym']:6s} {cur:+7.1f}%  고점대비 {dd:+6.1f}%  {hold:.0f}주")
    led["updated"] = str(date.today())
    save(led)


# ───────────────────────── report ─────────────────────────
def cmd_report():
    led = load()
    T = pd.DataFrame(led["trades"])
    if T.empty:
        print("기록 없음 — 먼저 `python leaders_paper.py log`"); return
    cl = T[T.status == "closed"]
    op = T[T.status == "open"]
    print("=" * 96)
    print(f"주도주 페이퍼 트레이딩 — 시작 {led['created']} · 갱신 {led.get('updated','-')}")
    print(f"규칙 {led['rule']}  |  청산 {led['exit']}")
    print("=" * 96)
    print(f"  총 {len(T)}건 (청산 {len(cl)} · 보유 {len(op)})")
    if len(op):
        print("\n[보유 중]")
        print(op[["sym", "log_date", "entry_px", "peak_px", "rs_13w", "psr", "triggers"]]
              .to_string(index=False))
    if len(cl) == 0:
        print("\n청산된 거래가 없어 실전 대조 불가. 백테스트 기대값:")
        print(f"  평균 {REF['avg_ret']:+.1f}% · 중앙 {REF['med_ret']:+.1f}% · "
              f"승률 {REF['winrate']:.0f}% · 보유 {REF['hold_wk']:.0f}주 · 손익비 {REF['payoff']:.1f}")
        return
    live = dict(avg_ret=cl.ret_pct.mean(), med_ret=cl.ret_pct.median(),
                winrate=(cl.ret_pct > 0).mean() * 100, hold_wk=cl.hold_wk.mean(),
                payoff=(cl[cl.ret_pct > 0].ret_pct.mean() / abs(cl[cl.ret_pct <= 0].ret_pct.mean())
                        if (cl.ret_pct <= 0).any() and (cl.ret_pct > 0).any() else np.nan))
    print("\n[실전 vs 백테스트]")
    print(f"{'지표':12s}{'실전':>10s}{'백테스트':>12s}{'괴리':>10s}")
    for k, lab, unit in [("avg_ret", "평균 수익", "%"), ("med_ret", "중앙 수익", "%"),
                         ("winrate", "승률", "%"), ("hold_wk", "평균 보유", "주"),
                         ("payoff", "손익비", "")]:
        lv, rf = live[k], REF[k]
        gap = "—" if (lv != lv) else f"{lv - rf:+.1f}"
        lvs = "—" if lv != lv else f"{lv:.1f}{unit}"
        print(f"{lab:12s}{lvs:>10s}{rf:>11.1f}{unit}{gap:>10s}")
    n = len(cl)
    print(f"\n  ⚠️ 청산 {n}건 — {'표본이 너무 적어 판단 불가 (최소 20건 필요)' if n < 20 else '참고 가능'}")
    print(f"  ⚠️ 백테스트는 생존편향·인샘플 선택이 있어 낙관적. 실전이 낮게 나오는 게 정상이다.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    {"log": cmd_log, "update": cmd_update, "report": cmd_report}.get(cmd, cmd_report)()
