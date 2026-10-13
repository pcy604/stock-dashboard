"""가상 체결 — 주문표를 슬리피지만큼 불리하게 체결하고 원장에 반영한다."""
from .ledger import Position


def fill(ledger, orders, week, slippage_pct=0.3, approve_all=False):
    done = []
    for o in orders:
        if o.get("needs_approval") and not approve_all:
            done.append(dict(o, status="승인 대기"))
            continue
        px = o["px"] * (1 + slippage_pct / 100 if o["side"] == "BUY" else 1 - slippage_pct / 100)
        if o["side"] == "SELL":
            p = ledger.positions.get(o["sym"])
            if not p:
                done.append(dict(o, status="보유 없음")); continue
            qty = min(p.qty, o["amount"] / o["px"])
            ledger.cash += qty * px
            p.qty -= qty
            if p.qty <= 1e-9:
                del ledger.positions[o["sym"]]
        else:
            amt = min(o["amount"], ledger.cash)
            if amt <= 0:
                done.append(dict(o, status="현금 부족")); continue
            qty = amt / px
            ledger.cash -= amt
            p = ledger.positions.get(o["sym"])
            if p:
                p.entry_px = (p.entry_px * p.qty + px * qty) / (p.qty + qty); p.qty += qty
            else:
                ledger.positions[o["sym"]] = Position(o["sym"], o["sleeve"], qty, week, px, px, week, 0, px)
        done.append(dict(o, status="체결", fill_px=round(px, 4)))
    ledger.history.append({"week": week, "orders": done})
    ledger.week = week
    return done
