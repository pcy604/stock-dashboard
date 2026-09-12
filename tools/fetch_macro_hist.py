# -*- coding: utf-8 -*-
"""
백테스트용 매크로 시계열 수집 — data/macro_hist.parquet

왜 따로 받는가
  대시보드의 macro_inputs() 는 **최근 값만** 본다(국면 표시가 목적이라 그걸로 충분하다).
  백테스트는 2018~2026 주차마다 "그 시점에 알 수 있던 값"이 필요하다.
  같은 FRED 계열을 전 구간으로 받아 주봉으로 맞춘다.

받는 것 — 전부 대시보드 매크로 탭이 이미 쓰는 지표다
  BAMLH0A0HYM2  하이일드 OAS(신용 스프레드) — 위험자산 스트레스의 대표 지표
  VIXCLS        변동성 지수
  T10Y2Y        장단기 금리차(10년−2년)
  UNRATE        실업률 → 삼의 법칙(12개월 최저 대비 상승폭)
  INDPRO        산업생산 → 실적 사이클 대용
  FEDFUNDS      기준금리
  M2SL          통화량

⚠️ 발표 시차(look-ahead)
  월간 지표(UNRATE·INDPRO·FEDFUNDS·M2SL)는 **다음 달에 발표된다.**
  그 주차에 실제로 알 수 있던 값만 쓰려면 한 달 밀어야 한다 — shift 로 처리한다.
  일간 지표(하이일드·VIX·금리차)는 당일 알 수 있으므로 밀지 않는다.
  이걸 빼먹으면 미래를 보고 매매한 결과가 나온다.

CLI
  python tools/fetch_macro_hist.py
"""
import os
import sys
import time

import pandas as pd
import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
OUT = os.path.join(BASE, "data", "macro_hist.parquet")

# (FRED 코드, 발표 지연, 단위)  M=개월 W=주
# ⚠️ ISM 제조업 PMI(NAPM)는 FRED 에서 받을 수 없다. ISM 이 2016년 라이선스를
#    회수해 계열이 내려갔다. 대체재를 쓴다 — CFNAI(시카고연준 국가활동지수, 85개
#    월간 지표의 합성)와 NEWORDER(비국방 자본재 신규수주), AWHMAN(제조업 주당
#    근로시간, ISM 과 같은 선행 노동 지표). 같은 것이 아니라는 점은 명시한다.
SERIES = [
    # ── 일간 (당일 알 수 있다) ──────────────────────────
    ("BAMLH0A0HYM2", 0, "M"),   # 하이일드 OAS — 2023-09 부터만 있다
    ("VIXCLS", 0, "M"),
    ("T10Y2Y", 0, "M"),
    ("T10Y3M", 0, "M"),         # 10년−3개월. 침체 예측력은 이쪽이 더 낫다는 연구가 많다
    ("DGS10", 0, "M"),          # 미국 10년물 금리 — 성장주 할인율
    # ── 주간 (발표 1주 지연) ────────────────────────────
    ("NFCI", 1, "W"),           # 시카고연준 금융상황지수. 0 초과 = 긴축적
    ("ANFCI", 1, "W"),          # 경기 조정판 — 경제 상황으로 설명되는 부분을 뺀 것
    ("NFCICREDIT", 1, "W"),     # 신용 하위지수. 하이일드 OAS 의 장기 대용
    ("NFCIRISK", 1, "W"),       # 위험 하위지수
    ("ICSA", 1, "W"),           # 주간 신규실업수당 — 실업률보다 훨씬 빠른 노동 지표
    # ── 월간 ───────────────────────────────────────────
    ("UNRATE", 1, "M"),
    ("INDPRO", 1, "M"),
    ("FEDFUNDS", 1, "M"),
    ("M2SL", 1, "M"),
    ("CFNAI", 2, "M"),          # ISM 대용 ①. 익월 말 발표라 2개월 민다
    ("NEWORDER", 2, "M"),       # ISM 대용 ② 신규수주
    ("AWHMAN", 1, "M"),         # ISM 대용 ③ 제조업 근로시간
]


def pull(sid, key):
    url = "https://api.stlouisfed.org/fred/series/observations"
    p = dict(series_id=sid, api_key=key, file_type="json",
             observation_start="2015-01-01")
    for _ in range(3):
        try:
            r = requests.get(url, params=p, timeout=20)
            r.raise_for_status()
            obs = r.json()["observations"]
            rows = [(o["date"], float(o["value"])) for o in obs if o["value"] != "."]
            if rows:
                s = pd.Series({pd.Timestamp(d): v for d, v in rows}).sort_index()
                return s
        except Exception as e:
            print(f"  {sid} 재시도: {str(e)[:50]}", flush=True)
            time.sleep(2)
    return None


def main():
    # config.py 에는 FRED_KEY 정의가 없다(대시보드가 따로 읽는다). 파일을 직접 본다.
    key = os.environ.get("FRED_KEY", "")
    if not key:
        kp = os.path.join(BASE, "data", ".fred_key")
        if os.path.exists(kp):
            key = open(kp, encoding="utf-8").read().strip()
    if not key:
        print("[ERROR] FRED_KEY 가 없다. data/.fred_key 또는 환경변수를 확인해라.")
        return 1

    cols = {}
    for sid, lag, unit in SERIES:
        s = pull(sid, key)
        if s is None or s.empty:
            print(f"  [WARN] {sid} 실패 — 건너뛴다", flush=True)
            continue
        # 주봉(월요일)으로 맞춘다. 월간은 발표 지연만큼 민다.
        if lag:
            s.index = s.index + (pd.DateOffset(months=lag) if unit == "M"
                                 else pd.DateOffset(weeks=lag))
        w = s.resample("W-MON", label="left", closed="left").last().ffill()
        cols[sid] = w
        print(f"  {sid:<14}{len(s):>6}개 → 주봉 {len(w):>4}개 "
              f"({s.index[0].date()}~{s.index[-1].date()}) 지연 {lag}{unit}", flush=True)

    if not cols:
        print("[ERROR] 하나도 못 받았다.")
        return 1
    df = pd.DataFrame(cols).sort_index()
    df.to_parquet(OUT)
    print(f"\n→ {OUT}  ({len(df)}주 · {len(df.columns)}지표)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
