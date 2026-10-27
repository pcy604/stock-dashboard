"""세부 업종 수집 (2026-10-27) → data/sector_detail.json

사용자 지적: 한국 표준산업분류는 '특수 목적용 기계 제조업'처럼 거칠어 반도체 소부장을 못 발라낸다.
  · KR = 네이버 금융 **테마**(사람이 분류 · 한 종목이 여러 테마: '반도체 장비'·'반도체 재료/부품'·'HBM' …) + 네이버 업종.
         m.stock.naver.com JSON API 먼저, 안 되면 finance.naver.com 목록 페이지.
  · US = 야후 세부 산업(industry, 약 145개 · 'Semiconductor Equipment & Materials' 등). 증분 · 하루 상한 회전.
결과: {'asof', 'kr': {code: {'upjong': str, 'themes': [str]}}, 'us': {sym: {'industry', 'sector'}},
       'themes': {이름: 종목수}, 'src': {...}}
"""
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, 'data', 'sector_detail.json')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36',
      'Referer': 'https://m.stock.naver.com/'}
US_DAILY_CAP = int(os.environ.get('US_CAP', '1200'))


def _get(url, **kw):
    for i in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=15, **kw)
            if r.status_code == 200:
                return r
        except Exception:
            pass
        time.sleep(1 + i)
    return None


def _dicts(js):
    """JSON 어디에 있든 dict 리스트를 다 꺼낸다(스키마를 모르는 API 방어)."""
    if isinstance(js, dict):
        yield js
        for v in js.values():
            yield from _dicts(v)
    elif isinstance(js, list):
        for v in js:
            yield from _dicts(v)


# ───────────────────────── KR: 네이버 ─────────────────────────
def _groups_api(kind):
    """kind = 'theme' | 'industry' → [(no, name)]"""
    out, page = {}, 1
    while page < 30:
        r = _get(f'https://m.stock.naver.com/api/stocks/{kind}', params={'page': page, 'pageSize': 100})
        if not r:
            break
        try:
            js = r.json()
        except Exception:
            break
        got = 0
        for d in _dicts(js):
            no = d.get('no') or d.get('themeNo') or d.get('industryCode') or d.get('groupNo')
            nm = d.get('name') or d.get('themeName') or d.get('industryName') or d.get('groupName')
            if no and nm and str(no) not in out:
                out[str(no)] = str(nm).strip()
                got += 1
        if not got:
            break
        page += 1
    return list(out.items())


def _members_api(kind, no):
    codes, page = [], 1
    while page < 10:
        r = _get(f'https://m.stock.naver.com/api/stocks/{kind}/{no}', params={'page': page, 'pageSize': 100})
        if not r:
            break
        new = [c for c in re.findall(r'"itemCode"\s*:\s*"([0-9A-Z]{6})"', r.text) if c not in codes]
        if not new:
            break
        codes += new
        page += 1
    return codes


def _groups_web(kind):
    t = 'theme' if kind == 'theme' else 'upjong'
    out = {}
    url = 'https://finance.naver.com/sise/theme.naver' if t == 'theme' else 'https://finance.naver.com/sise/sise_group.naver?type=upjong'
    for page in range(1, 15 if t == 'theme' else 2):
        r = _get(url, params={'page': page} if t == 'theme' else None)
        if not r:
            break
        r.encoding = 'euc-kr'
        got = 0
        for no, nm in re.findall(rf'sise_group_detail\.naver\?type={t}&(?:amp;)?no=(\d+)"[^>]*>([^<]+)<', r.text):
            if no not in out:
                out[no] = nm.strip()
                got += 1
        if not got:
            break
    return list(out.items())


def _members_web(kind, no):
    t = 'theme' if kind == 'theme' else 'upjong'
    r = _get(f'https://finance.naver.com/sise/sise_group_detail.naver?type={t}&no={no}')
    if not r:
        return []
    return list(dict.fromkeys(re.findall(r'/item/main\.naver\?code=([0-9A-Z]{6})', r.text)))


def collect_kr():
    src = {}
    res = {'theme': {}, 'industry': {}}
    for kind in ('theme', 'industry'):
        gs, how = _groups_api(kind), 'm.stock API'
        if len(gs) < (50 if kind == 'theme' else 20):
            gs, how = _groups_web(kind), 'finance.naver 페이지'
        mem = _members_api if how == 'm.stock API' else _members_web
        print(f"  KR {kind}: {len(gs)}개 그룹 ({how})")
        with ThreadPoolExecutor(6) as ex:
            for (no, nm), codes in zip(gs, ex.map(lambda g: mem(kind, g[0]), gs)):
                if codes:
                    res[kind][nm] = codes
        if how == 'm.stock API' and sum(map(len, res[kind].values())) < 100:      # API 목록만 되고 구성종목이 막힌 경우
            res[kind] = {}
            for no, nm in _groups_web(kind):
                c = _members_web(kind, no)
                if c:
                    res[kind][nm] = c
            how = 'finance.naver 페이지(구성종목)'
        src[kind] = how
        print(f"    → 구성 {len(res[kind])}개 · 종목-그룹 쌍 {sum(map(len, res[kind].values())):,}")
    kr = {}
    for nm, codes in res['industry'].items():
        for c in codes:
            kr.setdefault(c, {'upjong': None, 'themes': []})['upjong'] = nm
    for nm, codes in res['theme'].items():
        for c in codes:
            kr.setdefault(c, {'upjong': None, 'themes': []})['themes'].append(nm)
    themes = {nm: len(c) for nm, c in res['theme'].items()}
    return kr, themes, src


# ───────────────────────── US: 야후 세부 산업 ─────────────────────────
def collect_us(old: dict):
    import yfinance as yf
    try:
        import universe as U
        syms = [s for s, _, _ in U.us_cover()]
    except Exception as e:
        print(f"::warning::US 명단 실패 {e}")
        syms = list(old)
    todo = [s for s in syms if not (old.get(s) or {}).get('industry')]
    # 회전: 날짜로 시작점을 옮겨 늘 같은 앞부분만 시도하지 않게(CLAUDE.md 순서 편향)
    if todo:
        k = date.today().toordinal() % len(todo)
        todo = (todo[k:] + todo[:k])[:US_DAILY_CAP]
    print(f"  US: 명단 {len(syms):,} · 이미 {len(syms) - len([s for s in syms if not (old.get(s) or {}).get('industry')]):,} · 이번 시도 {len(todo):,}")

    def one(s):
        try:
            inf = yf.Ticker(s.replace('.', '-')).get_info()
            ind, sec = inf.get('industry'), inf.get('sector')
            return s, ({'industry': ind, 'sector': sec} if ind else None)
        except Exception:
            return s, None
    out, ok = dict(old), 0
    with ThreadPoolExecutor(6) as ex:
        for s, v in ex.map(one, todo):
            if v:
                out[s] = v
                ok += 1
    print(f"    → 성공 {ok:,}/{len(todo):,}")
    return out, ok, len(todo)


def main():
    old = {}
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT, encoding='utf-8'))
        except Exception:
            old = {}
    kr, themes, src = collect_kr()
    bad = False
    if len(themes) < 100 or len(kr) < 1000:
        print(f"::error title=네이버 테마 수집 실패::테마 {len(themes)} · 종목 {len(kr)} — 이전 값 유지")
        kr, themes = old.get('kr') or {}, old.get('themes') or {}
        bad = True
    us, ok, tried = collect_us(old.get('us') or {})
    if tried >= 50 and ok < tried * 0.3:
        print(f"::error title=야후 산업 수집 대부분 실패::{ok}/{tried}")
        bad = True
    out = {'asof': date.today().isoformat(), 'kr': kr, 'us': us, 'themes': themes,
           'src': {**src, 'us': 'yfinance industry'}}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    for c in ('005930', '042700', '036930', 'NVDA', 'AMAT'):
        print(f"  확인 {c}: {(kr.get(c) or us.get(c))}")
    print(f"✅ KR {len(kr):,}종 · 테마 {len(themes)} · US {sum(1 for v in us.values() if v):,}종")
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
