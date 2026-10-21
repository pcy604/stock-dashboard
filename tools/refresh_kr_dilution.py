# -*- coding: utf-8 -*-
"""KR 잠재 희석(CB·BW·EB 발행 결정) 저장본 — data/kr_dilution.parquet (2026-10-21)

왜
  화면 서버(Streamlit Cloud)에서는 DART 가 자주 막힌다(CLAUDE.md '외부 소스'). 종목 분석의 '잠재 희석'이
  그때마다 비면 안 되니, 러너가 주 1회 전 종목분을 받아 저장한다. 화면은 실시간 → 실패 시 이 파일.
방법
  1) 공시검색 list.json(주요사항보고 B001, 3개월 창 × 최근 4년)에서 '전환사채권/신주인수권부사채권/교환사채권 발행결정'
     이 있는 회사만 고른다(전 종목 상세 호출을 피한다). 증분: 기존 파일이 있으면 마지막 실행 이후 창만 훑고,
     그 회사들만 다시 받는다.
  2) 고른 회사마다 dart_client.dilution_terms(최근 4년) → 한 행 = 한 발행 결정.
  안전장치: DART 가 안 닿으면 기존 파일을 그대로 두고 ::warning (0건 저장을 '성공'으로 찍지 않는다).
  python tools/refresh_kr_dilution.py [--full]
"""
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

import dart_client as D

OUT = ROOT / "data" / "kr_dilution.parquet"
KEYS = ('전환사채권발행결정', '신주인수권부사채권발행결정', '교환사채권발행결정')


def corps_with_filings(bgn: date, end: date) -> set:
    found, d0 = set(), bgn
    while d0 < end:
        d1 = min(d0 + timedelta(days=89), end)
        page = 1
        while True:
            j = D._get(f"{D.BASE}/list.json", {'crtfc_key': D._key(), 'pblntf_detail_ty': 'B001',
                                                'bgn_de': d0.strftime('%Y%m%d'), 'end_de': d1.strftime('%Y%m%d'),
                                                'page_no': page, 'page_count': 100}).json()
            if j.get('status') == '013':
                break
            if j.get('status') != '000':
                raise RuntimeError(f"list.json {j.get('status')} {j.get('message')}")
            for x in j.get('list') or []:
                nm = str(x.get('report_nm') or '').replace(' ', '')
                if x.get('stock_code') and any(k in nm for k in KEYS):
                    found.add((x['corp_code'], x['stock_code']))
            if page >= int(j.get('total_page') or 1):
                break
            page += 1
            time.sleep(0.15)
        d0 = d1 + timedelta(days=1)
    return found


def main(full=False):
    today = date.today()
    old = pd.read_parquet(OUT) if OUT.exists() else pd.DataFrame()
    since = today - timedelta(days=365 * 4)
    if not full and not old.empty and 'fetched' in old:
        since = max(since, pd.to_datetime(old['fetched']).max().date() - timedelta(days=7))
    try:
        corps = corps_with_filings(since, today)
    except Exception as e:
        print(f"::warning::DART 공시검색 실패 — 기존 파일 유지: {type(e).__name__}: {e}"[:300])
        return 0
    print(f"발행결정 공시 회사 {len(corps)}곳 ({since} ~ {today})")
    rows, fails = [], 0
    for i, (cc, sym) in enumerate(sorted(corps)):
        try:
            for r in D.dilution_terms(cc, years=4):
                rows.append(dict(r, sym=sym, corp_code=cc, fetched=today.isoformat()))
        except Exception as e:
            fails += 1
            print(f"  {sym} 실패: {type(e).__name__}"[:120])
        if i % 50 == 0:
            print(f"  {i}/{len(corps)}")
        time.sleep(0.12)
    if corps and fails > len(corps) * 0.5:
        print(f"::error::상세 조회 실패 {fails}/{len(corps)} — 저장하지 않음")
        return 1
    new = pd.DataFrame(rows)
    if not old.empty and not new.empty:
        old = old[~old['sym'].isin(new['sym'].unique())]     # 다시 받은 회사는 통째로 교체
    out = pd.concat([old, new], ignore_index=True) if not old.empty else new
    if out.empty:
        print("::warning::저장할 행 없음 — 파일을 만들지 않음")
        return 0
    out = out.drop_duplicates(['sym', 'kind', 'rcept_no']).sort_values(['sym', 'rcept_no'])
    out.to_parquet(OUT, index=False)
    print(f"✅ {OUT.name}: {len(out)}행 · {out['sym'].nunique()}종 (이번 갱신 {len(new)}행)")
    return 0


if __name__ == '__main__':
    sys.exit(main(full='--full' in sys.argv))
