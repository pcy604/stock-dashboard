"""
consensus_snapshot.py — 컨센서스 시계열 스냅샷 (리비전 모멘텀의 재료)
─────────────────────────────────────────────────────────────────
왜: 애널 추정치가 '오르는 중인가 내리는 중인가'(earnings revision momentum)는
   가장 강건한 펀더멘털 벡터인데, 그 방향을 보려면 컨센서스를 시계열로 저장해야 함.
   우린 그날 값만 봐서 방향을 몰랐음 → 지금부터 매주 스냅샷을 append(시간이 만드는 자산).

동작: value_kr.json 유니버스의 KR 종목에 대해 네이버 (E) 컨센서스(올해/내년 EPS·영업익)를
   긁어 results/consensus_history.jsonl 에 {date, sym, eps_0y, eps_1y, op_0y} 로 누적.
   종목당 최근 16주만 유지(용량 관리). daily가 아니라 주 1회(값 변화 느림).

실행: python consensus_snapshot.py            # 스냅샷 축적
      python consensus_snapshot.py --limit 20 # 테스트(상위 20종목만)
워크플로: weekly-scorecard.yml 등 주간 잡에 스텝 추가(또는 별도 크론).
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import re
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

VALUE = Path('results/value_kr.json')
HISTORY = Path('results/consensus_history.jsonl')
KEEP_WEEKS = 16


DIAG = {}   # 실패 사유 집계 — 0종목이면 이걸 ::error 로 찍는다(2026-10-19)


def _why(k):
    DIAG[k] = DIAG.get(k, 0) + 1


def fetch_consensus(sym: str) -> dict | None:
    """네이버 (E) 컨센서스 — 올해/내년 EPS·영업이익만 (리비전 추적용 최소셋).
    1순위 navercomp.wisereport(해외 러너에서도 닿는다), 실패하면 종목 메인 표(국내에서만 보인다)."""
    try:
        import kr_fin_naver as _kfn
        try:
            c = _kfn.consensus(sym)
        except Exception as _e1:                     # 2026-10-19 — 같은 날 여러 번 돌리자 ConnectTimeout 214건. 한 번 쉬고 다시
            if 'Timeout' not in type(_e1).__name__:
                raise
            time.sleep(3)
            c = _kfn.consensus(sym)
        if c:
            return c
        _why('wisereport 추정 열 없음')
    except Exception as e:
        _why(f'wisereport {type(e).__name__}')
    return _fetch_consensus_main(sym)


def _fetch_consensus_main(sym: str) -> dict | None:
    """(구) finance.naver.com 종목 메인 '기업실적분석' 표 — 해외 러너에는 표가 빠져 내려온다."""
    try:
        r = requests.get(f'https://finance.naver.com/item/main.naver?code={sym}',
                         headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
        if r.status_code != 200:
            _why(f'HTTP {r.status_code}')
            return None
        soup = BeautifulSoup(r.text, 'html.parser')
        tb = soup.select_one('div.cop_analysis table')
        if tb is None:
            _why(f'표 없음(응답 {len(r.text)}B)')
            return None
        heads = [th.get_text(' ', strip=True) for th in tb.select('thead th')]
        dh = [h for h in heads if re.match(r'\d{4}\.\d{2}', h)]
        n_annual = 4 if len(dh) >= 10 else max(len(dh) - 6, 0)
        ynow = datetime.now().year
        emap = {}
        for i, h in enumerate(dh[:n_annual]):
            if '(E)' in h:
                emap[i] = '0y' if int(h[:4]) <= ynow else '1y'
        if not emap:
            _why('(E) 열 없음')
            return None

        def _num(s):
            s = s.replace(',', '').strip()
            try:
                return float(s)
            except Exception:
                return None

        out = {}
        for kw, key in [('EPS', 'eps'), ('영업이익', 'op')]:
            for row in tb.select('tbody tr'):
                th = row.select_one('th')
                if th and kw in th.get_text():
                    vals = [_num(td.get_text(strip=True)) for td in row.select('td')]
                    for i, lab in emap.items():
                        if i < len(vals) and vals[i] is not None:
                            out[f'{key}_{lab}'] = vals[i]
                    break
        return out or None
    except Exception as e:
        _why(type(e).__name__)
        return None


def _universe(limit=None):
    if not VALUE.exists():
        return []
    d = json.loads(VALUE.read_text(encoding='utf-8'))
    syms = [(s['sym'], s.get('marcap', 0)) for s in d.get('stocks', []) if s.get('sym')]
    syms.sort(key=lambda x: -(x[1] or 0))       # 시총 큰 것부터(리비전 신뢰도↑)
    out = [s for s, _ in syms]
    return out[:limit] if limit else out


def run(limit=None):
    syms = _universe(limit)
    if not syms:
        print("value_kr.json 없음 — value_export.py 먼저")
        return
    today = datetime.now().strftime('%Y-%m-%d')
    print(f"컨센서스 스냅샷: {len(syms)}종목 ({today})...")

    results = {}
    done = [0]
    def _one(sym):
        time.sleep(0.03)
        c = fetch_consensus(sym)
        done[0] += 1
        if done[0] % 100 == 0:
            print(f"  {done[0]}/{len(syms)}")
        return sym, c
    with ThreadPoolExecutor(max_workers=3) as ex:   # 6 → 3: 네이버가 몰리는 요청을 끊었다(2026-10-19)
        for sym, c in ex.map(_one, syms):
            if c:
                results[sym] = c

    # ⚠️ 2026-10-19 — 07-24 이후 석 달 동안 매주 "✅ 저장: 0종목" 을 찍고 초록불로 끝났다.
    #   화면의 '컨센서스 추세'는 07-24 한 점에 멈춰 있었다. 대부분 실패하면 쓰지 않고
    #   사유를 ::error 로 남긴 뒤 실패 코드로 끝낸다(Actions 주석에 보인다).
    if len(results) < max(5, len(syms) * 0.3):
        top = ', '.join(f'{k} {v}' for k, v in sorted(DIAG.items(), key=lambda x: -x[1])[:4])
        print(f"::error title=컨센서스 스냅샷 실패::{len(results)}/{len(syms)}종목만 수집 — 사유: {top or '미상'}. 이력을 덮지 않는다.")
        sys.exit(1)

    # 기존 이력 로드 → 오늘 것 제외(재실행 시 덮어씀) + 16주 초과분 정리
    cutoff = (datetime.now() - timedelta(weeks=KEEP_WEEKS)).strftime('%Y-%m-%d')
    rows = []
    if HISTORY.exists():
        for line in HISTORY.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                if r.get('date') != today and r.get('date', '') >= cutoff:
                    rows.append(r)
            except Exception:
                continue
    for sym, c in results.items():
        rows.append({'date': today, 'sym': sym, **c})
    rows.sort(key=lambda r: (r['date'], r['sym']))
    HISTORY.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n',
                       encoding='utf-8')
    print(f"✅ 저장: {len(results)}종목 스냅샷 · 누적 {len(rows)}행 → {HISTORY}")


def revision_map(weeks_back=4) -> dict:
    """sym → 리비전 판정. 최신 스냅샷 vs weeks_back 전 스냅샷의 올해EPS(eps_0y) 변화.
    반환: {sym: {'dir': 'up'|'down'|'flat', 'pct': float, 'n_weeks': int}}"""
    if not HISTORY.exists():
        return {}
    by_sym = {}
    for line in HISTORY.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        by_sym.setdefault(r['sym'], []).append(r)
    out = {}
    for sym, recs in by_sym.items():
        recs = [r for r in sorted(recs, key=lambda x: x['date']) if r.get('eps_0y')]
        if len(recs) < 2:
            continue
        latest = recs[-1]
        target_date = (datetime.strptime(latest['date'], '%Y-%m-%d')
                       - timedelta(weeks=weeks_back)).strftime('%Y-%m-%d')
        prior = min(recs[:-1], key=lambda r: abs(
            (datetime.strptime(r['date'], '%Y-%m-%d')
             - datetime.strptime(target_date, '%Y-%m-%d')).days))
        if not prior.get('eps_0y') or prior['eps_0y'] == 0:
            continue
        pct = (latest['eps_0y'] / prior['eps_0y'] - 1) * 100
        d = 'up' if pct > 1 else ('down' if pct < -1 else 'flat')
        out[sym] = {'dir': d, 'pct': round(pct, 1), 'n_weeks': len(recs)}
    return out


if __name__ == '__main__':
    lim = None
    if '--limit' in sys.argv:
        lim = int(sys.argv[sys.argv.index('--limit') + 1])
    run(lim)
