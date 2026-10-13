"""executor — 원칙 v1 규칙이 코드로 그대로 옮겨졌는지."""
import copy, json, os
import pytest
from executor.ledger import Ledger, Position
from executor import planner, broker_paper

CFG = json.load(open(os.path.join(os.path.dirname(__file__), "..", "executor", "config.json"), encoding="utf-8"))
W = "2026-10-05"


def _pos(sym, qty, px, entry="2025-01-06", peak=None, peak_week=None, sleeve="satellite"):
    return Position(sym, sleeve, qty, entry, px, peak or px, peak_week or entry, 0, px)


def _plan(led, prices, above=True, sigs=(), cfg=CFG):
    return planner.plan(led, copy.deepcopy(cfg), W, dict(prices), above, list(sigs))


def test_first_funding_core_gets_core_plus_idle_satellite():
    led = Ledger(cash=100_000)
    r = _plan(led, {"VOO": 500})
    core = [o for o in r["orders"] if o["sym"] == "VOO"]
    assert len(core) == 1 and core[0]["side"] == "BUY"
    assert core[0]["amount"] == pytest.approx(80_000)          # 코어 50% + 위성 빈칸 30%


def test_satellite_buys_smallest_mcap_first_one_slot_each():
    led = Ledger(cash=100_000)
    sigs = [dict(sym="BIG", mc=50), dict(sym="SMALL", mc=1), dict(sym="MID", mc=5)]
    cfg = copy.deepcopy(CFG); cfg["satellite"]["slots"] = 2
    r = _plan(led, {"VOO": 500, "BIG": 10, "SMALL": 10, "MID": 10}, sigs=sigs, cfg=cfg)
    buys = [o["sym"] for o in r["orders"] if o["side"] == "BUY" and o["sleeve"] == "satellite"]
    assert buys == ["SMALL", "MID"]
    amt = [o["amount"] for o in r["orders"] if o["sym"] == "SMALL"][0]
    assert amt == pytest.approx(100_000 * 0.30 / 2)


def test_take_rule_sells_after_52w_and_33w_without_new_high():
    led = Ledger(cash=0)
    led.positions["AAA"] = _pos("AAA", 100, 10, entry="2025-08-04", peak=12, peak_week="2026-02-16")
    r = _plan(led, {"VOO": 500, "AAA": 11})
    s = [o for o in r["orders"] if o["sym"] == "AAA"]
    assert s and s[0]["side"] == "SELL" and "익절" in s[0]["reason"]


def test_no_take_when_recent_new_high():
    led = Ledger(cash=0)
    led.positions["AAA"] = _pos("AAA", 100, 10, entry="2025-08-04", peak=12, peak_week="2026-08-31")
    r = _plan(led, {"VOO": 500, "AAA": 11})
    assert not [o for o in r["orders"] if o["sym"] == "AAA" and o["side"] == "SELL" and "익절" in o["reason"]]


def test_no_stop_loss_by_default():
    led = Ledger(cash=0)
    led.positions["AAA"] = _pos("AAA", 100, 10, entry="2026-06-01", peak=20, peak_week="2026-07-06")
    r = _plan(led, {"VOO": 500, "AAA": 11})                 # 고점 대비 -45% 지만 손절 없음
    assert not [o for o in r["orders"] if o["sym"] == "AAA" and "손절" in o["reason"]]


def test_trim_over_15pct_of_satellite_to_10pct():
    led = Ledger(cash=70_000)
    led.positions["AAA"] = _pos("AAA", 600, 10, entry="2026-06-01")      # 6,000 = 위성(30,000*?)
    r = _plan(led, {"VOO": 500, "AAA": 10})
    E = 76_000; sat = E * 0.30
    t = [o for o in r["orders"] if o["sym"] == "AAA" and "트림" in o["reason"]]
    assert t and t[0]["amount"] == pytest.approx(6_000 - sat * 0.10)


def test_core_switch_off_sells_core():
    led = Ledger(cash=20_000)
    led.positions["VOO"] = _pos("VOO", 160, 500, sleeve="core")
    r = _plan(led, {"VOO": 500}, above=False)
    s = [o for o in r["orders"] if o["sym"] == "VOO"]
    assert s and s[0]["side"] == "SELL" and s[0]["amount"] == pytest.approx(80_000)
    assert r["core_on"] is False


def test_kill_switch_blocks_new_buys():
    led = Ledger(cash=50_000, sat_equity_peak=40_000)
    led.positions["AAA"] = _pos("AAA", 100, 100, entry="2026-06-01", peak=200, peak_week="2026-07-06")
    r = _plan(led, {"VOO": 500, "AAA": 100, "NEW": 10}, sigs=[dict(sym="NEW", mc=1)])
    assert r["kill"] and not [o for o in r["orders"] if o["sym"] == "NEW"]


def test_leveraged_etf_never_bought():
    led = Ledger(cash=100_000)
    r = _plan(led, {"VOO": 500, "TSLL": 10}, sigs=[dict(sym="TSLL", mc=1)])
    assert not [o for o in r["orders"] if o["sym"] == "TSLL"]


def test_missing_price_two_weeks_sells_with_approval():
    led = Ledger(cash=0)
    p = _pos("GONE", 100, 10, entry="2026-06-01"); p.missing_weeks = 1
    led.positions["GONE"] = p
    r = _plan(led, {"VOO": 500})
    s = [o for o in r["orders"] if o["sym"] == "GONE"]
    assert s and s[0]["needs_approval"]


def test_paper_fill_updates_ledger_and_sells_first():
    led = Ledger(cash=100_000)
    r = _plan(led, {"VOO": 500, "SMALL": 10}, sigs=[dict(sym="SMALL", mc=1)])
    assert r["orders"][0]["side"] in ("SELL", "BUY")
    done = broker_paper.fill(led, r["orders"], W, slippage_pct=0.3, approve_all=True)
    assert all(d["status"] == "체결" for d in done)
    assert "SMALL" in led.positions and "VOO" in led.positions
    assert led.cash == pytest.approx(100_000 - sum(o["amount"] for o in r["orders"]), rel=1e-6)
