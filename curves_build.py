# -*- coding: utf-8 -*-
"""
가격 곡선 통합 발행 — results/price_curves.json

왜 별도 파일인가 (2026-08-25)
  L/S 심층조회(leaders_symbol_detail.json)와 이익가속 심층조회(leaders_accel.json)가
  **같은 종목의 같은 주봉 종가를 각자 저장**하고 있었다. 674종이 겹쳤다.
    leaders_symbol_detail  곡선 364,026점
    leaders_accel          곡선 323,315점
  두 파일의 날짜 축(451주차)은 완전히 같았으므로 곡선만 떼어 한 파일로 합친다.
  각 규칙 JSON 은 곡선 대신 `spans`(종목 → [첫 신호, 마지막 신호] 인덱스)만 싣고,
  이 스크립트가 합집합 구간의 곡선을 만든다.

  ⚠️ 저장소 사정 — .git 이 580MB 다(gc 전 1,006MB). 결과 JSON 을 매주 커밋해온 탓이다.
     히스토리 1위는 guru_insights.json(518MB · 734회 커밋)이고 곡선은 그 다음이다.

창 규칙
  각 규칙의 (첫 신호 − 26주) ~ (마지막 신호 + 104주) 를 구하고, 두 규칙에 다 걸린
  종목은 **합집합**(더 이른 시작 ~ 더 늦은 끝)을 쓴다.
  ⚠️ 그래서 절감폭이 단순 중복 제거보다 작다 — 겹치는 674종은 더 넓은 창을 갖게 된다.
  깨지는 지점: 오래전에만 신호가 났던 종목은 최근 흐름이 안 보인다. 신호 후 2년까지는
  보이므로 판단에는 대체로 충분하다고 봤다.

의존 순서 (leaders_weekly.sh)
  leaders_accel.py → leaders_ab.py → leaders_symbol.py → **curves_build.py**
  ⚠️ 반드시 두 발행 스크립트 **뒤에** 돌아야 한다. spans 를 읽어야 하기 때문이다.
     순서가 어긋나면 곡선이 지난주 신호 기준으로 만들어지고, 화면에서는
     "차트에 최근 ▲ 가 안 보인다"로 나타난다 — 조용히 틀린다.

CLI
  python curves_build.py
"""
import json
import os
import sys

import sqlite3

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "market.db")
OUT = os.path.join(BASE, "results", "price_curves.json")
SRC = [os.path.join(BASE, "results", f)
       for f in ("leaders_accel.json", "leaders_symbol_detail.json")]
PRE, POST = 26, 104          # 첫 신호 앞 26주 ~ 마지막 신호 뒤 104주


def build():
    dates, spans = None, {}
    for p in SRC:
        if not os.path.exists(p):
            print(f"[WARN] 없음: {os.path.basename(p)} — 건너뛴다")
            continue
        d = json.load(open(p, encoding="utf-8"))
        sp = d.get("spans")
        if not sp:
            print(f"[WARN] spans 없음: {os.path.basename(p)} — 먼저 재발행해야 한다")
            continue
        if dates is None:
            dates = d["dates"]
        elif d["dates"] != dates:
            print(f"[ERROR] 날짜 축이 다르다: {os.path.basename(p)}. 통합할 수 없다.")
            return 1
        for s, (lo, hi) in sp.items():
            a, b = spans.get(s, (10**9, -1))
            spans[s] = (min(a, lo), max(b, hi))       # 두 규칙의 합집합
    if not spans:
        print("[ERROR] spans 를 하나도 못 읽었다. 발행 스크립트를 먼저 돌려라.")
        return 1

    # ⚠️ 종가는 반드시 발행 스크립트와 **같은 소스**(market.db factor_weekly)에서 읽는다.
    #    2026-08-25 최초 구현에서 data/leaders_cache/px_*.csv 를 봤다가 62종의 곡선이
    #    통째로 빠졌다 — 그 종목들은 캐시에 파일이 없었다. 화면에서는 "차트가 안 뜬다"로
    #    나타난다. 소스가 갈리면 조용히 어긋난다.
    if not os.path.exists(DB):
        print(f"[ERROR] {DB} 가 없다. 곡선은 발행 환경에서만 만들 수 있다.")
        return 1
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    px_all = pd.read_sql("SELECT as_of,sym,close FROM factor_weekly "
                         "WHERE factor_ver='v1' AND close IS NOT NULL", c)
    c.close()
    px_all["as_of"] = pd.to_datetime(px_all.as_of)
    by_sym = {k: v.set_index("as_of").close for k, v in px_all.groupby("sym")}

    D = pd.to_datetime(dates)
    ix = {t: j for j, t in enumerate(D)}
    curves, pts = {}, 0
    for i, (s, (lo, hi)) in enumerate(sorted(spans.items()), 1):
        px = by_sym.get(s)
        if px is None:
            continue
        w = D[max(0, lo - PRE):hi + POST + 1]
        ser = px.reindex(w).dropna()
        if ser.empty:
            continue
        # 로그 축으로 그리므로 유효숫자 4자리면 눈에 차이가 없다
        curves[s] = dict(i=[ix[t] for t in ser.index],
                         c=[round(float(v), 1 if v >= 100 else 2 if v >= 10 else 3)
                            for v in ser.values])
        pts += len(ser)
        if i % 400 == 0:
            print(f"  {i}/{len(spans)}", flush=True)

    out = dict(generated=str(pd.Timestamp.today().date()), dates=dates, curves=curves)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    miss = len(spans) - len(curves)
    print(f"→ {OUT}  ({os.path.getsize(OUT)/1e6:.2f} MB · {len(curves)}종 · {pts:,}점)")
    if miss:
        print(f"[WARN] 곡선을 못 만든 종목 {miss}개 — 화면에서 차트가 안 뜬다")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(build())
