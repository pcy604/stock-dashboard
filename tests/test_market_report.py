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
print("ALL PASS")
