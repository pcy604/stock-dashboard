"""주간 1회 실행 — 페이퍼(P1).

  python -m executor.run --init 100000      원장 생성(가상 자금)
  python -m executor.run                    이번 주 주문표 생성 + 가상 체결 + 보고서
  python -m executor.run --dry-run          주문표만(원장 변경 없음)

입력
  신호: results/leaders_accel.json 의 candidates (signal_week·mc·close)
  시세: Yahoo v8 chart 주봉 종가 (prices.py) — P2 에서 토스 시세로 교체
"""
import argparse, json, os, sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from executor.ledger import Ledger, LEDGER
from executor import planner, broker_paper, prices as P


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", type=float); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--approve-all", action="store_true")
    a = ap.parse_args()
    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    if a.init:
        Ledger(cash=a.init).save(); print(f"원장 생성 — 가상 자금 {a.init:,.0f}"); return
    led = Ledger.load()
    acc = json.load(open(os.path.join(ROOT, "results", "leaders_accel.json"), encoding="utf-8"))
    week = acc.get("signal_week") or date.today().isoformat()
    sigs = [dict(sym=c["sym"], mc=c.get("mc"), week=week) for c in acc.get("candidates", [])]
    syms = sorted({s["sym"] for s in sigs} | set(led.positions) | {cfg["core_symbol"]})
    px, _ = P.weekly_close(syms, cfg["core_symbol"], 0)
    # 코어 스위치 = verdict.py (화면·리포트와 같은 SPY 200일선, 2026-10-21). 예전엔 여기서 VOO 40주선을 따로 쟀다.
    import verdict as V
    above = V.latest_core_on() if cfg.get("core_ma_switch_days") else None
    res = planner.plan(led, cfg, week, px, above, sigs)
    print(report(res, week))
    if a.dry_run:
        return
    done = broker_paper.fill(led, res["orders"], week, cfg.get("slippage_pct", 0.3), a.approve_all)
    led.save()
    print(f"체결 {sum(1 for d in done if d['status']=='체결')}건 · 대기 {sum(1 for d in done if d['status']!='체결')}건 → {LEDGER}")


def report(res, week):
    L = [f"🧾 주간 주문표 ({week}) · 자산 {res['equity']:,.0f}"
         + ("" if res.get("core_on", True) else " · 코어 OFF")]
    for n in res["notes"]:
        L.append(f"  ※ {n}")
    for o in res["orders"]:
        L.append(f"  {'🟥' if o['side']=='SELL' else '🟩'} {o['side']:4s} {o['sym']:6s} {o['amount']:>12,.0f}"
                 f"  [{o['sleeve']}] {o['reason']}{'  ⏸승인필요' if o['needs_approval'] else ''}")
    if not res["orders"]:
        L.append("  (주문 없음)")
    return "\n".join(L)


if __name__ == "__main__":
    main()
