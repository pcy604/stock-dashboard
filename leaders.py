"""
주도주 발굴 — 섹터 상대강도(Sector RS) 기반
─────────────────────────────────────────────────────────────────
오닐·미너비니: "주도주는 혼자 안 온다, 주도 섹터와 함께 온다."
  1) 섹터별 상대강도(평균 신고가 근접도) → 주도 섹터 랭킹
  2) 그 주도 섹터 안에서 가장 강한(신고가에 가장 붙은 + 신호 많은) 종목 = 주도주

데이터: results/screener_latest.json (sector·dist_52w·pct_change·신호)
실시간 계산(캐시 스캔 불필요).
"""
import json
from pathlib import Path

SCREENER = Path('results/screener_latest.json')
PERF = Path('results/perf_latest.json')


def _load():
    """넓은 유니버스(월간 모멘텀, 대형주 포함) 우선. 없으면 주봉 신호 종목."""
    try:
        d = json.loads(PERF.read_text(encoding='utf-8'))
        # 주봉 신호(dist_52w·signals)를 sym 기준으로 병합
        try:
            scr = json.loads(SCREENER.read_text(encoding='utf-8'))
            smap = {s['sym']: s for s in scr.get('stocks', [])}
        except Exception:
            smap = {}
        for s in d.get('stocks', []):
            ss = smap.get(s['sym'])
            if ss:
                s['dist_52w'] = ss.get('dist_52w')
                s['signals'] = ss.get('signals', [])
                s['total_signals'] = ss.get('total_signals', 0)
            else:
                s['signals'] = [lab for k, lab in [('now_sig_52w', '52주신고가'),
                    ('now_sig_maconv', '이평선수렴'), ('now_sig_vol', '거래량폭발'),
                    ('now_sig_cup', '컵핸들'), ('now_sig_ma5', '5주라이딩'),
                    ('now_sig_rsimacd', 'RSI/MACD')] if s.get(k)]
                s['total_signals'] = sum(1 for k in ['now_sig_52w', 'now_sig_vol',
                    'now_sig_ma5', 'now_sig_cup', 'now_sig_maconv', 'now_sig_rsimacd'] if s.get(k))
            s['pct_change'] = s.get('ret_1w', 0)
        return d
    except Exception:
        try:
            return json.loads(SCREENER.read_text(encoding='utf-8'))
        except Exception:
            return None


def _stock_strength(s):
    """종목 강도: 4주 모멘텀(주) + 신고가 근접도 + 신호수."""
    rs = 0.0
    mom = s.get('ret_4w')
    if mom is not None:
        rs += max(-20, min(mom, 60))          # 4주 수익률 = 핵심 RS (-20~60)
    dist = s.get('dist_52w')
    if dist is not None:
        rs += (max(0.0, 30 + dist) if dist < 0 else 30 + min(dist, 10)) * 0.5
    rs += s.get('total_signals', 0) * 3
    return round(rs, 1)


def find_leaders(market_filter='전체', top_sectors=6, per_sector=4, min_in_sector=3):
    """반환: {'mode': 'sector'|'overall', 'sectors': [...], 'top': [...]}"""
    data = _load()
    if not data:
        return None
    stocks = [s for s in data['stocks']
              if market_filter == '전체' or s['market'] == market_filter]
    if not stocks:
        return None

    # 섹터 맵으로 보강 (스크리너의 '기타' → 실제 섹터)
    try:
        from sectors import get_sector_map
        smap = get_sector_map()
    except Exception:
        smap = {}

    for s in stocks:
        s['_rs'] = _stock_strength(s)
        mapped = smap.get(s['sym']) or smap.get(str(s['sym']).zfill(6))
        if mapped:
            s['sector'] = mapped

    # 섹터 데이터가 충분한지 확인 (기타 제외하고 의미있는 섹터가 있나)
    from collections import defaultdict
    sec = defaultdict(list)
    for s in stocks:
        sc = s.get('sector')
        if sc and sc != '기타':
            sec[sc].append(s)

    sector_rows = []
    for name, members in sec.items():
        if len(members) < min_in_sector:
            continue
        avg_rs = sum(m['_rs'] for m in members) / len(members)
        near_high = sum(1 for m in members if (m.get('dist_52w') or -99) >= -5)
        sector_rows.append({
            'sector': name, 'n': len(members),
            'sector_rs': round(avg_rs, 1),
            'near_high_pct': round(near_high / len(members) * 100, 0),
            'leaders': sorted(members, key=lambda x: -x['_rs'])[:per_sector],
        })
    sector_rows.sort(key=lambda x: -x['sector_rs'])

    overall_top = sorted(stocks, key=lambda x: -x['_rs'])[:20]
    return {
        'mode': 'sector' if len(sector_rows) >= 3 else 'overall',
        'sectors': sector_rows[:top_sectors],
        'top': overall_top,
    }


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    res = find_leaders()
    if not res:
        print("데이터 없음 — weekly_run.py 먼저")
    else:
        print("🚀 주도 섹터 & 주도주\n")
        for r in res:
            print(f"[{r['sector']}]  섹터RS {r['sector_rs']}  신고가근접 {r['near_high_pct']:.0f}%  ({r['n']}종목)")
            for m in r['leaders']:
                d = f"{m['dist_52w']:+.0f}%" if m.get('dist_52w') is not None else '-'
                print(f"    {m['market']} {m['name'][:14]:<14} RS{m['_rs']:>6}  신고가{d}  {', '.join(m['signals'][:2])}")
            print()
