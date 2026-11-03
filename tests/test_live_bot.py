# -*- coding: utf-8 -*-
"""주문 봇 — 판단·안전장치·대조·모의 차단 (네트워크 없음)."""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "live"))
import bot as B
from executor.broker_toss import TossTrader

PLAN = {"made": "2026-11-01", "usdkrw": 1300.0, "index": {"US": {"ok": True}},
        "sleeves": {"US": {"buys": [{"sym": "CDNA", "name": "CareDx", "krw": 36000, "rs": 99, "why": "이익가속"}]}}}


def L0(pos=None, cash=300000):
    return {"US": {"cash_krw": cash, "positions": pos or {}}, "KR": {"cash_krw": 0, "positions": {}}, "done_ids": [], "pending": {}}


def test_new_buy_amount_and_idempotent():
    L = L0()
    o, _, eq = B.decide(L, PLAN, {}, today=date(2026, 11, 3))
    assert [x["sym"] for x in o] == ["CDNA"] and abs(o[0]["amount_usd"] - 27.69) < 0.01
    L["done_ids"].append(o[0]["cid"])
    assert B.decide(L, PLAN, {}, today=date(2026, 11, 3))[0] == []          # 같은 주문 두 번 안 나감


def test_stale_plan_and_index_gate():
    assert B.decide(L0(), PLAN, {}, today=date(2026, 11, 12))[0] == []
    p = dict(PLAN, index={"US": {"ok": False}})
    assert B.decide(L0(), p, {}, today=date(2026, 11, 3))[0] == []


def test_stop_uses_peak_not_entry():
    pos = {"X": dict(shares=2.0, avg=100, first_px=100, peak=150, stop=120, added=True, last_px=150, opened="2026-11-03")}
    o, _, _ = B.decide(L0(pos), PLAN, {"X": (121.0, "2026-11-10")}, today=date(2026, 11, 20))
    assert o == []                                                           # 121 > 150×0.8=120
    o, _, _ = B.decide(L0(pos), PLAN, {"X": (119.0, "2026-11-10")}, today=date(2026, 11, 20))
    assert o[0]["side"] == "SELL" and o[0]["quantity"] == 2.0


def test_pyramid_once():
    pos = {"X": dict(shares=1.0, avg=100, first_px=100, peak=111, stop=88.8, added=False, last_px=111, opened="2026-11-03")}
    o, _, _ = B.decide(L0(pos), PLAN, {"X": (111.0, "d")}, today=date(2026, 11, 20))
    assert o[0]["side"] == "BUY" and o[0]["cid"].endswith("ADD")
    pos["X"]["added"] = True
    assert B.decide(L0(pos), PLAN, {"X": (111.0, "d")}, today=date(2026, 11, 20))[0] == []


def test_guard_blocks():
    L = L0()
    eq = dict(equity_krw=300000, fx=1300.0)
    orders = [dict(sym="TQQQ", side="BUY", amount_usd=10, cid="a", why=""),
              dict(sym="ZZZ", side="BUY", amount_usd=10, cid="b", why=""),
              dict(sym="CDNA", side="BUY", amount_usd=500, cid="c", why="")]
    ok, why = B.guard(orders, L, PLAN, eq)
    assert ok == [] and len(why) == 3


def test_reconcile_flags_manual_trade_ignores_legacy():
    pos = {"CDNA": dict(shares=0.5)}
    diff, legacy = B.reconcile(pos, [{"sym": "CDNA", "qty": 0.3, "market": "US"}, {"sym": "SATL", "qty": 10, "market": "US"}])
    assert diff and diff[0]["sym"] == "CDNA" and legacy == ["SATL"]


def test_dry_run_never_posts():
    class S:
        def post(self, *a, **k): raise AssertionError("모의인데 POST")
    T = TossTrader("id", "sec", live=False, session=S())
    r = T.place("1", symbol="CDNA", side="BUY", client_order_id="x", amount_usd=27.69)
    assert r["dry_run"] and T.sent[0]["orderAmount"] == "27.69" and "quantity" not in T.sent[0]


def test_switch_needs_both(monkeypatch, tmp_path):
    f = tmp_path / "s.json"; f.write_text('{"live": true}')
    monkeypatch.setattr(B, "SWITCH", f)
    monkeypatch.delenv("LIVE_TRADING", raising=False)
    assert not B.is_live()
    monkeypatch.setenv("LIVE_TRADING", "ON")
    assert B.is_live()
