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


def investor(sosok: str, pages: int = 8) -> list[dict]:
    """sosok: '01' 코스피 · '02' 코스닥. 한 쪽 10영업일 안팎 — 8쪽 ≈ 3~4개월."""
    biz = datetime.now(KST).strftime('%Y%m%d')
    rows = []
    for p in range(1, pages + 1):
        try:
            rows += parse_investor(_get('https://finance.naver.com/sise/investorDealTrendDay.naver',
                                        dict(bizdate=biz, sosok=sosok, page=p)))
        except Exception as e:
            ERR[f'investor{sosok}p{p}'] = f'{type(e).__name__}: {e}'[:120]
            break
    return _dedup(rows)


def deposit(pages: int = 8) -> list[dict]:
    rows = []
    for p in range(1, pages + 1):
        try:
            rows += parse_deposit(_get('https://finance.naver.com/sise/sise_deposit.naver', dict(page=p)))
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
        s['credit'] = dict(date=c[-1][0], v=v[-1], chg20=(v[-1] / v[-21] - 1) * 100 if len(v) > 20 else None,
                           peak=max(v), from_peak=(v[-1] / max(v) - 1) * 100)
    if k:
        v = [x for _, x in k]
        s['deposit'] = dict(date=k[-1][0], v=v[-1], chg20=(v[-1] / v[-21] - 1) * 100 if len(v) > 20 else None)
    if c and k:
        s['credit_ratio'] = c[-1][1] / k[-1][1] * 100      # 신용잔고 ÷ 예탁금(%) — 빚 비중
    return s


def main() -> int:
    inv = {'KOSPI': investor('01'), 'KOSDAQ': investor('02')}
    dep = deposit()
    ok = sum(len(v) > 10 for v in inv.values()) + (len(dep) > 10)
    v = dict(generated=datetime.now(KST).strftime('%Y-%m-%d %H:%M KST'),
             src='네이버 금융 — 투자자별 매매동향(sise/investorDealTrendDay) · 증시자금동향(sise/sise_deposit), 단위 억원',
             investor=inv, deposit=dep, summary=summarize(inv, dep), err=ERR)
    print(f"투자자 코스피 {len(inv['KOSPI'])}일 · 코스닥 {len(inv['KOSDAQ'])}일 · 자금동향 {len(dep)}일 · 실패 {ERR}")
    if inv['KOSPI'] and inv['KOSDAQ'] and inv['KOSPI'][-1] == inv['KOSDAQ'][-1]:
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
