"""시황 리포트 — 장중 미완성 봉 제거 · AI 글의 근거 없는 숫자 검사 (2026-10-21). 네트워크 없이 돈다."""
import os, sys
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
import market_report as M

s = pd.Series([1.0, 2.0, 3.0], index=pd.to_datetime(["2026-10-19", "2026-10-20", "2026-10-21"]))
# 한국 09:26(=00:26 UTC) → 코스피 오늘 봉은 장중이라 버린다
assert len(M.drop_open_bar(s, "^KS11", datetime(2026, 10, 21, 0, 26, tzinfo=timezone.utc))) == 2
# 한국 16:00 이후면 확정 종가 → 유지
assert len(M.drop_open_bar(s, "^KS11", datetime(2026, 10, 21, 7, 5, tzinfo=timezone.utc))) == 3
# 미국: 뉴욕 10-21 12:00(=16:00 UTC) 장중 → 버림, 10-21 21:30 UTC(=17:30 뉴욕) → 유지
assert len(M.drop_open_bar(s, "^GSPC", datetime(2026, 10, 21, 16, 0, tzinfo=timezone.utc))) == 2
assert len(M.drop_open_bar(s, "^GSPC", datetime(2026, 10, 21, 21, 30, tzinfo=timezone.utc))) == 3
assert len(M.drop_open_bar(s, "^GSPC", datetime(2026, 10, 21, 20, 10, tzinfo=timezone.utc))) == 3, "서머타임 마감 +10분이면 오늘 봉 유지"
# 미국 장 시작 전(뉴욕 날짜가 아직 10-20) 이면 마지막 봉이 '오늘'이 아니라서 유지
assert len(M.drop_open_bar(s, "^GSPC", datetime(2026, 10, 21, 2, 0, tzinfo=timezone.utc))) == 3
# 환율은 24시간 — 그대로
assert len(M.drop_open_bar(s, "KRW=X", datetime(2026, 10, 21, 0, 26, tzinfo=timezone.utc))) == 3
print("✅ 장중 미완성 봉 제거")

f = {"indices": [{"name": "코스피", "d1": -1.95, "d5": -6.29}], "stocks": {"KR": {"breadth_up": 27}, "US": {"breadth_up": 67}},
     "signals": {"market_direction": {"KR": "하락추세 (200일선 -13.6%)"}}, "verdict": {"core_gap_200d": 5.66}}
assert M.unbacked_pcts("코스피 -1.9%, 5일 -6.3%, 200일선 -13.6%, 이격 5.7%, 상승 비율 27%·67%", f) == []
assert M.unbacked_pcts("상승 종목 비율: 한국 9.1%, 미국 9.5%", f) == ["9.1%", "9.5%"]
print("✅ AI 글 근거 없는 숫자 검사 (10-21 실제 오류 재현)")
f2 = dict(kind="daily", generated="2026-10-21 21:40", verdict={},
          indices=[{"name": "코스피", "close": 5900.0, "d1": 4.4, "d5": 1.0, "m1": -10.0, "from_52w_high": -30.0}],
          stocks={}, signals={"market_direction": {"KR": "하락추세", "US": "상승추세"}, "accel_week": "2026-10-12", "accel_new": []})
md = M.compose("## 한 줄 요약\n코스피 반등.\n## 체크포인트\n1. 200일선 확인할 것.", f2)
assert "## 한 줄 요약\n코스피 반등." in md and "| 코스피 | 5,900.0 | +4.4%" in md and "## 체크포인트" in md, md
assert md.count("※") == 1
print("✅ AI 문장 + 숫자 템플릿 합성")
# 한국 장 마감 리포트 — 오늘자 KRX 목록일 때만 종목 등락, 아니면 생략
import sys as _s, types
fake = pd.DataFrame({"Code": ["005930", "000660", "123456"], "Name": ["삼성전자", "SK하이닉스", "소형주"],
                     "Marcap": [1e15, 9e14, 1e11], "ChagesRatio": [4.4, -1.2, 30.0]})
fake.attrs = {"asof": "2026-10-21"}
_s.modules["krx_listing"] = types.SimpleNamespace(stock_listing=lambda *a, **k: fake)
import os as _os, tempfile as _tf
_os.environ["MR_BREADTH_LOG"] = _os.path.join(_tf.mkdtemp(), "kr_breadth_log.json")   # 실제 results/ 에 쓰지 않게(2026-11-12)
k = M.kr_today_facts("2026-10-21")["KR"]
assert k["basis"] == "d1" and k["top"][0]["name"] == "삼성전자" and k["universe"] == 2 and k["breadth_up"] == 50, k
assert M.kr_today_facts("2026-10-22") == {}, "어제 목록을 오늘 것으로 쓰지 않는다"
assert k["breadth_all"] == {"up": 2, "down": 1, "flat": 0, "limit_up": 1, "limit_down": 0}, k["breadth_all"]
assert [m["name"] for m in k["megacaps"]][:2] == ["삼성전자", "SK하이닉스"], k["megacaps"]
assert M._sec_short("일차전지 및 이차전지 제조업") == "2차전지" and M._sec_short("가구 제조업") == "가구"
fk = dict(kind="kr", generated="2026-10-21 15:52", verdict={},
          indices=[{"name": "코스피", "sym": "^KS11", "date": "2026-10-21", "close": 5900.0, "d1": 4.4, "d5": 1.0, "m1": -10.0, "from_52w_high": -30.0}],
          stocks={"KR": k}, signals={"market_direction": {"KR": "하락추세"}})
t = M.template(fk)
assert "한국 장 마감 시황" in t and "오늘 수익률" in t and "US" not in t and "이익가속" not in t, t
print("✅ 한국 장 마감 리포트(오늘 등락·휴장 판정 재료)")
# 52주 신고가(장중 고가 ≥ 52주 고가 — hi52 가 오늘 고가를 이미 포함해도 잡힌다) · 특징주 · 거래대금 상위 — 2026-11-11
al = pd.DataFrame({"Code": ["000001", "000002", "000003", "000004"], "Name": ["신고가A", "장중만B", "급등C", "상한D"],
                   "Marcap": [5e11, 5e11, 3e11, 2e11], "Close": [110.0, 99.0, 50.0, 30.0], "High": [110.0, 99.5, 51.0, 30.0],
                   "Amount": [9e10, 1e10, 5e10, 2e10], "_r": [3.0, 5.0, 12.0, 30.0]})
M._j = lambda p: {"date": "2026-11-11", "stocks": [
    {"market": "KR", "sym": "000001", "hi52": 110.0}, {"market": "KR", "sym": "000002", "hi52": 100.0}]}
mv = M.kr_movers(al, "2026-11-11")
assert mv["new_high_52w"]["n"] == 1 and mv["new_high_52w"]["top"][0]["name"] == "신고가A" and mv["new_high_52w"]["top"][0]["close_high"], mv["new_high_52w"]
assert [r["name"] for r in mv["featured"]] == ["급등C", "상한D"] and mv["featured"][1]["tag"] == "상한가", "거래대금 순"
assert mv["featured"][0]["tag"] == "거래대금 2위" and mv["turnover_top"][0]["amt_b"] == 900, mv
assert "new_high_52w" not in M.kr_movers(al, "2026-11-12"), "어제 고점표로 오늘 신고가를 판정하지 않는다"
M._j = lambda p: {"kr": {"000001": {"themes": ["HBM"]}, "000002": {"themes": ["HBM", "SPAC 테마"]}, "000003": {"themes": ["HBM"]},
                        "000004": {"themes": ["HBM", "기타"]}}} if "sector_detail" in p else {}
th = M.kr_themes(al, min_theme=2)
assert th["themes_top"][0]["name"] == "HBM" and th["themes_top"][0]["n"] == 4 and th["themes_top"][0]["lead"][0]["name"] == "상한D", th
assert all("SPAC" not in x["name"] for x in th["themes_top"]), "스팩 제외"
print("✅ 52주 신고가·특징주·거래대금 상위 · 오늘의 테마")
print("ALL PASS")
# 업종 히트맵 묶음(네이버 업종 → 16묶음) — 2026-11-11
assert M._hm_group("반도체와반도체장비") == "반도체" and M._hm_group("손해보험") == "금융" and M._hm_group("전기제품") == "2차전지·전기제품"
assert M._hm_group("전기장비") == "전력기기" and M._hm_group("자동차부품") == "자동차" and M._hm_group(None) == "기타"
M._j = lambda p: {"kr": {"005930": {"upjong": "반도체와반도체장비"}}}
hm = M.kr_heatmap(pd.DataFrame({"Code": ["005930", "999999"], "Name": ["삼성전자", "모름"], "Marcap": [1.2e15, 2e12], "_r": [2.8, -1.0]}), "2026-11-11")
assert hm[0] == dict(name="삼성전자", sym="005930", sec="반도체", mc=1200.0, ret=2.8) and hm[1]["sec"] == "기타", hm
print("✅ 업종 히트맵 묶음")
print("ALL PASS")


def test_chat_context_keeps_korea_close():
    """2026-11-12 사고: 12,000자 절단에 한국 장 마감 자료가 통째로 잘렸다."""
    import json, pathlib, market_report as _M
    real = json.loads((pathlib.Path(__file__).parent.parent / "results" / "market_report.json").read_text(encoding="utf-8"))
    old, _M._j = _M._j, (lambda p: real)
    try:
        c = _M.chat_context()
    finally:
        _M._j = old
    assert "한국 장 마감" in c and "themes_top" in c and "heatmap" not in c
    assert len(c) <= 12000
