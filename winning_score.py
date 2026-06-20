"""
위닝 셋업 복합 스코어 (Winning Setup Score) — v1
─────────────────────────────────────────────────────────────────
멍거의 inversion: "오르는 종목의 지문"을 점수화하고, "지는 패턴"은 감점.

가중치는 감(感)이 아니라 **우리 자신의 백테스트 13주 샤프**에서 역산했다.
(results/backtest 리포트 기준 — 과최적화 방어용으로 우리 데이터에 근거)

  신호            13주 샤프   →  배점(가중치)
  이평수렴(베이스)   1.25      →  25   ← 변동성 수축·정배열, 최강 단일신호
  52주신고가         0.90      →  18   (+ 신고가 근접 보너스)
  컵핸들(베이스변형)  1.28      →  13
  5주라이딩          0.82      →   8
  RSI/MACD          0.73      →   6
  거래량확인         0.20(단독) →   8   (단독 약함, 돌파 '확인'으로만)
  상대강도(RS)        —        →  12   (시장보다 강한가)
  실적 가속(펀더)      —        →  10   (KR: CANSLIM C·A / US: 데이터없어 제외 후 재정규화)

시너지: 52주신고가 + 베이스(이평수렴/컵)가 동시 → +8 (백테스트 최강 조합 1.33~1.36)
감점(inversion): 신고가 대비 -25% 이탈(주도주 아님) → ×0.6
자기보정: 각 신호 기여도에 페이퍼 트레이딩 실전 신뢰계수를 곱함(라쿤 오류수정)
매크로: 레짐에 따라 전체 ×0.75~1.0 (위험장에선 확신 축소)

CLI:
  python winning_score.py --market KR --top 20
  python winning_score.py --top 30
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import json
import argparse
from pathlib import Path

SCREENER = Path('results/screener_latest.json')
CANSLIM  = Path('results/canslim_latest.json')
WEIGHTS  = Path('results/signal_live_weights.json')

# ── 백테스트 샤프 기반 배점 (component → max점수) ────────────────────
W = {
    'maconv': 25,   # 이평수렴(베이스)
    'high52': 18,   # 52주 신고가 + 근접도
    'cup':    13,   # 컵핸들
    'ma5':     8,   # 5주 라이딩
    'rsimacd': 6,   # RSI/MACD
    'vol':     8,   # 거래량 확인
    'rs':     12,   # 상대강도
    'fund':   10,   # 실적 가속 (KR만)
}
SYNERGY_BONUS = 8           # 52주 + 베이스 동시
LAGGARD_PENALTY = 0.6       # 신고가 -25% 이탈
LAGGARD_DIST = -25.0

# 신호 플래그 ↔ 라이브 신뢰계수 키
LIVE_KEY = {'maconv': 'sig_maconv', 'high52': 'sig_52w', 'cup': 'sig_cup',
            'ma5': 'sig_ma5', 'rsimacd': 'sig_rsimacd', 'vol': 'sig_vol'}


def _load(p):
    try:
        return json.loads(Path(p).read_text(encoding='utf-8'))
    except Exception:
        return None


def _live_mults():
    w = _load(WEIGHTS)
    if not w:
        return {}
    return {k: v.get('mult', 1.0) for k, v in w.get('weights', {}).items()}


def _canslim_map():
    c = _load(CANSLIM)
    if not c:
        return {}, True
    market_ok = c.get('market_ok', True)
    return {s['sym']: s for s in c.get('stocks', [])}, market_ok


def score_stock(s, can=None, live=None):
    """
    s: screener 종목 dict (기술 신호 + dist_52w + vol_ratio)
    can: 같은 종목의 canslim dict (rs_pct, c_growth_pct, a_growth_y1) or None
    live: {sig_*: mult}
    반환: (score 0~100, breakdown dict, grade, disq_bool)
    """
    live = live or {}
    bd = {}            # 항목별 획득 점수
    avail = 0.0        # 적용 가능한 총 배점(재정규화용)

    def lm(comp):      # 라이브 신뢰계수 (없으면 1.0)
        return live.get(LIVE_KEY.get(comp, ''), 1.0)

    # ── 기술 신호 (있으면 만점×신뢰계수, 없으면 0) ──
    for comp, flag in [('maconv', 'sig_maconv'), ('cup', 'sig_cup'),
                       ('ma5', 'sig_ma5'), ('rsimacd', 'sig_rsimacd'),
                       ('vol', 'sig_vol')]:
        avail += W[comp]
        bd[comp] = round(W[comp] * lm(comp), 1) if s.get(flag) else 0.0

    # ── 52주 신고가 + 근접도 ──
    avail += W['high52']
    dist = s.get('dist_52w')
    if s.get('sig_52w'):
        bd['high52'] = round(W['high52'] * lm('high52'), 1)
    elif dist is not None and dist >= -8:   # 신호엔 안 잡혀도 근접하면 부분점수
        bd['high52'] = round(W['high52'] * 0.5 * (1 - min(abs(dist), 8) / 8), 1)
    else:
        bd['high52'] = 0.0

    # ── 상대강도 RS ──
    avail += W['rs']
    if can and can.get('rs_pct') is not None:
        bd['rs'] = round(W['rs'] * (can['rs_pct'] / 100), 1)        # KR: CANSLIM 퍼센타일
    elif dist is not None:
        # 프록시: 신고가에 가까울수록 강함 (0% → 만점, -25% → 0)
        bd['rs'] = round(W['rs'] * max(0, 1 - abs(min(dist, 0)) / 25), 1)
    else:
        bd['rs'] = 0.0

    # ── 실적 가속 (KR CANSLIM만; US는 배점에서 제외 → 재정규화) ──
    if can:
        avail += W['fund']
        f = 0.0
        cg = can.get('c_growth_pct')      # 분기 순이익 성장
        a1 = can.get('a_growth_y1')       # 연간 성장
        if isinstance(cg, (int, float)):
            f += W['fund'] * 0.6 * max(0, min(cg, 50) / 50)
        elif cg == '흑자전환':
            f += W['fund'] * 0.6
        if isinstance(a1, (int, float)):
            f += W['fund'] * 0.4 * max(0, min(a1, 30) / 30)
        bd['fund'] = round(f, 1)

    # ── 시너지: 52주 + 베이스 ──
    base = s.get('sig_maconv') or s.get('sig_cup')
    bonus = SYNERGY_BONUS if (s.get('sig_52w') and base) else 0.0

    raw = sum(bd.values()) + bonus
    # 재정규화: 적용가능 배점(avail) 기준 100점 환산 (US는 fund 빠져 avail 작음)
    norm = raw / (avail + SYNERGY_BONUS) * 100 if avail > 0 else 0.0

    # ── 감점 (inversion): 신고가에서 너무 멀면 주도주 아님 ──
    disq = dist is not None and dist < LAGGARD_DIST
    if disq:
        norm *= LAGGARD_PENALTY

    score = round(min(norm, 100), 1)
    grade = 'S' if score >= 80 else ('A' if score >= 65 else ('B' if score >= 50 else 'C'))
    return score, bd, grade, disq


def rank_all(market_filter='전체', regime_mult=1.0):
    scr = _load(SCREENER)
    if not scr:
        return []
    can_map, market_ok = _canslim_map()
    live = _live_mults()
    rows = []
    for s in scr['stocks']:
        if market_filter != '전체' and s['market'] != market_filter:
            continue
        can = can_map.get(s['sym'])
        score, bd, grade, disq = score_stock(s, can, live)
        score = round(score * regime_mult, 1)
        rows.append({
            'sym': s['sym'], 'name': s['name'], 'market': s['market'],
            'sector': s.get('sector', ''), 'score': score, 'grade': grade,
            'disq': disq, 'dist_52w': s.get('dist_52w'),
            'marcap': s.get('marcap'),
            'signals': s.get('signals', []), 'breakdown': bd,
            'has_fund': can is not None,
        })
    rows.sort(key=lambda x: -x['score'])
    return rows


def _main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--market', default='전체', choices=['전체', 'KR', 'US'])
    ap.add_argument('--top', type=int, default=25)
    args = ap.parse_args()

    rows = rank_all(args.market)
    if not rows:
        print("데이터 없음 — weekly_run.py 먼저")
        return
    print("\n" + "═" * 78)
    print(f"  🏅 위닝 셋업 스코어  |  {args.market}  |  상위 {args.top}  (가중치=백테스트 샤프 역산)")
    print("═" * 78)
    print(f"  {'등급':<4}{'점수':>6}  {'종목':<14}{'시장':>4}{'신고가거리':>10}  {'신호'}")
    print("  " + "─" * 74)
    for r in rows[:args.top]:
        d = f"{r['dist_52w']:+.0f}%" if r['dist_52w'] is not None else '-'
        flag = ' ⚠️이탈' if r['disq'] else ''
        print(f"  {r['grade']:<4}{r['score']:>6.1f}  {r['name'][:12]:<14}{r['market']:>4}"
              f"{d:>10}  {', '.join(r['signals'][:3])}{flag}")
    print("  " + "─" * 74)
    from collections import Counter
    gc = Counter(r['grade'] for r in rows)
    print(f"  등급분포  S:{gc['S']}  A:{gc['A']}  B:{gc['B']}  C:{gc['C']}  (총 {len(rows)})")
    print("═" * 78)


if __name__ == '__main__':
    _main()
