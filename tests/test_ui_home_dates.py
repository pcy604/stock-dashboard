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
    assert it["한국 종가"] and it["봇 실행"] and not it["계획표"]
    ok = {k: o for k, v, o in U.date_items(now, "2026-11-11", "2026-11-11", "2026-11-07", "2026-11-12 09:11")}
    assert not any(ok.values())
