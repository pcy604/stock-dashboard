"""
ingest_dart_quarterly.py — KR 분기 재무 적재 (DART 다중회사 주요계정)
─────────────────────────────────────────────────────────────────────
왜 필요한가:
  US 주도주 규칙⑥의 핵심 조건은 '이익 변곡(흑자전환·영업익 폭증)'인데, 이건 분기
  영업이익이 있어야 판정된다. 그런데 이 저장소의 KR 재무는 fundamentals 테이블의
  **연간 2023~2025, 835종**뿐이라 KR 규칙(KR-P1)이 순수 가격 규칙에 머물러 있었다.

어떻게:
  DART `fnlttMultiAcnt.json` 은 corp_code 를 **최대 100개씩** 묶어 받는다.
  9년 × 4보고서 × 15배치 ≈ 540콜 → 일일 한도(2만) 대비 여유. 단일회사 API로
  같은 걸 하면 47,000콜이라 사흘 걸린다.

⚠️ 누적/당분기 구분 — 실측으로 확인한 사실 (2026-08-15):
  DART **주요계정(fnlttMultiAcnt)** 의 손익 항목은 분기보고서에서 **당분기(3개월)** 값을 준다.
  사업보고서(11011)만 연간 누적이다. 즉:
     11013(1분기)=Q1 3개월 · 11012(반기)=Q2 3개월 · 11014(3분기)=Q3 3개월 · 11011(사업)=FY

  검증: 삼성전자 2023 → Q1 63.7조 · Q2 60.0조 · Q3 67.4조 · 11011 258.9조.
        Q1+Q2+Q3=191.2조, 258.9−191.2=**67.8조**로 실제 4분기 매출과 일치.
        (반기보고서가 누적이었다면 Q2 자리에 124.3조가 왔어야 한다 — 아니었다)

  따라서 개별 분기는 **Q4만 차분**하면 된다: Q4 = FY − (Q1+Q2+Q3).
  ※ '한국 분기보고서는 누적'이라는 통설은 재무제표 원문(fnlttSinglAcntAll)에는 맞지만
    이 주요계정 API에는 해당하지 않는다. 가정을 그대로 뒀다면 Q2·Q3가 부풀려져
    '영업익 폭증'이 상시 참이 되는 규칙 붕괴가 났을 것이다.

실행:  python ingest_dart_quarterly.py            # 2018~올해
       python ingest_dart_quarterly.py 2022 2024  # 연도 지정
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from datetime import date

import numpy as np
import requests

import dart_client as D

DB = 'data/market.db'
API = 'https://opendart.fss.or.kr/api/fnlttMultiAcnt.json'
BATCH = 60                         # 배치는 작게, 대신 병렬로
WORKERS = 6                        # 실측: 6워커에서 5.5배 (그 이상은 DART 부담)
# 보고서코드 → (분기번호, 누적개월수)
REPRTS = [('11013', 1, 3), ('11012', 2, 6), ('11014', 3, 9), ('11011', 4, 12)]
WANT = {'매출액': 'revenue', '영업이익': 'op_income', '당기순이익': 'net_income'}

DDL = """
CREATE TABLE IF NOT EXISTS fundamentals_q (
  sym TEXT, year INTEGER, q INTEGER,
  revenue REAL, op_income REAL, net_income REAL,   -- 1~3Q=당분기(3개월), 4=사업보고서(FY)
  fs_div TEXT, updated TEXT,
  PRIMARY KEY (sym, year, q)
);
CREATE INDEX IF NOT EXISTS ix_fq_sym ON fundamentals_q(sym, year, q);
"""


def _num(s):
    if not s or s in ('-', ''):
        return None
    try:
        return float(str(s).replace(',', ''))
    except Exception:
        return None


def fetch_batch(codes: list[str], year: int, reprt: str) -> dict:
    """{(sym, year): {revenue, op_income, net_income, fs_div}} — 연결(CFS) 우선.

    응답에 `frmtrm_amount`(전년 동기)도 들어 있어 **한 번에 2개 연도**를 얻는다.
    덕분에 연도 호출을 절반으로 줄일 수 있다(2026·2024·2022·2020·2018 → 2017~2026).
    """
    try:
        r = requests.get(API, params={'crtfc_key': D._key(), 'corp_code': ','.join(codes),
                                      'bsns_year': str(year), 'reprt_code': reprt}, timeout=40)
        j = r.json()
    except Exception:
        return {}
    if j.get('status') != '000':
        return {}
    out: dict[tuple, dict] = {}
    for row in j.get('list', []):
        sym = (row.get('stock_code') or '').strip()
        if not sym or len(sym) != 6:
            continue
        acc = WANT.get((row.get('account_nm') or '').strip())
        if not acc or (row.get('sj_div') or '') != 'IS':      # 손익계산서만
            continue
        fs = row.get('fs_div') or 'OFS'
        for yr, field in ((year, 'thstrm_amount'), (year - 1, 'frmtrm_amount')):
            v = _num(row.get(field))
            if v is None:
                continue
            cur = out.setdefault((sym, yr), {'fs_div': fs})
            # 연결(CFS)이 실체 — 별도(OFS)만 먼저 왔으면 CFS 로 갈아끼운다
            if fs == 'CFS' and cur.get('fs_div') != 'CFS':
                cur.clear(); cur['fs_div'] = 'CFS'
            elif cur.get('fs_div') == 'CFS' and fs != 'CFS':
                continue
            cur[acc] = v
    return out


def ingest(y0: int, y1: int, syms: list[str] | None = None):
    cm = D.corp_map()
    if syms is None:
        # 가격 캐시에 있는 종목만 = 실제로 쓰는 유니버스
        import glob, os
        syms = sorted({os.path.basename(f)[:-8] for f in glob.glob('data/longcache/*.parquet')
                       if os.path.basename(f)[:-8].isdigit()})
    pairs = [(s, cm[s]) for s in syms if s in cm]
    print(f'대상 {len(pairs)}종 (corp_code 매칭) · {y0}~{y1}', flush=True)

    # DART 는 종목당 ~1.1초로 고정이라 배칭만으로는 못 줄인다(단일 스레드 8시간).
    # 병렬 6워커로 5.5배 — 실측 202초 → 36.5초.
    from concurrent.futures import ThreadPoolExecutor
    # frmtrm(전년 동기)이 함께 오므로 격년만 호출해도 전 구간이 덮인다
    call_years = sorted({y for y in range(y1, y0 - 1, -2)} | {y1})
    print(f'호출 연도 {call_years} (각 호출이 전년도까지 커버) · 워커 {WORKERS}', flush=True)

    con = sqlite3.connect(DB)
    con.executescript(DDL)
    chunks = [pairs[i:i + BATCH] for i in range(0, len(pairs), BATCH)]
    total, t0 = 0, time.time()
    for year in call_years:
        for reprt, q, _months in REPRTS:
            with ThreadPoolExecutor(max_workers=WORKERS) as ex:
                parts = list(ex.map(
                    lambda ch: fetch_batch([c for _, c in ch], year, reprt), chunks))
            rows = []
            for res in parts:
                for (s, yr), v in res.items():
                    if not (y0 <= yr <= y1):
                        continue
                    rows.append((s, yr, q, v.get('revenue'), v.get('op_income'),
                                 v.get('net_income'), v.get('fs_div'), str(date.today())))
            if rows:
                con.executemany(
                    'INSERT OR REPLACE INTO fundamentals_q'
                    ' (sym,year,q,revenue,op_income,net_income,fs_div,updated)'
                    ' VALUES (?,?,?,?,?,?,?,?)', rows)
                con.commit()
            total += len(rows)
            print(f'  호출 {year} Q{q}: {len(rows):>5}행 (누적 {total:,}행, '
                  f'{time.time()-t0:.0f}s)', flush=True)
    con.close()
    print(f'완료 · {total:,}행 · {time.time()-t0:.0f}초')


def quarterly(con=None) -> 'pd.DataFrame':
    """당분기(3개월) 손익 테이블. Q4만 FY에서 차분해 만든다.

    반환 컬럼: sym, year, q, period(YYYYQn), revenue, op_income, net_income,
              op_turn(흑자전환), op_yoy(영업익 YoY %), rev_yoy
    """
    import pandas as pd
    if con is None and not os.path.exists(DB):
        # 러너에는 market.db(574MB, gitignore)가 없다. 그래서 KR-U6가 자동 갱신에서
        # 빠져 있었고 대시보드에 며칠 묵은 신호가 떠 있었다 — 레포에 실은 export를
        # 읽어 러너에서도 돌게 한다(0.75MB parquet, export_kr_fundq.py 참고).
        import export_kr_fundq
        d = export_kr_fundq.load()
        if d is None or d.empty:
            print('[quarterly] market.db도 kr_fundamentals_q.parquet도 없음 — 빈 결과')
            return pd.DataFrame()
        d = d[['sym', 'year', 'q', 'revenue', 'op_income', 'net_income']]
    else:
        close_after = con is None
        con = con or sqlite3.connect(DB)
        d = pd.read_sql('SELECT sym,year,q,revenue,op_income,net_income FROM fundamentals_q', con)
        if close_after:
            con.close()
    if d.empty:
        return d
    piv = d.pivot_table(index=['sym', 'year'], columns='q',
                        values=['revenue', 'op_income', 'net_income'])
    rows = []
    for (sym, year), r in piv.iterrows():
        q123 = {c: [r.get((c, q)) for q in (1, 2, 3)] for c in
                ('revenue', 'op_income', 'net_income')}
        for q in (1, 2, 3):
            rec = dict(sym=sym, year=int(year), q=q)
            ok = False
            for c in ('revenue', 'op_income', 'net_income'):
                v = r.get((c, q))
                rec[c] = None if pd.isna(v) else float(v)
                ok |= rec[c] is not None
            if ok:
                rows.append(rec)
        # Q4 = FY − (Q1+Q2+Q3) — 셋 중 하나라도 없으면 만들지 않는다(부정확한 값 금지)
        rec = dict(sym=sym, year=int(year), q=4)
        ok = False
        for c in ('revenue', 'op_income', 'net_income'):
            fy = r.get((c, 4))
            parts = q123[c]
            if pd.isna(fy) or any(pd.isna(x) for x in parts):
                rec[c] = None
            else:
                rec[c] = float(fy) - float(sum(parts)); ok = True
        if ok:
            rows.append(rec)
    q = pd.DataFrame(rows).sort_values(['sym', 'year', 'q']).reset_index(drop=True)
    q['period'] = q['year'].astype(str) + 'Q' + q['q'].astype(str)
    # 이익 변곡 재료 — 전년 동기 대비
    q['op_prev_y'] = q.groupby(['sym', 'q'])['op_income'].shift(1)
    q['rev_prev_y'] = q.groupby(['sym', 'q'])['revenue'].shift(1)
    q['op_turn'] = ((q['op_prev_y'] <= 0) & (q['op_income'] > 0)).astype(int)
    q['op_yoy'] = np.where((q['op_prev_y'].notna()) & (q['op_prev_y'] > 0),
                           (q['op_income'] / q['op_prev_y'] - 1) * 100, np.nan)
    q['rev_yoy'] = np.where((q['rev_prev_y'].notna()) & (q['rev_prev_y'] > 0),
                            (q['revenue'] / q['rev_prev_y'] - 1) * 100, np.nan)
    return q


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    a = sys.argv[1:]
    y0 = int(a[0]) if a else 2018
    y1 = int(a[1]) if len(a) > 1 else date.today().year
    ingest(y0, y1)
