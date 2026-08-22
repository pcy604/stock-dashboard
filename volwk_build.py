# -*- coding: utf-8 -*-
"""
주봉 거래량 패널 재생성 — data/_volwk.parquet

왜 별도 파일인가:
  L/S 규칙의 핵심 조건이 **거래량 전주 대비 배수**(vw)다. 20주 평균(vol_x_20w)이
  아니다 — 20주 평균으로 보면 대시세 출발점이 0.86배(조용함)로 나와 아무것도
  안 잡힌다. factor_weekly 에는 이 '전주 대비' 컬럼이 없어서 가격 캐시에서
  주봉 거래량 패널을 따로 만든다.

⚠️ 2026-08-22 사고 — 이 스크립트가 주간 사이클에 없었다
  L/S 를 도입한 2026-08-18 에 이 빌더는 `_volbuild.py` 라는 임시 스크립트로만
  존재했고 leaders_weekly.sh 에 들어가지 않았다. 결과:
    · factor_weekly 는 2026-08-17 까지 갱신됨
    · _volwk.parquet 는 2026-08-10 에 정지
    · 08-17 주차의 vw 가 전부 NaN → `vw < 1.5` 가 항상 거짓
    · **"이번 주 신호 0종"이 화면에 떴고, 사이클은 EXIT=0 으로 성공을 보고했다**
  '초록불인데 실은 죽어 있는' 전형이다. 신호 0종은 진짜 0이 아니라 가짜 0이었다.
  반드시 factor_weekly 적재 **직후**, L/S 발행 **직전**에 돌아야 한다.

CLI
  python volwk_build.py
"""
import os
import sys

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, "data", "leaders_cache")
OUT = os.path.join(BASE, "data", "_volwk.parquet")


def build():
    rows = []
    files = [f for f in os.listdir(CACHE)
             if f.startswith("px_") and f.endswith(".csv")]
    for i, f in enumerate(files, 1):
        sym = f[3:-4]
        try:
            d = pd.read_csv(os.path.join(CACHE, f), index_col=0, parse_dates=True)
        except Exception:
            continue
        if "Volume" not in d.columns or not len(d):
            continue
        rows.append(pd.DataFrame({"as_of": d.index, "vol_wk": d.Volume.values,
                                  "sym": sym}))
        if i % 500 == 0:
            print(f"  {i}/{len(files)}", flush=True)
    if not rows:
        print("[ERROR] 가격 캐시에서 거래량을 하나도 못 읽었다. 캐시를 먼저 채워라.")
        return 1
    v = pd.concat(rows, ignore_index=True)
    v.to_parquet(OUT, index=False)
    print(f"→ {OUT}  {len(v):,}행 · {v.sym.nunique():,}종 · 최신 {v.as_of.max().date()}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(build())
