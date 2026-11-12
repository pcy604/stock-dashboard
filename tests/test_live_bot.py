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
    assert eq["target_krw"] == 30000 and o[0]["quantity"] == 1            # v1.9: 30만 ÷ 10 × 50% = 15,000 / 10,000 → 1주
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
    o, _, _ = B.decide(L0(pos, cash=3_000_000), PLAN, {"000002": (11000.0, "d")}, BM, today=date(2026, 11, 20))
    a = [x for x in o if "ADD" in x["cid"]]
    assert a[0]["cid"].endswith("ADD1") and a[0]["quantity"] >= 1             # v1.9: +10% 1차
    o, _, _ = B.decide(L0({"000002": P(added=False, adds=1, peak=12000, stop=9600)}, cash=3_000_000), PLAN,
                       {"000002": (11000.0, "d")}, BM, today=date(2026, 11, 20))
    assert not [x for x in o if "ADD" in x["cid"]]                             # 2차는 +20% 부터
    p2 = dict(PLAN, index={"KR": {"ok": False}, "KQ": {"ok": True}})
    assert not [x for x in B.decide(L0(pos, cash=3_000_000), p2, {"000002": (11000.0, "d")}, BM, today=date(2026, 11, 20))[0] if "ADD" in x["cid"]]


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


def test_rs_exit_sells_and_frees_slot():
    # v1.9: 계획표 exits(RS < 70) → 전량 매도, 그 칸은 같은 날 신규로
    pos = {f"00010{i}": P(name=f"X{i}") for i in range(10)}
    plan = dict(PLAN, sleeves={"KR": dict(PLAN["sleeves"]["KR"], exits=[{"sym": "000100", "rs": 55}])})
    closes = {k: (15000.0, "2026-11-13") for k in pos}
    o, _, _ = B.decide(L0(pos, cash=3_000_000), plan, closes, BM, today=D)
    assert any(x["cid"].endswith("000100-RSOUT") and x["side"] == "SELL" for x in o)
    assert any(x["cid"].endswith("000001-BUY") for x in o)                     # 꽉 찬 10칸인데 1칸이 비어 신규


def test_open_auction_phase_and_limit():
    # 2026-11-09: 08:31~08:58 KST 시가 단일가 창('pre') → 09:00 시가 체결, 09:05~15:10 정규장('reg')
    from datetime import datetime
    k = lambda h, m, d=9: B.kr_phase(datetime(2026, 11, d, h, m, tzinfo=B.KST))
    assert k(8, 40) == "pre" and k(8, 31) == "pre" and k(8, 58) == "pre"
    assert k(8, 59) is None and k(9, 0) is None and k(9, 4) is None
    assert k(9, 10) == "reg" and k(15, 10) == "reg" and k(15, 11) is None
    assert k(8, 40, d=7) is None                                               # 토요일
    assert B.tick(1999) == 1 and B.tick(4999) == 5 and B.tick(15000) == 10 and B.tick(49999) == 50
    assert B.tick(150000) == 100 and B.tick(300000) == 500 and B.tick(600000) == 1000
    assert B.limit_px(15000) == 16500 and B.limit_px(47000) == 51700           # 51,700: 5만 이상 → 100원 단위
    assert B.limit_px(4800) == 5280 and B.limit_px(1234) == 1357


def test_pre_limit_shrinks_quantity_to_cash():
    o = [dict(sym="000001", side="BUY", quantity=10, px=10000.0, lim=11000, cid="x")]
    L = L0({}, cash=100000)
    ok, why = B.guard(o, L, PLAN, dict(equity_krw=1_000_000), cash_krw=100000)
    assert ok and ok[0]["quantity"] == 9 and not why                           # 99,500 ÷ 11,000 = 9주


def test_gate_override_window(tmp_path, monkeypatch):
    import importlib, json as _json, plan as Pl
    from datetime import date as _d
    sw = tmp_path / "live"; sw.mkdir()
    (sw / "switch.json").write_text(_json.dumps({"gate_override_until": "2026-11-13", "gate_override_why": "t"}), encoding="utf-8")
    monkeypatch.setattr(Pl, "ROOT", str(tmp_path))
    assert Pl.gate_override(_d(2026, 11, 13)) and Pl.gate_override(_d(2026, 11, 9))
    assert Pl.gate_override(_d(2026, 11, 14)) is None


def test_naver_rows_parse():
    x = '<chartdata symbol="010170"><item data="20261105|10500|11000|10400|10700|123" />\n<item data="20261106|10700|11200|10600|10860|456" /></chartdata>'
    r = B._naver_rows(x)
    assert r == [(date(2026, 11, 5), 10700.0), (date(2026, 11, 6), 10860.0)]


def test_pyramid_one_step_per_week():
    """2026-11-12 메가터치: 09:10·09:11 연속 실행이 1차·2차를 1분 간격 매수 → 백테스트(주봉 1단계)와 다름. 같은 주엔 1단계만."""
    px = {"000002": (12500.0, "d")}                                             # +25% — 1·2차 조건 모두 충족
    p_after1 = P(added=True, adds=1, peak=12500, stop=10000, last_add="2026-11-19")
    o, notes, _ = B.decide(L0({"000002": p_after1}, cash=3_000_000), PLAN, px, BM, today=date(2026, 11, 20))
    assert not [x for x in o if "ADD" in x["cid"]] and any("이번 주 이미 불타기" in n for n in notes)
    o, _, _ = B.decide(L0({"000002": p_after1}, cash=3_000_000), PLAN, px, BM, today=date(2026, 11, 23))   # 다음 주 월요일
    assert [x["cid"] for x in o if "ADD" in x["cid"]][0].endswith("ADD2")


def test_apply_fill_records_last_add(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "TRADES", tmp_path / "trades.jsonl")              # 실제 매매 기록에 쓰지 않게
    L = L0({"000002": P(added=False, adds=0)})
    B.apply_fill(L, dict(sym="000002", side="BUY", name="X", why="불타기 1차", cid="000002-x-ADD1"), 1, 11000.0, 1.0, "2026-11-12")
    p = L["KR"]["positions"]["000002"]
    assert p["adds"] == 1 and p["last_add"] == "2026-11-12"


def test_settle_pending_before_reconcile(tmp_path, monkeypatch):
    """2026-11-12 — 시가 주문이 체결된 뒤 실행하면 토스 수량 > 원장(pending). 체결을 먼저 반영해야 대조가 맞는다."""
    monkeypatch.setattr(B, "TRADES", tmp_path / "trades.jsonl")
    L = L0({"000001": P(shares=3, added=False, adds=0)})            # 불타기 주문이 시가에 체결된 경우
    o = dict(sym="000001", side="BUY", name="가나", why="불타기 1차", cid="000001-x-ADD1", quantity=2, px=10000)
    L["pending"]["000001-x-ADD1"] = dict(orderId="A1", o=o, at="2026-11-12")

    class T:
        def order(self, acct, oid):
            return {"execution": {"filledQuantity": 2, "averageFilledPrice": 10050, "commission": 3}}
    toss = [{"sym": "000001", "qty": 5, "market": "KR"}]
    diff_before, _ = B.reconcile(L["KR"]["positions"], toss)
    assert diff_before                                       # 예전 순서라면 여기서 '불일치 → 중단'
    msg = []
    assert B.settle_pending(L, T(), "acct", "2026-11-12", msg) == 1
    assert not L["pending"] and L["KR"]["positions"]["000001"]["shares"] == 5
    diff_after, _ = B.reconcile(L["KR"]["positions"], toss)
    assert not diff_after
