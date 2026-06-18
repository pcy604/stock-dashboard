"""
일/주/월 통합 자동 포트폴리오 추천 + 손익비 기반 리스크 사이징 (v1)
─────────────────────────────────────────────────────────────────
"신호 → 종목 → 얼마나 살까 → 어디서 자를까"를 한 번에.

타임프레임:
  monthly  월간 — perf_latest.json (4주 모멘텀 + 현재신호)   보유 ~1~3개월
  weekly   주간 — screener_latest.json (주봉 6신호)          보유 ~2~6주
  daily    일간 — 주간 후보 + 일봉 진입타이밍(entry_timing)  보유 ~3~15일

손익비(R:R) 사이징 — 프로 방식 '고정 분율 리스크':
  · 손절폭 stop_pct (예: 7%)
  · 손익비 rr (예: 2.0 → 목표는 손절폭의 2배 = +14%)
  · 1회 최대손실 risk_per_trade (예: 자본의 1%)
  → 포지션 크기 = (자본 × risk%) ÷ 손절폭.  손절에 닿아도 손실은 딱 risk%.
  → 손익비가 정한 '본전 승률' = 1 / (1 + rr).  이보다 실제 승률이 높아야 이득.

신뢰계수 연동: 페이퍼 트레이딩 실전 신뢰계수(signal_live_weights.json)를
  점수에 곱해, 실전에서 죽쑤는 신호의 비중을 자동으로 깎는다(라쿤 '오류수정').

CLI:
  python auto_recommend.py weekly   --capital 10000000 --stop 7 --rr 2
  python auto_recommend.py monthly  --capital 10000000 --stop 10 --rr 2.5
  python auto_recommend.py daily    --capital 10000000 --stop 5 --rr 2   (느림: 일봉조회)
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta

SCREENER = Path('results/screener_latest.json')
PERF     = Path('results/perf_latest.json')
WEIGHTS  = Path('results/signal_live_weights.json')

SIG_FLAGS = ['sig_52w', 'sig_vol', 'sig_ma5', 'sig_cup', 'sig_maconv', 'sig_rsimacd']
SIG_LABEL = {'sig_52w': '52주신고가', 'sig_vol': '거래량폭발', 'sig_ma5': '5주라이딩',
             'sig_cup': '컵핸들', 'sig_maconv': '이평수렴', 'sig_rsimacd': 'RSI/MACD'}

# 타임프레임별 기본 손절/손익비 가이드 (사용자가 덮어쓸 수 있음)
TF_DEFAULTS = {
    'daily':   {'stop': 5,  'rr': 2.0,  'hold': '3~15일',  'label': '일간'},
    'weekly':  {'stop': 7,  'rr': 2.0,  'hold': '2~6주',   'label': '주간'},
    'monthly': {'stop': 10, 'rr': 2.5,  'hold': '1~3개월', 'label': '월간'},
}


def _load(p):
    try:
        return json.loads(Path(p).read_text(encoding='utf-8'))
    except Exception:
        return None


# ── 신호 점수 (타임프레임 공통) ──────────────────────────────────────
def _signal_score(flags: dict, dist_52w=None):
    """1급(52주신고가·이평수렴) 가중. 보조신호 가산. 신고가 거리 보정."""
    is52  = flags.get('sig_52w');    isMac = flags.get('sig_maconv')
    isCup = flags.get('sig_cup');    isMa5 = flags.get('sig_ma5')
    isRsi = flags.get('sig_rsimacd'); isVol = flags.get('sig_vol')
    score = 0
    if is52 and isMac: score += 5
    elif is52 or isMac: score += 4
    if isCup: score += 2
    if isVol: score += 2
    if isMa5: score += 1
    if isRsi: score += 1
    if dist_52w is not None:
        if 0 <= dist_52w <= 5:   score += 2
        elif -5 <= dist_52w < 0: score += 1
        elif dist_52w > 40:      score -= 2
        elif dist_52w > 20:      score -= 1
    has_primary = bool(is52 or isMac)
    return score, has_primary


def _live_mult(flags: dict, weights: dict):
    """종목의 활성 신호들의 실전 신뢰계수 평균 (없으면 1.0)."""
    if not weights:
        return 1.0
    w = weights.get('weights', {})
    mults = [w[f]['mult'] for f in SIG_FLAGS if flags.get(f) and f in w]
    return round(sum(mults) / len(mults), 2) if mults else 1.0


# ── 현재가 조회 (주간/일간 상위 종목용) ──────────────────────────────
def _price(sym, market):
    try:
        import FinanceDataReader as fdr
        code = sym.replace('.KS', '').replace('.KQ', '')
        fdr_sym = code if market == 'KR' else sym
        start = (datetime.now() - timedelta(days=6)).strftime('%Y-%m-%d')
        df = fdr.DataReader(fdr_sym, start)
        return float(df['Close'].iloc[-1]) if not df.empty else None
    except Exception:
        return None


# ── 후보 수집 (타임프레임별) ─────────────────────────────────────────
def _candidates(timeframe, market_filter):
    """반환: [{sym,name,market,flags,dist_52w,price(optional),mom}]"""
    out = []
    if timeframe == 'monthly':
        data = _load(PERF)
        if not data:
            return []
        for s in data['stocks']:
            if market_filter != '전체' and s['market'] != market_filter:
                continue
            # perf_latest는 현재신호를 now_sig_* 로 저장 → 공통 sig_* 키로 매핑
            flags = {f: bool(s.get(f.replace('sig_', 'now_sig_'), False)) for f in SIG_FLAGS}
            out.append({
                'sym': s['sym'], 'name': s['name'], 'market': s['market'],
                'flags': flags, 'dist_52w': None,
                'price': s.get('curr_price'), 'mom': s.get('ret_4w', 0),
                'signals': s.get('sigs_now', []),
            })
    else:  # weekly / daily 는 screener 신호 풀 사용
        data = _load(SCREENER)
        if not data:
            return []
        for s in data['stocks']:
            if market_filter != '전체' and s['market'] != market_filter:
                continue
            flags = {f: bool(s.get(f)) for f in SIG_FLAGS}
            out.append({
                'sym': s['sym'], 'name': s['name'], 'market': s['market'],
                'flags': flags, 'dist_52w': s.get('dist_52w'),
                'price': None, 'mom': s.get('pct_change', 0),
                'signals': s.get('signals', []),
            })
    return out


# ── 핵심: 추천 생성 ──────────────────────────────────────────────────
def build_recommendations(timeframe='weekly', capital=10_000_000,
                          stop_pct=None, rr=None, risk_per_trade=1.0,
                          max_positions=6, market_filter='전체',
                          cash_pct=0.30, primary_only=True,
                          use_live_weights=True, use_entry_timing=False):
    tf = TF_DEFAULTS.get(timeframe, TF_DEFAULTS['weekly'])
    stop_pct = tf['stop'] if stop_pct is None else stop_pct
    rr = tf['rr'] if rr is None else rr
    target_pct = round(stop_pct * rr, 1)
    breakeven_wr = round(1 / (1 + rr) * 100, 1)

    weights = _load(WEIGHTS) if use_live_weights else None

    cands = _candidates(timeframe, market_filter)
    scored = []
    for c in cands:
        score, has_prim = _signal_score(c['flags'], c.get('dist_52w'))
        if primary_only and not has_prim:
            continue
        mult = _live_mult(c['flags'], weights)
        c['score'] = score
        c['live_mult'] = mult
        c['adj_score'] = round(score * mult, 2)
        scored.append(c)

    scored.sort(key=lambda x: (-x['adj_score'], -x.get('mom', 0)))
    top = scored[:max_positions]

    # 일간: 상위 후보에 일봉 진입타이밍 적용 → '진입적정'만 통과
    if timeframe == 'daily' and use_entry_timing and top:
        try:
            from entry_timing import batch_check
            res = batch_check([{'sym': c['sym'], 'market': c['market'],
                                'dist_52w': c.get('dist_52w')} for c in top])
            for c in top:
                g = res.get(c['sym'], {})
                c['entry_grade'] = g.get('grade', '⚪')
                if g.get('cur_price'):
                    c['price'] = g['cur_price']
            top = [c for c in top if '진입적정' in c.get('entry_grade', '')] or top
        except Exception:
            pass

    # 현재가 채우기 (없는 것만)
    for c in top:
        if not c.get('price'):
            c['price'] = _price(c['sym'], c['market'])

    # ── 손익비 기반 리스크 사이징 ──
    deployable = capital * (1 - cash_pct)
    per_slot_cap = deployable / max(max_positions, 1)
    risk_amt = capital * risk_per_trade / 100

    recs = []
    cash_used = 0.0
    for c in top:
        px = c.get('price')
        if not px or px <= 0:
            continue
        size_by_risk = risk_amt / (stop_pct / 100)
        pos_value = min(size_by_risk, per_slot_cap, deployable - cash_used)
        if pos_value <= 0:
            break
        qty = pos_value / px
        actual_risk = qty * px * stop_pct / 100
        reward_amt = actual_risk * rr
        cash_used += pos_value

        entry = px
        stop_px = entry * (1 - stop_pct / 100)
        target_px = entry * (1 + target_pct / 100)

        recs.append({
            'sym': c['sym'], 'name': c['name'], 'market': c['market'],
            'signals': c.get('signals', []),
            'score': c['score'], 'live_mult': c['live_mult'], 'adj_score': c['adj_score'],
            'entry': round(entry, 2 if c['market'] == 'US' else 0),
            'stop': round(stop_px, 2 if c['market'] == 'US' else 0),
            'target': round(target_px, 2 if c['market'] == 'US' else 0),
            'qty': round(qty, 4 if c['market'] == 'US' else 2),
            'pos_value': round(pos_value),
            'pos_pct': round(pos_value / capital * 100, 1),
            'risk_amt': round(actual_risk),
            'reward_amt': round(reward_amt),
            'entry_grade': c.get('entry_grade', ''),
        })

    total_risk = sum(r['risk_amt'] for r in recs)
    summary = {
        'timeframe': timeframe, 'tf_label': tf['label'], 'hold': tf['hold'],
        'capital': capital, 'cash_pct': round(cash_pct * 100, 0),
        'stop_pct': stop_pct, 'rr': rr, 'target_pct': target_pct,
        'breakeven_wr': breakeven_wr, 'risk_per_trade': risk_per_trade,
        'n': len(recs),
        'deployed': sum(r['pos_value'] for r in recs),
        'deployed_pct': round(sum(r['pos_value'] for r in recs) / capital * 100, 1),
        'total_risk': total_risk,
        'portfolio_heat': round(total_risk / capital * 100, 2),  # 전체가 손절시 총손실%
        'max_reward': sum(r['reward_amt'] for r in recs),
    }
    return summary, recs


# ── CLI ──────────────────────────────────────────────────────────────
def _main():
    ap = argparse.ArgumentParser()
    ap.add_argument('timeframe', choices=['daily', 'weekly', 'monthly'])
    ap.add_argument('--capital', type=float, default=10_000_000)
    ap.add_argument('--stop', type=float, default=None)
    ap.add_argument('--rr', type=float, default=None)
    ap.add_argument('--risk', type=float, default=1.0, help='1회 최대손실 퍼센트 (자본 대비)')
    ap.add_argument('--n', type=int, default=6)
    ap.add_argument('--market', default='전체', choices=['전체', 'KR', 'US'])
    ap.add_argument('--cash', type=float, default=30, help='현금 비중 퍼센트')
    args = ap.parse_args()

    summary, recs = build_recommendations(
        args.timeframe, args.capital, args.stop, args.rr, args.risk,
        args.n, args.market, cash_pct=args.cash / 100,
        use_entry_timing=(args.timeframe == 'daily'),
    )

    s = summary
    print("\n" + "═" * 76)
    print(f"  🎯 {s['tf_label']} 자동 추천  |  보유 {s['hold']}  |  자본 {s['capital']:,.0f}원")
    print(f"  손절 -{s['stop_pct']}%  목표 +{s['target_pct']}%  손익비 1:{s['rr']}  "
          f"본전승률 {s['breakeven_wr']}%  1회리스크 {s['risk_per_trade']}%")
    print("═" * 76)
    if not recs:
        print("  추천 종목 없음 (데이터 비었거나 조건 미달). 스크리너부터 갱신하세요.")
        return
    print(f"  {'종목':<14}{'시장':>4}{'진입':>11}{'손절':>11}{'목표':>11}"
          f"{'수량':>9}{'비중%':>7}{'리스크':>10}{'신뢰':>6}")
    print("  " + "─" * 88)
    for r in recs:
        print(f"  {r['name'][:12]:<14}{r['market']:>4}{r['entry']:>11,.0f}{r['stop']:>11,.0f}"
              f"{r['target']:>11,.0f}{r['qty']:>9.2f}{r['pos_pct']:>6.1f}%"
              f"{r['risk_amt']:>10,.0f}{r['live_mult']:>6.2f}")
    print("  " + "─" * 88)
    print(f"  투입 {s['deployed']:,.0f}원 ({s['deployed_pct']}%) · 현금 {s['cash_pct']:.0f}% · "
          f"포트폴리오 히트 {s['portfolio_heat']}% (전부 손절 시 총손실)")
    print(f"  최대 기대수익(전부 목표 도달) {s['max_reward']:,.0f}원  vs  최대손실 {s['total_risk']:,.0f}원  "
          f"= 손익비 1:{s['rr']}")
    print("═" * 76)


if __name__ == '__main__':
    _main()
