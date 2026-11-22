# -*- coding: utf-8 -*-
"""미국 시계열 접합(factor_weekly v13y + v1) 정답 테스트 (2026-11-22).

왜 접합하나 — 실측부터:
  `v1` 은 **증분 적재**라 새 주차만 붙이고 과거 행을 고치지 않는다. 그 뒤 분할이 일어나면
  `prices`(일봉)는 수정주가로 **과거까지** 보정되는데 factor_weekly 의 과거 행은 분할 전 값으로 남는다.
  겹침 구간(2018-01~2026-08, 959,977행)을 일봉 원본과 대조한 결과:
    · v1 이 0.5% 넘게 어긋난 행 105,618 (11.0%) · 252종 — AAPL·BAC·AMGN·ADM·AEP 포함
    · v13y 가 어긋난 종목 **0**
    · 재무 열(revenue·op_income·gross_profit·net_income·rev_yoy·rev_qoq·gpm·opm·period_end)은 불일치 0
    · 접합부(2017-12 v13y → 2018-01 v1) 주간 변동률 중앙 1.018 · 99%분위 1.228 · ×5 초과 0종
  → 통째로 쌓은 판을 앞에, 증분 판을 뒤에. 오류도 결측도 없이 틀린 가격이 돌던 것을 막는다.

이 테스트가 지키는 것: 접합 우선순위 · 행이 불어나지 않음 · 접합이 꺼지는 경로 · 낡음 기록.
"""
import os
import sqlite3
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))

import leaders_accel as A      # noqa: E402
import quant_panel as Q        # noqa: E402

def _db(dirpath, rows):
    """rows: (factor_ver, as_of, sym, close) — 나머지 열은 채워 넣는다.

    ⚠️ 표는 **실제 `leaders_schema.sql` 로** 만든다. 테스트가 자기 CREATE TABLE 을 들고 있으면
    열 타입이 어긋나(전부 TEXT 였다) 숫자 연산이 테스트에서만 깨지고, 스키마가 바뀌어도 모른다."""
    dirpath = __import__("pathlib").Path(dirpath)
    dirpath.mkdir(parents=True, exist_ok=True)
    p = dirpath / "market.db"
    c = sqlite3.connect(str(p))
    c.executescript(open(os.path.join(ROOT, "leaders_schema.sql"), encoding="utf-8").read())
    for ver, as_of, sym, close in rows:
        c.execute("INSERT INTO factor_weekly (as_of, sym, name, close, factor_ver, period_end, "
                  "revenue, op_income, gross_profit, net_income) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (as_of, sym, sym, float(close), ver, as_of, 1e9, 1e8, 5e8, 1e8))
    c.commit(); c.close()
    return p


def _load(tmp_path, rows, vers, monkeypatch):
    monkeypatch.setattr(A, "DB", str(_db(tmp_path, rows)))
    return A.load(vers=vers)


def test_front_ver_wins_on_overlap(tmp_path, monkeypatch):
    """겹치는 (sym, as_of)는 **앞 ver** 이 이긴다 — 통째로 쌓은 판이 옳았다(실측 252종 대 0종)."""
    d = _load(tmp_path, [("v13y", "2019-01-07", "AAPL", "10"),
                         ("v1", "2019-01-07", "AAPL", "30")], ("v13y", "v1"), monkeypatch)
    assert len(d) == 1
    assert float(d.close.iloc[0]) == 10.0


def test_order_matters(tmp_path, monkeypatch):
    """우선순위를 뒤집으면 뒤집힌 값이 나와야 한다 — 우연히 맞은 게 아님을 보인다."""
    d = _load(tmp_path, [("v13y", "2019-01-07", "AAPL", "10"),
                         ("v1", "2019-01-07", "AAPL", "30")], ("v1", "v13y"), monkeypatch)
    assert float(d.close.iloc[0]) == 30.0


def test_incremental_fills_after_base_ends(tmp_path, monkeypatch):
    """통째 판이 끝난 뒤 구간은 증분 판이 메운다 — 이게 '패널이 낡는' 문제를 푸는 지점이다."""
    d = _load(tmp_path, [("v13y", "2019-01-07", "AAPL", "10"),
                         ("v1", "2026-11-16", "AAPL", "250")], ("v13y", "v1"), monkeypatch)
    assert len(d) == 2
    assert str(d.as_of.max().date()) == "2026-11-16"


def test_seam_does_not_duplicate_rows(tmp_path, monkeypatch):
    """행이 불어나면 백테스트가 같은 주를 두 번 체결한다."""
    rows = [(v, f"2019-0{m}-07", s, "10")
            for v in ("v13y", "v1") for m in (1, 2, 3) for s in ("AAPL", "MSFT")]
    d = _load(tmp_path, rows, ("v13y", "v1"), monkeypatch)
    assert len(d) == 6
    assert not d.duplicated(["sym", "as_of"]).any()


def test_single_ver_keeps_old_behaviour(tmp_path, monkeypatch):
    """기존 호출부(대시보드·발행)는 ver 하나만 넘긴다 — 동작이 바뀌면 안 된다."""
    d = _load(tmp_path, [("v13y", "2019-01-07", "AAPL", "10"),
                         ("v1", "2019-01-07", "AAPL", "30")], ("v1",), monkeypatch)
    assert len(d) == 1 and float(d.close.iloc[0]) == 30.0


def test_missing_ver_is_skipped_not_fatal(tmp_path, monkeypatch):
    d = _load(tmp_path, [("v1", "2019-01-07", "AAPL", "30")], ("v13y", "v1"), monkeypatch)
    assert len(d) == 1


def test_all_vers_missing_is_fatal(tmp_path, monkeypatch):
    """조용히 빈 프레임을 돌려주면 패널이 0행으로 만들어지고 백테스트가 '매매 0건'을 낸다."""
    with pytest.raises(SystemExit):
        _load(tmp_path, [("v1", "2019-01-07", "AAPL", "30")], ("zzz",), monkeypatch)


# ──────────────────────────────────────────────────────────────────────
# ver 고르기 — 환경변수가 접합을 끄는 경로
# ──────────────────────────────────────────────────────────────────────
def test_factor_ver_env_disables_the_seam(tmp_path, monkeypatch):
    """⚠️ 이게 11-22 의 고장 그 자체였다 — quant-panel.yml 이 `FACTOR_VER=v13y` 로 못 박아
    멈춘 판 하나만 쓰게 했고, 미국 패널이 10-26 에 정지했다. 동작은 남기되 의도적일 때만 켜진다."""
    monkeypatch.setattr(Q, "ROOT", str(tmp_path))
    _db(tmp_path / "data", [("v13y", "2019-01-07", "A", "1"), ("v1", "2026-11-16", "A", "2")])
    monkeypatch.setenv("FACTOR_VER", "v1")
    assert Q._us_vers() == ("v1",)
    monkeypatch.delenv("FACTOR_VER")
    assert Q._us_vers() == ("v13y", "v1")


def test_workflow_does_not_pin_factor_ver():
    """워크플로가 FACTOR_VER 를 다시 못 박으면 접합이 꺼지고 패널이 조용히 낡는다."""
    y = open(os.path.join(ROOT, ".github", "workflows", "quant-panel.yml"), encoding="utf-8").read()
    run = [ln for ln in y.splitlines() if "quant_panel.py" in ln and "run:" in ln]
    assert run, "패널 빌드 스텝을 못 찾았다"
    for ln in run:
        assert "FACTOR_VER" not in ln, f"FACTOR_VER 를 넘기면 접합이 꺼진다: {ln.strip()}"


# ──────────────────────────────────────────────────────────────────────
# 낡음 기록 — 조용히 썩지 않게
# ──────────────────────────────────────────────────────────────────────
def test_seam_note_records_base_staleness(tmp_path, monkeypatch):
    """통째 판이 낡은 만큼 증분 판이 메우고, 그 구간은 분할 썩음에 노출된다.
    데이터는 '최신'이라 어떤 경보도 울리지 않는다 → 숫자로 남겨야 한다."""
    monkeypatch.setattr(Q, "ROOT", str(tmp_path))
    _db(tmp_path / "data", [("v13y", "2026-08-31", "A", "1"), ("v1", "2026-11-16", "A", "2")])
    n = Q._seam_note(("v13y", "v1"))
    assert n["base_stale_days"] == 77
    assert n["filled_by_incremental"] == "2026-08-31 ~ 2026-11-16"
    assert "분할" in n["note"]


def test_seam_note_single_ver_has_no_staleness(tmp_path, monkeypatch):
    monkeypatch.setattr(Q, "ROOT", str(tmp_path))
    _db(tmp_path / "data", [("v1", "2026-11-16", "A", "2")])
    n = Q._seam_note(("v1",))
    assert "base_stale_days" not in n


# ──────────────────────────────────────────────────────────────────────
# 분할 썩음 측정기 자체
# ──────────────────────────────────────────────────────────────────────
def _db_with_prices(tmp_path, fw, px):
    p = _db(tmp_path, fw)
    #   prices 는 leaders_schema.sql 에 없다(db.py 쪽) → 여기서 만든다
    c = sqlite3.connect(str(p))
    c.execute("CREATE TABLE IF NOT EXISTS prices (sym TEXT, market TEXT, date TEXT, close REAL)")
    c.executemany("INSERT INTO prices VALUES (?,?,?,?)", px)
    c.commit(); c.close()
    return p


def test_split_rot_finds_the_stale_price(tmp_path, monkeypatch):
    """주봉 종가가 일봉 원본의 3.07배 — WLFC 2019 에서 실제로 본 모양(분할 보정 미전파)."""
    monkeypatch.setattr(A, "DB", str(_db_with_prices(
        tmp_path,
        [("v1", "2019-05-13", "WLFC", "55.58"), ("v1", "2019-05-20", "OK", "10.0")],
        [("WLFC", "US", "2019-05-17", 18.09), ("OK", "US", "2019-05-24", 10.0)])))
    r = A.split_rot(ver="v1", since="2018-01-01")
    assert r["rows"] == 2 and r["rot_rows"] == 1 and r["syms"] == ["WLFC"]


def test_split_rot_ignores_weeks_without_daily(tmp_path, monkeypatch):
    """일봉이 없는 주차를 '썩음'으로 세면 결측이 고장으로 보고된다 — 거래정지·상장 전 주차가 그렇다."""
    monkeypatch.setattr(A, "DB", str(_db_with_prices(
        tmp_path, [("v1", "2019-05-13", "X", "100.0")], [])))
    assert A.split_rot(ver="v1", since="2018-01-01")["rows"] == 0


def test_split_rot_tolerance(tmp_path, monkeypatch):
    """0.5% 안쪽은 반올림·종가 선택 차이다 — 썩음으로 세지 않는다."""
    monkeypatch.setattr(A, "DB", str(_db_with_prices(
        tmp_path, [("v1", "2019-05-13", "X", "100.3")],
        [("X", "US", "2019-05-17", 100.0)])))
    assert A.split_rot(ver="v1", since="2018-01-01")["rot_rows"] == 0
