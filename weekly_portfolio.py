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
        import requests
        FRED = '7c2403fc4ee8a087ed80776a259b9273'
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


def save_snapshot(p10, p20):
    CURRENT.write_text(json.dumps({'updated': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'p10': p10, 'p20': p20}, ensure_ascii=False, indent=2), encoding='utf-8')
    hist = []
    if HISTORY.exists():
        try:
            hist = json.loads(HISTORY.read_text(encoding='utf-8'))
        except Exception:
            hist = []
    wk = p10['week']
    hist = [h for h in hist if h.get('week') != wk]
    hist.append({'week': wk, 'date': p10['date'], 'p10': p10, 'p20': p20})
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


def analyze():
    """과거 스냅샷별 비중가중 포트폴리오 수익률(진입가 대비 현재가)."""
    if not HISTORY.exists():
        return []
    hist = json.loads(HISTORY.read_text(encoding='utf-8'))
    out = []
    for h in hist:
        for key in ('p10', 'p20'):
            port = h.get(key) or {}
            poss = port.get('positions', [])
            if not poss:
                continue
            tot_w, wret = 0.0, 0.0
            details = []
            for p in poss:
                cur = _cur_price(p['sym'], p['market'])
                if cur is None or not p.get('entry'):
                    continue
                ret = (cur / p['entry'] - 1) * 100
                w = p['weight_pct']
                wret += w * ret; tot_w += w
                details.append((p['name'], round(ret, 1)))
            if tot_w > 0:
                out.append({'week': h['week'], 'set': key, 'n': len(poss),
                            'port_return': round(wret / tot_w, 2),
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
            print(f"  {r['week']} [{r['set']}] {r['n']}종목 · 현금{r['cash_pct']:.0f}% "
                  f"→ 포트 수익률 {r['port_return']:+.2f}%")
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
