"""한국 돈의 흐름 수집 (2026-11-06, 매크로 개편 4번 '한국 블록') → results/kr_flow.json

  · 외국인·기관·개인 순매수(억원, 일별) — 코스피·코스닥 · 네이버 금융 '투자자별 매매동향'
  · 고객예탁금·신용잔고(억원, 일별) — 네이버 금융 '증시자금동향'
수출(FRED XTEXVA01KRM667S)·원/달러(Yahoo KRW=X)는 화면이 직접 받는다.

해외 서버(Actions)에서 KRX·DART 가 자주 막혀 네이버를 쓴다. 실패는 숨기지 않는다:
대부분 비면 ::error 와 exit 1 (0건 저장을 ✅ 로 찍지 않는다 — CLAUDE.md).
"""
from __future__ import annotations

import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'results', 'kr_flow.json')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36',
      'Referer': 'https://finance.naver.com/'}
KST = timezone(timedelta(hours=9))
ERR: dict = {}


def _get(url: str, params: dict | None = None) -> str:
    r = requests.get(url, params=params, headers=UA, timeout=15)
    r.raise_for_status()
    r.encoding = 'euc-kr'
    return r.text


def _num(x):
    if x is None:
        return None
    s = str(x).replace(',', '').replace('+', '').strip()
    try:
        return float(s)
    except ValueError:
        return None


def _date(x):
    s = str(x).strip()
    for f in ('%y.%m.%d', '%Y.%m.%d'):
        try:
            return datetime.strptime(s, f).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return None


def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [' '.join(dict.fromkeys(str(c) for c in col if 'Unnamed' not in str(c))).strip() for col in df.columns]
    else:
        df.columns = [str(c) for c in df.columns]
    return df


def parse_investor(html: str) -> list[dict]:
    """투자자별 매매동향 표 → [{date, 개인, 외국인, 기관}] (억원, 순매수)."""
    out = []
    for t in pd.read_html(io.StringIO(html)):
        t = _flatten(t)
        cols = list(t.columns)
        dc = next((c for c in cols if '날짜' in c), None)
        fc = next((c for c in cols if c.startswith('외국인')), None)
        if not dc or not fc:
            continue
        pc = next((c for c in cols if c.startswith('개인')), None)
        ic = next((c for c in cols if c.startswith('기관')), None)
        for _, r in t.iterrows():
            d = _date(r[dc])
            if not d:
                continue
            out.append(dict(date=d, 외국인=_num(r[fc]), 개인=_num(r[pc]) if pc else None, 기관=_num(r[ic]) if ic else None))
    return out


def parse_deposit(html: str) -> list[dict]:
    """증시자금동향 표 → [{date, 고객예탁금, 신용잔고}] (억원)."""
    out = []
    for t in pd.read_html(io.StringIO(html)):
        t = _flatten(t)
        cols = list(t.columns)
        dc = next((c for c in cols if '날짜' in c), None)
        dep = next((c for c in cols if '고객예탁금' in c and '증감' not in c), None)
        cr = next((c for c in cols if '신용잔고' in c and '증감' not in c), None)
        if not dc or not (dep or cr):
            continue
        for _, r in t.iterrows():
            d = _date(r[dc])
            if not d:
                continue
            out.append(dict(date=d, 고객예탁금=_num(r[dep]) if dep else None, 신용잔고=_num(r[cr]) if cr else None))
    return out


def _dedup(rows: list[dict]) -> list[dict]:
    m = {r['date']: r for r in rows if r.get('date')}
    return [m[k] for k in sorted(m)]


def investor_day(mk: str, d: str) -> dict | None:
    """네이버 증권 모바일 API — 그날 개인·외국인·기관 순매수(억원). mk: KOSPI | KOSDAQ, d: YYYYMMDD.
    2026-11-06: 옛 PC 페이지(investorDealTrendDay)는 '더 이상 제공되지 않습니다'(410)."""
    r = requests.get(f'https://m.stock.naver.com/api/index/{mk}/trend', params=dict(bizdate=d), headers=UA, timeout=12)
    r.raise_for_status()
    j = r.json()
    j = j[0] if isinstance(j, list) and j else j
    bd = str(j.get('bizdate') or '')
    if not j or bd[:8] != d:                    # 휴장일이면 다른 날을 돌려준다 → 버린다
        return None
    row = dict(date=f'{bd[:4]}-{bd[4:6]}-{bd[6:8]}', 개인=_num(j.get('personalValue')),
               외국인=_num(j.get('foreignValue')), 기관=_num(j.get('institutionalValue')))
    # 2026-11-11 — 장 시작 전·집계 전에는 그날 날짜로 0·0·0 을 돌려준다(08-17 행도 같은 모양). 실행이 늦게 돌면
    #   (cron 17:47 이 실제로는 다음 날 01~04시) 두 시장 다 0 이 되어 아래 '두 시장 같다' 점검이 실패했다 → 버린다.
    if not any(row[k] for k in ('개인', '외국인', '기관')):
        return None
    return row


def investor(mk: str, days: int = 95, prev: list | None = None) -> list[dict]:
    """최근 days 일(달력) — 이미 받은 날은 다시 받지 않는다(최근 5일은 정정될 수 있어 다시)."""
    have = {r['date']: r for r in (prev or [])}
    today = datetime.now(KST).date()
    rows = []
    for i in range(days):
        dt = today - timedelta(days=i)
        if dt.weekday() >= 5:
            continue
        iso = dt.isoformat()
        if iso in have and i > 5:
            rows.append(have[iso]); continue
        try:
            x = investor_day(mk, dt.strftime('%Y%m%d'))
            if x:
                rows.append(x)
        except Exception as e:
            ERR[f'{mk} {iso}'] = f'{type(e).__name__}: {e}'[:120]
    return _dedup(rows)


def deposit(pages: int = 6) -> list[dict]:
    """증시자금동향 — stock.naver.com JSON(2026-11-06: 옛 PC 표는 화면에서 그려 빈 표만 온다). 단위 억원."""
    rows = []
    for p in range(1, pages + 1):
        try:
            r = requests.get('https://stock.naver.com/api/domestic/market/trendDeposit',
                             params=dict(page=p, pageSize=20), headers=UA, timeout=12)
            r.raise_for_status()
            j = r.json()
            if isinstance(j, dict):                # 감싼 키 이름에 기대지 않는다 — 첫 번째 목록 값
                j = j if 'bizdate' in j else next((v for v in j.values() if isinstance(v, list)), [j])
            if isinstance(j, dict):
                j = [j]
            new = 0
            for x in (j or []):
                bd = str(x.get('bizdate') or '')
                if len(bd) < 8:
                    continue
                d = f'{bd[:4]}-{bd[4:6]}-{bd[6:8]}'
                if any(r_['date'] == d for r_ in rows):
                    continue
                rows.append(dict(date=d, 고객예탁금=_num(x.get('customerDeposit')), 신용잔고=_num(x.get('creditLoan'))))
                new += 1
            if not new:
                break
        except Exception as e:
            ERR[f'deposit p{p}'] = f'{type(e).__name__}: {e}'[:120]
            break
    return _dedup(rows)


def summarize(inv: list[dict], dep: list[dict]) -> dict:
    """화면 카드용 요약 — 계산은 여기 한 곳."""
    s = {}
    for mk, rows in inv.items():
        f = [r['외국인'] for r in rows if r.get('외국인') is not None]
        if f:
            s[mk] = dict(date=rows[-1]['date'], d1=f[-1], d5=sum(f[-5:]), d20=sum(f[-20:]), d60=sum(f[-60:]),
                         n=len(f))
    c = [(r['date'], r['신용잔고']) for r in dep if r.get('신용잔고') is not None]
    k = [(r['date'], r['고객예탁금']) for r in dep if r.get('고객예탁금') is not None]
    if c:
        v = [x for _, x in c]
        w = min(20, len(v) - 1)                    # API 가 최근 20일만 준다 → 매일 쌓기 전엔 있는 만큼(win 에 적는다)
        s['credit'] = dict(date=c[-1][0], v=v[-1], chg20=(v[-1] / v[-1 - w] - 1) * 100 if w >= 10 else None, win=w,
                           peak=max(v), peak_date=c[v.index(max(v))][0], from_peak=(v[-1] / max(v) - 1) * 100, n=len(v))
    if k:
        v = [x for _, x in k]
        w = min(20, len(v) - 1)
        s['deposit'] = dict(date=k[-1][0], v=v[-1], chg20=(v[-1] / v[-1 - w] - 1) * 100 if w >= 10 else None, win=w)
    if c and k:
        s['credit_ratio'] = c[-1][1] / k[-1][1] * 100      # 신용잔고 ÷ 예탁금(%) — 빚 비중
    return s


def main() -> int:
    old = {}
    try:
        old = json.load(open(OUT, encoding='utf-8'))
    except Exception:
        pass
    inv = {mk: investor(mk, prev=(old.get('investor') or {}).get(mk)) for mk in ('KOSPI', 'KOSDAQ')}
    dep = deposit()
    dep = _dedup(list(old.get('deposit') or []) + dep)[-400:]    # API 는 최근 20일뿐 → 매일 이어 붙여 쌓는다
    ok = sum(len(v) > 10 for v in inv.values()) + (len(dep) > 10)
    v = dict(generated=datetime.now(KST).strftime('%Y-%m-%d %H:%M KST'),
             src='네이버 증권 — 투자자별 순매수(m.stock.naver.com/api/index/*/trend) · 증시자금동향(stock.naver.com/api/domestic/market/trendDeposit), 단위 억원',
             investor=inv, deposit=dep, summary=summarize(inv, dep), err=ERR)
    print(f"투자자 코스피 {len(inv['KOSPI'])}일 · 코스닥 {len(inv['KOSDAQ'])}일 · 자금동향 {len(dep)}일 · 실패 {ERR}")
    if (inv['KOSPI'] and inv['KOSDAQ'] and inv['KOSPI'][-1]['date'] == inv['KOSDAQ'][-1]['date']
            and inv['KOSPI'][-1]['외국인'] and inv['KOSPI'][-1]['외국인'] == inv['KOSDAQ'][-1]['외국인']):
        print('::error::코스피와 코스닥 수급이 같다 — sosok 매개변수가 무시됐을 수 있다')
        return 1
    if ok < 2:
        print(f'::error::한국 수급 수집 대부분 실패 ({ok}/3) — 저장하지 않는다')
        return 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(v, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
