"""주간 주문표 — 원칙 v1 을 그대로 옮긴다. 순수 함수: (원장, 시세, 신호, 설정) → 주문 목록.

순서 (원칙 v1 §8 ③)
  0. 보유 갱신 (보유 주수·최고가·가격 결측)
  1. 코어 스위치   S&P500 이 40주 이평 위면 코어 보유, 아래면 코어 → 완충(현금)
  2. 위성 매도     익절(52주 보유 후 33주 신고가 미갱신) · 손절(설정 시) · 가격 2주 결측
  3. 위성 트림     한 종목이 위성의 15% 초과 → 10% 로
  4. 위성 매수     빈 칸 × (위성 예산 / 칸 수), 시총 작은 순, 킬스위치면 중단
  5. 빈 칸 → 코어   위성에서 놀고 있는 돈은 코어로(원칙 §4-6)
  6. 슬리브 리밸런싱  밴드 ±5%p 이탈 또는 13주마다
  안전장치: 1회 주문 상한·차단 종목·레거시 종목은 엔진이 손대지 않음
"""
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional


@dataclass
class Order:
    sym: str
    side: str            # BUY | SELL
    amount: float        # 원화·달러 금액(체결 전 추정)
    px: float
    sleeve: str
    reason: str
    needs_approval: bool = False

    @property
    def qty(self):
        return self.amount / self.px if self.px else 0.0


def _weeks_between(a: str, b: str) -> int:
    import datetime as dt
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days // 7


def plan(ledger, cfg: dict, week: str, prices: Dict[str, float], core_above_ma: Optional[bool],
         signals: List[dict]) -> dict:
    sat = cfg["satellite"]; sl = cfg["sleeves"]; safety = cfg["safety"]
    core_sym = cfg["core_symbol"]
    blocked = set(safety.get("blocked_symbols", [])) | set(cfg.get("legacy_symbols", []))
    orders: List[Order] = []
    notes: List[str] = []

    # 0) 보유 갱신
    for p in ledger.positions.values():
        px = prices.get(p.sym)
        if px is None:
            p.missing_weeks += 1
            continue
        p.missing_weeks = 0
        p.last_px = px
        p.weeks_held = _weeks_between(p.entry_date, week)
        if px > p.peak_px:
            p.peak_px, p.peak_week = px, week

    E = ledger.equity(prices)
    if E <= 0:
        return {"orders": [], "notes": ["자산 0"], "equity": E}
    ledger.equity_peak = max(ledger.equity_peak, E)
    sat_val = ledger.value(prices, "satellite")
    ledger.sat_equity_peak = max(ledger.sat_equity_peak, sat_val)

    # 1) 코어 스위치
    switch_on = cfg.get("core_ma_switch_weeks", 0) and core_above_ma is not None
    core_on = (not switch_on) or bool(core_above_ma)
    if switch_on and not core_above_ma:
        notes.append(f"코어 스위치 OFF — S&P500 이 {cfg['core_ma_switch_weeks']}주 이평 아래. 코어를 현금으로 둔다")

    # 2) 위성 매도
    sold = set()
    for p in list(ledger.positions.values()):
        if p.sleeve != "satellite" or p.sym in blocked:
            continue
        px = prices.get(p.sym, p.last_px)
        why = None
        if p.missing_weeks >= 2:
            why = f"가격 {p.missing_weeks}주 결측(상장폐지·정지 의심) — 마지막가로 정리, 수동 확인"
        elif p.weeks_held >= sat["take_min_weeks"] and _weeks_between(p.peak_week, week) >= sat["take_dry_weeks"]:
            why = f"익절 규칙: 보유 {p.weeks_held}주 · 최고가 이후 {_weeks_between(p.peak_week, week)}주 신고가 없음"
        elif sat.get("stop_from_peak_pct") and px <= p.peak_px * (1 - sat["stop_from_peak_pct"] / 100):
            why = f"고점 대비 -{sat['stop_from_peak_pct']}% 손절"
        elif sat.get("disaster_stop_pct") and px <= p.peak_px * (1 - sat["disaster_stop_pct"] / 100):
            why = f"재앙 손절 -{sat['disaster_stop_pct']}%"
        if why:
            orders.append(Order(p.sym, "SELL", p.qty * px, px, "satellite", why, needs_approval=p.missing_weeks >= 2))
            sold.add(p.sym)

    # 3) 위성 트림
    sat_budget = E * sl["satellite"]
    for p in ledger.positions.values():
        if p.sleeve != "satellite" or p.sym in sold or p.sym in blocked:
            continue
        px = prices.get(p.sym, p.last_px); v = p.qty * px
        if sat_budget > 0 and v / sat_budget * 100 > sat["trim_over_pct"]:
            cut = v - sat_budget * sat["trim_to_pct"] / 100
            orders.append(Order(p.sym, "SELL", cut, px, "satellite",
                                f"트림: 위성의 {v/sat_budget*100:.1f}% → {sat['trim_to_pct']}%"))

    # 4) 위성 매수
    held = [p for p in ledger.positions.values() if p.sleeve == "satellite" and p.sym not in sold]
    free = max(0, sat["slots"] - len(held))
    kill = (ledger.sat_equity_peak > 0
            and (1 - sat_val / ledger.sat_equity_peak) * 100 >= sat["kill_switch_dd_pct"])
    if kill:
        notes.append(f"⛔ 킬스위치: 위성 낙폭 {(1 - sat_val / ledger.sat_equity_peak) * 100:.1f}% ≥ "
                     f"{sat['kill_switch_dd_pct']}% — 신규 매수 중단, 사람 점검")
    slot_amt = sat_budget / sat["slots"]
    cands = [s for s in signals if s.get("sym") and s["sym"] not in ledger.positions and s["sym"] not in blocked
             and prices.get(s["sym"])]
    if sat.get("order") == "mcap_asc":
        cands.sort(key=lambda s: s.get("mc") or 9e99)
    buys = [] if kill else cands[:free]
    for s in buys:
        orders.append(Order(s["sym"], "BUY", slot_amt, prices[s["sym"]], "satellite",
                            f"이익가속 신호 {s.get('week', week)} · 시총 {s.get('mc')}"))
    skipped = len(cands) - len(buys)
    if skipped > 0 and not kill:
        notes.append(f"만석으로 넘긴 신호 {skipped}종")

    # 5·6) 코어·완충 목표와 리밸런싱
    sat_after = sat_val - sum(o.amount for o in orders if o.sleeve == "satellite" and o.side == "SELL") \
        + sum(o.amount for o in orders if o.sleeve == "satellite" and o.side == "BUY")
    idle = max(0.0, sat_budget - sat_after) if sat.get("idle_to_core") else 0.0
    core_tgt = (E * sl["core"] + idle) if core_on else 0.0
    core_val = ledger.value(prices, "core")
    core_px = prices.get(core_sym)
    due = (ledger.last_rebalance_week is None
           or _weeks_between(ledger.last_rebalance_week, week) >= cfg["rebalance_every_weeks"])
    band = abs(core_val - core_tgt) / E * 100 > cfg["rebalance_band_pp"]
    if core_px and (due or band or (switch_on and (core_val > 0) != core_on)):
        diff = core_tgt - core_val
        if abs(diff) > E * 0.005:
            orders.append(Order(core_sym, "BUY" if diff > 0 else "SELL", abs(diff), core_px, "core",
                                f"코어 목표 {core_tgt/E*100:.1f}% (현재 {core_val/E*100:.1f}%"
                                + (f", 위성 빈칸 {idle/E*100:.1f}% 포함" if idle else "") + ")"))
            ledger.last_rebalance_week = week

    # 안전장치
    cap = E * safety["max_order_pct_of_equity"] / 100
    for o in orders:
        if o.amount > cap and o.sleeve != "core":
            o.needs_approval = True
    turnover = sum(o.amount for o in orders) / E * 100
    if turnover > safety["max_daily_turnover_pct"]:
        notes.append(f"회전율 {turnover:.0f}% > {safety['max_daily_turnover_pct']}% — 전체 승인 필요")
        for o in orders:
            o.needs_approval = True
    # 매도 먼저, 매수 나중 (원칙 §8 ⑤⑥)
    orders.sort(key=lambda o: (o.side != "SELL", o.sleeve != "core"))
    return {"orders": [dict(asdict(o), qty=o.qty) for o in orders], "notes": notes, "equity": E,
            "sat_value": sat_val, "core_on": core_on, "kill": kill}
