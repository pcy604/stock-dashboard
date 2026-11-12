import datetime as dt
import ui_home as U


def test_last_session_weekday_before_close():
    assert U.last_session(dt.datetime(2026, 11, 12, 10, 0)) == "2026-11-11"     # 목 10시 → 수
    assert U.last_session(dt.datetime(2026, 11, 12, 16, 0)) == "2026-11-12"     # 목 16시 → 목


def test_last_session_weekend_and_monday():
    assert U.last_session(dt.datetime(2026, 11, 15, 12, 0)) == "2026-11-13"     # 일 → 금
    assert U.last_session(dt.datetime(2026, 11, 16, 9, 0)) == "2026-11-13"      # 월 장중 → 금


def test_date_items_flags_stale():
    now = dt.datetime(2026, 11, 12, 10, 40)
    it = {k: o for k, v, o in U.date_items(now, "2026-11-10", "2026-11-11", "2026-11-07", "2026-11-11 09:11")}
    assert it["한국 종가"] and it["봇 실행"] and not it["주간 판정"]
    assert "봇 실행" not in {k for k, v, o in U.date_items(now, "2026-11-11", "2026-11-11", "2026-11-07")}   # 종합(공개)엔 봇 없음
    ok = {k: o for k, v, o in U.date_items(now, "2026-11-11", "2026-11-11", "2026-11-07", "2026-11-12 09:11")}
    assert not any(ok.values())


def test_rule_checkpoints_gate_distance():
    idx = [{"name": "코스피", "close": 5375.36, "gate5w": {"live_gap": -1.85}}]
    r = U.rule_checkpoints(idx, {"breadth_all": {"up": 70, "down": 30, "flat": 0}},
                           {"KOSPI": {"d1": 6729.0, "d5": -54713.0}}, [])
    assert "5,477" in r[0] and "1.9%" in r[0]          # 5375.36/(1-0.0185) = 5,476.6
    assert "70%" in r[1] and "추세 전환" in r[2]


def test_rule_checkpoints_flow_uses_today_provisional():
    r = U.rule_checkpoints([], {"flow": {"KOSPI": {"외국인": 3704.0}}},
                           {"KOSPI": {"date": "2026-11-11", "d1": 6729.0, "d5": -54713.0}}, [])
    assert "오늘 잠정 +0.37조" in r[0] and "11-11까지" in r[0]
