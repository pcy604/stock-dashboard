"""
주간 추천 포트폴리오 — 10선·20선 + 비중 + 현금비중, 매주 스냅샷 + 사후분석
─────────────────────────────────────────────────────────────────
"우선 첫 발을 디디자" — 매주 시스템이 포트폴리오를 제시하고, 그걸 기록해
4·13주 뒤 실제 성과를 사후분석한다. (실투자 아님, 페이퍼 트랙레코드)

구성:
  · 후보·점수·비중·진입가 = auto_recommend (기술60+기본40 블렌딩 + 손익비 사이징)
  · 현금비중 = 매크로 신호(FRED) 기반 자동 (10~70%)
  · 매주 1회 스냅샷 → results/weekly_portfolio_history.json 에 누적
  · 사후분석 = 과거 스냅샷의 진입가 대비 현재가 → 비중가중 포트 수익률

CLI:
  python weekly_portfolio.py            # 이번 주 10선·20선 생성 + 저장
  python weekly_portfolio.py analyze    # 과거 스냅샷 사후분석
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import json
from pathlib import Path
from datetime import datetime

import auto_recommend as AR

CURRENT = Path('results/weekly_portfolio.json')
HISTORY = Path('results/weekly_portfolio_history.json')


def _macro_cash_pct():
    """매크로 신호 기반 현금비중(중앙값, 0~1). 실패 시 0.30."""
    try:
        import os, requests
        FRED = os.environ.get('FRED_KEY', '')
        if not FRED:
            _kf = Path('data/.fred_key')
            FRED = _kf.read_text(encoding='utf-8').strip() if _kf.exists() else ''
        if not FRED:
            return 0.30
        def fred(s, n):
            r = requests.get('https://api.stlouisfed.org/fred/series/observations',
                             params=dict(series_id=s, api_key=FRED, file_type='json',
                                         sort_order='desc', limit=n), timeout=10)
            obs = r.json()['observations']
            return [float(o['value']) for o in obs if o['value'] != '.']
        fr = fred('FEDFUNDS', 1)
        fed_rate = fr[0] if fr else None
        m2 = fred('M2SL', 14)
        m2_yoy = round((m2[0] / m2[12] - 1) * 100, 1) if len(m2) >= 13 else None
        score = 0
        if fed_rate is not None:
            score += 2 if fed_rate <= 2.5 else (1 if fed_rate <= 4.5 else -1)
        if m2_yoy is not None:
            score += 2 if m2_yoy >= 5 else (1 if m2_yoy >= 0 else -1)
        if score >= 4:   lo, hi = 10, 20
        elif score >= 1: lo, hi = 25, 40
        else:            lo, hi = 50, 70
        return (lo + hi) / 2 / 100
    except Exception:
        return 0.30


def generate(n, market='전체', capital=10_000_000, cash_pct=None):
    cash = _macro_cash_pct() if cash_pct is None else cash_pct
    summary, recs = AR.build_recommendations(
        timeframe='weekly', capital=capital, max_positions=n,
        market_filter=market, cash_pct=cash, primary_only=True)
    positions = []
    for r in recs:
        positions.append({
            'sym': r['sym'], 'name': r['name'], 'market': r['market'],
            'weight_pct': r['pos_pct'], 'entry': r['entry'],
            'total_score': r.get('total_score'), 'win_score': r.get('win_score'),
            'fund_score': r.get('fund_score'), 'signals': r.get('signals', []),
            'stop': r['stop'], 'target': r['target'],
        })
    return {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'week': datetime.now().strftime('%G-W%V'),
        'n': n, 'market': market, 'cash_pct': round(cash * 100, 0),
        'deployed_pct': summary['deployed_pct'], 'positions': positions,
    }


def generate_contrarian_kr(n=10, cash_pct=None,
                           dd_min=-60.0, dd_max=-15.0, per_max=15.0, roe_min=8.0):
    """🔄 역발상 KR — 조정장 엔진 (2026-07 국장 급락 때 모멘텀 엔진이 눈을 감던
    구조적 결함의 보완). 렌즈: '싸고(저PER) 돈 잘 버는(ROE·성장) 우량주가
    고점대비 -15~-60% 조정받았을 때' — 공포에 우량주를 줍는 접근.
    소스: value_kr.json(DART 공식재무 × 당일 시총) × mdd.json(낙폭).
    ⚠️ 이 엔진도 페이퍼 검증 대상 — 성적표에서 모멘텀 엔진과 똑같이 채점됨."""
    cash = _macro_cash_pct() if cash_pct is None else cash_pct
    try:
        val = json.loads(Path('results/value_kr.json').read_text(encoding='utf-8'))
        mdd = {s['sym']: s for s in
               json.loads(Path('results/mdd.json').read_text(encoding='utf-8'))['stocks']
               if s.get('market') == 'KR'}
    except Exception:
        return None
    cands = []
    for s in val.get('stocks', []):
        m = mdd.get(s['sym'])
        if not m or m.get('cur_dd') is None or not m.get('price'):
            continue
        dd = m['cur_dd']
        if not (dd_min <= dd <= dd_max):
            continue
        per, roe = s.get('per'), s.get('roe')
        if not per or per <= 0 or per > per_max or roe is None or roe < roe_min:
            continue
        og = s.get('op_growth')
        if not (og == '흑자전환' or (isinstance(og, (int, float)) and og > 0)):
            continue
        # 벡터 함정 필터: 위치가 싸도 펀더멘털이 '악화 중'이면 밸류 함정 → 제외
        tr = s.get('traj')
        if tr and tr.get('verdict') == 'deteriorating':
            continue
        # 궤적점수를 스코어에 반영 (개선 가속일수록 가점)
        tboost = 1 + (tr['traj_score'] / 7 * 0.5) if tr else 1.0
        score = roe / per * (1.2 if og == '흑자전환' else 1.0) * tboost
        cands.append({'sym': s['sym'], 'name': s['name'], 'score': round(score, 2),
                      'price': m['price'], 'per': per, 'roe': roe, 'dd': dd, 'og': og,
                      'marcap': s.get('marcap'), 'traj': tr})
    cands.sort(key=lambda x: -x['score'])
    top = cands[:n]
    if not top:
        return None
    deployed = round((1 - cash) * 100, 1)
    w = round(deployed / len(top), 1)
    positions = []
    for c in top:
        _ogs = c['og'] if isinstance(c['og'], str) else f"영업익 {c['og']:+.0f}%"
        _tr = c.get('traj') or {}
        positions.append({
            'sym': c['sym'], 'name': c['name'], 'market': 'KR',
            'weight_pct': w, 'entry': c['price'],
            'total_score': c['score'], 'win_score': None, 'fund_score': None,
            'signals': [f"PER {c['per']}", f"ROE {c['roe']:.0f}%",
                        f"낙폭 {c['dd']:.0f}%", _ogs],
            'traj': {'verdict_label': _tr.get('verdict_label'), 'traj_score': _tr.get('traj_score'),
                     'd_roe': _tr.get('d_roe'), 'd_opm': _tr.get('d_opm')} if _tr else None,
            'stop': round(c['price'] * 0.90, 4),      # 역발상은 변동 커서 -10%
            'target': round(c['price'] * 1.20, 4),    # 손익비 2:1
        })
    return {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'week': datetime.now().strftime('%G-W%V'),
        'n': len(positions), 'market': 'KR', 'engine': 'contrarian',
        'cash_pct': round(cash * 100, 0), 'deployed_pct': deployed,
        'positions': positions,
    }


def save_snapshot(p10, p20, ckr=None):
    cur = {'updated': datetime.now().strftime('%Y-%m-%d %H:%M'), 'p10': p10, 'p20': p20}
    if ckr:
        cur['ckr'] = ckr
    CURRENT.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding='utf-8')
    hist = []
    if HISTORY.exists():
        try:
            hist = json.loads(HISTORY.read_text(encoding='utf-8'))
        except Exception:
            hist = []
    wk = p10['week']
    entry = {'week': wk, 'date': p10['date'], 'p10': p10, 'p20': p20}
    if ckr:
        entry['ckr'] = ckr
    else:                                      # 같은 주 기존 ckr 보존 (p10/p20만 갱신될 때)
        old = next((h for h in hist if h.get('week') == wk), None)
        if old and old.get('ckr'):
            entry['ckr'] = old['ckr']
            cur['ckr'] = old['ckr']
            CURRENT.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding='utf-8')
    hist = [h for h in hist if h.get('week') != wk]
    hist.append(entry)
    HISTORY.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding='utf-8')


def _cur_price(sym, market):
    try:
        import FinanceDataReader as fdr
        from datetime import timedelta
        code = sym.replace('.KS', '').replace('.KQ', '')
        fsym = code if market == 'KR' else sym
        df = fdr.DataReader(fsym, (datetime.now() - timedelta(days=6)).strftime('%Y-%m-%d'))
        return float(df['Close'].iloc[-1]) if not df.empty else None
    except Exception:
        return None


_BENCH_MEMO = {}

def _bench_ret(bench_sym, start_date_str):
    """벤치마크 지수의 start_date→현재 수익률 %. (스냅샷·세트 간 재사용 메모)"""
    key = (bench_sym, start_date_str)
    if key in _BENCH_MEMO:
        return _BENCH_MEMO[key]
    ret = None
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader(bench_sym, start_date_str)
        c = df['Close'].dropna()
        if len(c) >= 2:
            ret = round((float(c.iloc[-1]) / float(c.iloc[0]) - 1) * 100, 2)
    except Exception:
        pass
    _BENCH_MEMO[key] = ret
    return ret


def analyze():
    """과거 스냅샷별 비중가중 포트폴리오 수익률(진입가 대비 현재가) + 벤치마크 대비 알파.
       벤치마크 = 포지션의 KR/US 비중대로 KOSPI·SPY를 섞은 같은 기간 수익률."""
    if not HISTORY.exists():
        return []
    hist = json.loads(HISTORY.read_text(encoding='utf-8'))
    out = []
    for h in hist:
        for key in ('p10', 'p20', 'ckr'):
            port = h.get(key) or {}
            poss = port.get('positions', [])
            if not poss:
                continue
            tot_w, wret = 0.0, 0.0
            details = []
            for p in poss:
                cur = _cur_price(p['sym'], p['market'])
                if cur is None or not p.get('entry'):
                    details.append({'sym': p['sym'], 'name': p['name'], 'market': p.get('market'),
                                    'weight_pct': p['weight_pct'], 'entry': p.get('entry'),
                                    'cur': None, 'ret': None, 'signals': p.get('signals', []),
                                    'stop': p.get('stop'), 'target': p.get('target')})
                    continue
                ret = (cur / p['entry'] - 1) * 100
                w = p['weight_pct']
                wret += w * ret; tot_w += w
                hit_stop = p.get('stop') and cur <= p['stop']
                hit_target = p.get('target') and cur >= p['target']
                details.append({'sym': p['sym'], 'name': p['name'], 'market': p.get('market'),
                                'weight_pct': w, 'entry': p['entry'], 'cur': round(cur, 4),
                                'ret': round(ret, 1), 'signals': p.get('signals', []),
                                'stop': p.get('stop'), 'target': p.get('target'),
                                'hit_stop': bool(hit_stop), 'hit_target': bool(hit_target)})
            if tot_w > 0:
                port_ret = round(wret / tot_w, 2)
                # 벤치마크: KR/US 비중 가중 (KOSPI·SPY, 같은 기간)
                kr_w = sum(p['weight_pct'] for p in poss if p.get('market') == 'KR')
                us_w = sum(p['weight_pct'] for p in poss if p.get('market') == 'US')
                kr_b = _bench_ret('KS11', h['date']) if kr_w else None
                us_b = _bench_ret('SPY', h['date']) if us_w else None
                bw, br = 0.0, 0.0
                for w, b in ((kr_w, kr_b), (us_w, us_b)):
                    if w and b is not None:
                        bw += w; br += w * b
                bench = round(br / bw, 2) if bw > 0 else None
                out.append({'week': h['week'], 'date': h['date'], 'set': key, 'n': len(poss),
                            'port_return': port_ret, 'bench_return': bench,
                            'alpha': round(port_ret - bench, 2) if bench is not None else None,
                            'cash_pct': port.get('cash_pct'), 'details': details})
    return out


def _main():
    if len(sys.argv) > 1 and sys.argv[1] == 'analyze':
        res = analyze()
        if not res:
            print("히스토리 없음 — 먼저 python weekly_portfolio.py 로 스냅샷 생성")
            return
        print("\n📊 주간 포트폴리오 사후분석 (비중가중 수익률)")
        for r in res:
            _b = f" · 벤치 {r['bench_return']:+.2f}% · 알파 {r['alpha']:+.2f}%p" if r.get('bench_return') is not None else ""
            print(f"  {r['week']} [{r['set']}] {r['n']}종목 · 현금{r['cash_pct']:.0f}% "
                  f"→ 포트 수익률 {r['port_return']:+.2f}%{_b}")
        return

    cash = _macro_cash_pct()
    print(f"매크로 기반 현금비중: {cash*100:.0f}%  · 10선·20선 생성 중...")
    p10 = generate(10, cash_pct=cash)
    p20 = generate(20, cash_pct=cash)
    save_snapshot(p10, p20)
    for tag, p in [('10선', p10), ('20선', p20)]:
        print(f"\n══ 주간 {tag} ({p['date']}) · 현금 {p['cash_pct']:.0f}% · 투입 {p['deployed_pct']}% ══")
        print(f"  {'종목':<14}{'시장':>4}{'비중%':>7}{'종합':>6}{'진입':>11}")
        for x in p['positions']:
            print(f"  {x['name'][:12]:<14}{x['market']:>4}{x['weight_pct']:>6.1f}%"
                  f"{(x['total_score'] or 0):>6.0f}{x['entry']:>11,.0f}")
    print(f"\n✅ 저장: {CURRENT} · 히스토리 {HISTORY}")


if __name__ == '__main__':
    _main()
