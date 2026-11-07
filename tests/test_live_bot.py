# -*- coding: utf-8 -*-
"""주문 봇(한국 단독 v1.7) — 판단·안전장치·대조·모의 차단 (네트워크 없음)."""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "live"))
import bot as B
from executor.broker_toss import TossTrader

IX = {"KR": {"ok": True}, "KQ": {"ok": True}}
PLAN = {"made": "2026-11-07", "index": IX,
        "sleeves": {"KR": {"buys": [{"sym": "000001", "name": "가나", "ref_px": 10000, "rs": 99, "why": "흑자전환"}]}}}
BM = {"000001": "KQ", "000002": "KR"}
D = date(2026, 11, 10)


def L0(pos=None, cash=300000, **k):
    L = {"US": {"cash_krw": 0, "positions": {}}, "KR": {"cash_krw": cash, "positions": pos or {}}, "done_ids": [], "pending": {}}
    L.update(k); return L


def P(**k):
    p = dict(shares=3, avg=10000, first_px=10000, peak=15000, stop=12000, added=True, last_px=15000, opened="2026-11-10", name="X")
    p.update(k); return p


def test_new_buy_integer_and_idempotent():
    L = L0()
    o, _, eq = B.decide(L, PLAN, {}, BM, today=D)
    assert eq["target_krw"] == 60000 and o[0]["quantity"] == 3            # 36,000 / 10,000 → 3주
    L["done_ids"].append(o[0]["cid"])
    assert B.decide(L, PLAN, {}, BM, today=D)[0] == []                    # 같은 주문 두 번 안 나감


def test_gate_by_board_stale_plan_cooldown_and_too_expensive():
    p = dict(PLAN, index={"KR": {"ok": True}, "KQ": {"ok": False}})        # 코스닥 종목인데 코스닥 5주선 아래
    assert B.decide(L0(), p, {}, BM, today=D)[0] == []
    assert B.decide(L0(), PLAN, {}, BM, today=date(2026, 11, 20))[0] == []
    assert B.decide(L0(cooldown={"000001": "2026-11-01"}), PLAN, {}, BM, today=D)[0] == []
    assert B.decide(L0(), PLAN, {"000001": (50000.0, "d")}, BM, today=D)[0] == []   # 1주 > 배정


def test_stop_uses_peak_not_entry():
    o, _, _ = B.decide(L0({"000002": P()}), PLAN, {"000002": (12100.0, "d")}, BM, today=date(2026, 11, 20))
    assert o == []                                                         # 12,100 > 15,000×0.8
    o, _, _ = B.decide(L0({"000002": P()}), PLAN, {"000002": (11900.0, "d")}, BM, today=date(2026, 11, 20))
    assert o[0]["side"] == "SELL" and o[0]["quantity"] == 3


def test_pyramid_once_and_gated():
    pos = {"000002": P(added=False, peak=11000, stop=8800)}
    o, _, _ = B.decide(L0(pos), PLAN, {"000002": (11000.0, "d")}, BM, today=date(2026, 11, 20))
    assert o[0]["cid"].endswith("ADD") and o[0]["quantity"] >= 1
    p2 = dict(PLAN, index={"KR": {"ok": False}, "KQ": {"ok": True}})
    assert B.decide(L0(pos), p2, {"000002": (11000.0, "d")}, BM, today=date(2026, 11, 20))[0] == []


def test_guard_blocks():
    eq = dict(equity_krw=300000)
    orders = [dict(sym="999999", side="BUY", quantity=1, px=1000, cid="a", why=""),
              dict(sym="000001", side="BUY", quantity=20, px=10000, cid="b", why="")]    # 20만 > 상한 10.5만
    ok, why = B.guard(orders, L0(), PLAN, eq)
    assert ok == [] and len(why) == 2


def test_reconcile_flags_manual_trade_ignores_legacy_and_us():
    diff, legacy = B.reconcile({"000002": dict(shares=3)}, [
        {"sym": "000002", "qty": 2, "market": "KR"}, {"sym": "005930", "qty": 1, "market": "KR"}, {"sym": "SATL", "qty": 9, "market": "US"}])
    assert diff[0]["sym"] == "000002" and legacy == ["005930"]


def test_dry_run_never_posts():
    class S:
        def post(self, *a, **k): raise AssertionError("모의인데 POST")
    T = TossTrader("id", "sec", live=False, session=S())
    r = T.place("1", symbol="000001", side="BUY", client_order_id="x", quantity=3)
    assert r["dry_run"] and T.sent[0]["quantity"] == "3" and T.sent[0]["orderType"] == "MARKET"


def test_switch_needs_both(monkeypatch, tmp_path):
    f = tmp_path / "s.json"; f.write_text('{"live": true}')
    monkeypatch.setattr(B, "SWITCH", f)
    monkeypatch.delenv("LIVE_TRADING", raising=False)
    assert not B.is_live()
    monkeypatch.setenv("LIVE_TRADING", "ON")
    assert B.is_live()


def test_trim_over_cap_to_30pct_partial_and_weekly(monkeypatch, tmp_path):
    # v1.8(2026-11-07): 비중 30%×1.05 초과 → 30%까지 일부 매도, 주 1회(cid 에 ISO 주), 손절·고점은 그대로
    pos = {"000002": P(shares=20, avg=10000, first_px=10000, peak=20000, stop=16000, added=True)}
    L = L0(pos, cash=200000)                       # 20주×20,000 = 40만 / 자산 60만 = 66.7%
    o, _, eq = B.decide(L, PLAN, {"000002": (20000.0, "2026-11-13")}, BM, today=D)
    t = [x for x in o if x["cid"].endswith("TRIM")][0]
    assert t["side"] == "SELL" and t["quantity"] == 11 and "2026W46" in t["cid"]   # 40만 − 18만 = 22만 → 11주
    monkeypatch.setattr(B, "TRADES", tmp_path / "t.jsonl")
    B.apply_fill(L, t, 11, 20000.0, 0.0, "2026-11-13")
    p = L["KR"]["positions"]["000002"]
    assert p["shares"] == 9 and p["stop"] == 16000 and L["KR"]["cash_krw"] == 420000
    assert "000002" not in (L.get("cooldown") or {})


def test_no_trim_at_cap():
    pos = {"000002": P(shares=6, peak=15000, stop=12000)}              # 9만 / 30만 = 30% — 덜지 않음
    o, _, _ = B.decide(L0(pos, cash=210000), PLAN, {"000002": (15000.0, "2026-11-13")}, BM, today=D)
    assert not [x for x in o if x["cid"].endswith("TRIM")]


def test_market_hours_guard():
    from datetime import datetime
    assert B.in_kr_session(datetime(2026, 11, 9, 10, 30, tzinfo=B.KST))
    assert not B.in_kr_session(datetime(2026, 11, 9, 2, 30, tzinfo=B.KST))
    assert not B.in_kr_session(datetime(2026, 11, 7, 10, 30, tzinfo=B.KST))   # 토요일
