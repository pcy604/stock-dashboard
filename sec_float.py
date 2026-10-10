"""
sec_float.py — SEC frames 로 수집 유니버스를 한 번에 받는다
─────────────────────────────────────────────────────────────────
왜 만들었나 (2026-10-10):
  수집 유니버스를 **종목당 요청 1건**으로 긁고 있었다. edgar_cik 10,413종을
  대상으로 Yahoo 에 하나씩 물어보는 방식이다. 결과:
    · 실패 종목(상장폐지·ETF·ADR)이 목록 앞을 막는데 실패 기록이 없어
      매 실행 같은 것을 재시도한다
    · 10회 돌려 1,068종 느는 데 그쳤고 1,750종에서 멈췄다
    · 그 사이 universe 가 2,429 → 242종으로 무너져 주도주가 한 달 멈췄다

  SEC frames API 는 **분기당 1콜로 전체 기업**을 준다. 실측:
    8콜 · 6.5초 → 5,254개사 · $150M+ 3,134개사 · 티커 매핑 2,906종

  dei:EntityPublicFloat 은 10-K 표지의 '공모 시가총액'이다. 12월 결산 기업이
  6월 30일 기준으로 보고하므로 CY..Q2I 에 몰리고, 여러 분기를 합쳐야 비12월
  결산까지 들어온다.

⚠️ public float ≠ 시가총액 — 반드시 용도를 구분할 것
  내부자·계열 보유분이 빠진다. 창업자 지분이 큰 회사는 과소평가된다.
  10-K 표지 기준이라 연 1회 갱신이고 최대 1년 묵는다.
  → 그래서 **수집 유니버스 선정**에만 쓴다. 이 단계는 '무엇을 볼지'만 정하고,
    '무엇을 매매할지'는 factor_weekly 의 주차별 marcap(주식수 × 그 주 가격)이
    point-in-time 으로 건다. 화면에 쓰는 시총도 그쪽이다.
    오히려 float 은 '시장에서 실제 거래 가능한 규모'라 수집 대상을 고르는
    잣대로는 시총보다 맞는 면이 있다.
  → 놓치는 것: 외국 발행사(20-F)는 이 태그를 잘 안 쓴다. ADR 은 어차피
    유니버스에서 거르므로 손실이 아니지만, 미국 상장 외국기업 일부는 빠진다.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import json
import os
import time
from pathlib import Path

import requests

UA = {'User-Agent': 'stock-screener research pcy604604@gmail.com',
      'Accept-Encoding': 'gzip, deflate'}
OUT = Path('data/us_float.csv')
TAG = 'https://data.sec.gov/api/xbrl/frames/dei/EntityPublicFloat/USD/{q}.json'


def quarters(years=2):
    """최신 분기부터 거슬러 올라가는 프레임 키. 최신 값이 이기도록 뒤에서 덮는다."""
    import datetime as _d
    y0 = _d.date.today().year
    return [f'CY{y}Q{q}I' for y in range(y0 - years + 1, y0 + 1) for q in (1, 2, 3, 4)]


def fetch(years=2, sleep=0.2):
    """{cik: (float_usd, 기준분기)} — 분기당 1콜."""
    best, calls = {}, 0
    for q in quarters(years):
        try:
            r = requests.get(TAG.format(q=q), headers=UA, timeout=45)
            calls += 1
            if r.status_code != 200:
                continue
            for x in r.json().get('data', []):
                c, v = x.get('cik'), x.get('val')
                if c and v:
                    # quarters() 가 오름차순이므로 뒤에 오는 분기가 최신이다
                    best[int(c)] = (float(v), q)
        except Exception as e:
            print(f'  {q} 실패: {str(e)[:80]}', flush=True)
        time.sleep(sleep)
    return best, calls


def build(min_float=1.5e8, years=2):
    """수집 유니버스를 만들어 data/us_float.csv 에 저장하고 티커 목록을 돌려준다."""
    import pandas as pd
    t0 = time.time()
    best, calls = fetch(years)
    cm = json.load(open('data/edgar_cik.json', encoding='utf-8'))
    c2t = {int(v): k for k, v in cm.items()}

    rows = []
    for cik, (val, q) in best.items():
        sym = c2t.get(cik)
        if sym and val >= min_float:
            rows.append(dict(cik=cik, sym=sym, public_float=val, basis=q))
    d = pd.DataFrame(rows).sort_values('public_float', ascending=False)

    # 급감 가드 — marketcap_refresh 가 470종짜리로 3,095종을 덮은 사고와 같은 종류다.
    if OUT.exists():
        try:
            prev = len(pd.read_csv(OUT))
            if prev >= 500 and len(d) < prev * 0.7:
                print(f'[중단] {prev:,} → {len(d):,}종으로 급감했다. 기존 파일을 지킨다.',
                      flush=True)
                return sorted(pd.read_csv(OUT).sym.astype(str))
        except Exception:
            pass

    OUT.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(OUT, index=False)
    print(f'{calls}콜 · {time.time()-t0:.1f}초 → 기업 {len(best):,}개 · '
          f'${min_float/1e6:.0f}M+ 이면서 티커 있음 {len(d):,}종 → {OUT}', flush=True)
    return sorted(d.sym.astype(str))


def load():
    """저장된 유니버스 티커. 없으면 빈 리스트."""
    if not OUT.exists():
        return []
    try:
        import pandas as pd
        return sorted(pd.read_csv(OUT).sym.astype(str))
    except Exception:
        return []


if __name__ == '__main__':
    syms = build(min_float=float(os.environ.get('MIN_FLOAT', 1.5e8)))
    print(f'샘플 10종: {syms[:10]}')
