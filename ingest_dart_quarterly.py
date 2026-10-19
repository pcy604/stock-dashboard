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
REPORT_MONTH = {r: m for r, _q, m in REPRTS}   # 보고서 → 기간 끝 달력 월
WANT = {'매출액': 'revenue', '영업이익': 'op_income', '당기순이익': 'net_income'}


def _want(nm):
    """계정명 → 내부 필드. DART 는 **괄호를 붙여** 보낸다.

    ⚠️ 2026-10-12 — 여기서 42,751행의 net_income 이 전부 비었다. DART 가 주는
       이름은 '당기순이익(손실)' 인데 WANT 에는 '당기순이익' 으로 있었고,
       dict 정확일치 조회라 한 번도 안 걸렸다. 매출액·영업이익은 이름이
       정확히 같아서 멀쩡했기 때문에 '일부만 비는' 모양으로도 안 보였다.
       괄호 앞부분으로도 맞춰 같은 사고를 막는다.
    """
    nm = (nm or '').strip()
    if not nm:
        return None
    return WANT.get(nm) or WANT.get(nm.split('(')[0].strip())

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
        acc = _want(row.get('account_nm'))
        if not acc or (row.get('sj_div') or '') != 'IS':      # 손익계산서만
            continue
        # 2026-10-19 — 외국 기업(950xxx·900xxx)·두산밥캣 등은 USD·CNY 로 공시한다. 원화로 알고 저장해
        #   PER 이 1,400배 틀어졌다(네이버 대조로 발견). 원화가 아니면 받지 않는다 → 네이버(원화 환산)가 채운다.
        if (row.get('currency') or 'KRW').upper() != 'KRW':
            continue
        # 2026-10-19 — 12월 결산이 아닌 회사는 '사업연도' 분기다(3월 결산의 1분기 = 4~6월).
        #   달력 분기로 저장하면 10월에 '2026Q4' 같은 미래 분기가 생긴다. 기간 끝 월이 보고서의
        #   달력 월(3·6·9·12)과 다르면 받지 않는다.
        _end = str(row.get('thstrm_dt') or '').replace(' ', '').split('~')[-1]
        _mm = _end[5:7] if len(_end) >= 7 and _end[4] in '.-' else None
        if _mm and _mm.isdigit() and int(_mm) != REPORT_MONTH.get(reprt, int(_mm)):
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
    try:   # 12월 결산 아닌 종목은 건너뛴다(kr_fundq_naver 가 찾아 기록한다, 2026-10-19)
        import json as _js
        _nd = set(_js.load(open('data/kr_nondec.json', encoding='utf-8')))
    except Exception:
        _nd = set()
    pairs = [(s, cm[s]) for s in syms if s in cm and s not in _nd]
    print(f'대상 {len(pairs)}종 (corp_code 매칭) · {y0}~{y1}', flush=True)

    # DART 는 종목당 ~1.1초로 고정이라 배칭만으로는 못 줄인다(단일 스레드 8시간).
    # 병렬 6워커로 5.5배 — 실측 202초 → 36.5초.
    from concurrent.futures import ThreadPoolExecutor
    # frmtrm(전년 동기)이 함께 오므로 격년만 호출해도 전 구간이 덮인다
    # ⚠️ 2026-10-14 — '격년 호출'은 **완결된 해**에만 성립한다. 올해 3·4분기 보고서는 아직
    #   없으니 그 '전년 동기'(작년 3·4분기)도 영영 안 받았다. 실측: 2025Q3 7종 · 2025Q4 24종
    #   (정상 1,400+). '최근 4분기'를 쓰는 흑자전환·TTM PER 이 통째로 어긋났다.
    #   작년은 언제나 직접 호출한다.
    call_years = sorted({y for y in range(y1, y0 - 1, -2)} | {y1} | ({y1 - 1} if y1 - 1 >= y0 else set()))
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


def _has_fundq(db_path):
    """market.db 에 fundamentals_q 테이블이 실제로 있는가.

    파일 존재만으로 판단하면 안 된다 — 다른 스텝이 만든 빈 DB 가 폴백을 막는다.
    """
    if not os.path.exists(db_path):
        return False
    try:
        c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = c.execute("SELECT name FROM sqlite_master "
                            "WHERE type='table' AND name='fundamentals_q'").fetchone()
            return row is not None
        finally:
            c.close()
    except Exception:
        return False

def quarterly(con=None) -> 'pd.DataFrame':
    """당분기(3개월) 손익 테이블. Q4만 FY에서 차분해 만든다.

    반환 컬럼: sym, year, q, period(YYYYQn), revenue, op_income, net_income,
              op_turn(흑자전환), op_yoy(영업익 YoY %), rev_yoy
    """
    import pandas as pd
    if con is None and not _has_fundq(DB):
        # 러너에는 market.db(574MB, gitignore)가 없다. 그래서 KR-U6가 자동 갱신에서
        # 빠져 있었고 대시보드에 며칠 묵은 신호가 떠 있었다 — 레포에 실은 export를
        # 읽어 러너에서도 돌게 한다(0.75MB parquet, export_kr_fundq.py 참고).
        #
        # ⚠️ 2026-09-09 — 조건이 원래 `not os.path.exists(DB)` 였는데 그걸로는 부족했다.
        #   러너에서 앞선 스텝이 sqlite3.connect(DB) 를 쓰기 모드로 열면 **빈 DB 파일이
        #   생긴다.** 그러면 파일은 존재하니 폴백이 안 걸리고, 곧바로
        #   `no such table: fundamentals_q` 로 죽는다. 실제로 KR-U6 가 그 이유로
        #   11일, 포워드 원장이 18일 멈춰 있었다 — 화면에는 "정지"로만 보였다.
        #   파일이 아니라 **테이블이 있는지**로 판정해야 한다.
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
            # 2026-10-15 — 노트북 market.db 는 2025Q3·Q4 가 빠진 채(call_years 버그 시절 적재본)
            #   남아 있고, CI 가 고쳐서 올린 parquet 에는 들어 있다. 노트북이 매일 06:40 에
            #   흑자전환을 돌리며 **낡은 로컬 DB 를 우선** 써서 KR 0종(판정 보류 1,215종)을
            #   매일 덮어썼다. 두 원천 중 최신 분기가 더 늦은(같으면 그 분기 종목이 더 많은) 쪽을 쓴다.
            try:
                import export_kr_fundq
                pq = export_kr_fundq.load()
                if pq is not None and not pq.empty:
                    _t = pd.Timestamp.today() - pd.DateOffset(months=15)
                    _floor = _t.year * 10 + (_t.month - 1) // 3 + 1

                    def _cov(x):
                        # 최근 15개월 분기 행 수 — '최신 분기 하나'로 보면 일부 비12월 결산 종목이
                        # 만든 미래 분기(2026Q4 등) 몇 개에 판정이 끌려간다.
                        k = (x.year.astype(int) * 10 + x.q.astype(int))
                        return int((k >= _floor).sum())
                    if _cov(pq) > _cov(d):
                        print(f"[quarterly] parquet 이 로컬 DB 보다 최신 {_cov(pq)} > {_cov(d)} — parquet 사용")
                        d = pq[['sym', 'year', 'q', 'revenue', 'op_income', 'net_income']]
            except Exception as _e:
                print(f"[quarterly] parquet 비교 생략: {str(_e)[:80]}")
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
