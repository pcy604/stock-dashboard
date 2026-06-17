"""
포워드 페이퍼 트레이딩 + 오류수정 피드백 루프 (v1)
─────────────────────────────────────────────────────────────────
"신호가 나온다 ≠ 돈 번다." 그 증거를 0줄에서 시작해 매주 쌓는다.

설계 의도 (라쿤 홍진채의 '오류수정' + 우리에게 빠졌던 포워드 트랙레코드):
  1) log    — 신호 나올 때마다 가상 진입을 기록 (돈 안 씀)
  2) update — 1·4·13주 뒤 실제 가격으로 실현수익 계산
  3) report — 신호별 '실전 vs 백테스트' 대조 → 라이브 신뢰도 계수 산출
              괴리가 크면 그 신호의 비중을 자동으로 깎는다 (대응)

저장: results/paper_trades.json   (open/closed 신호 + 실현결과)
가격: FinanceDataReader (실거래와 동일 소스)

CLI:
  python paper_trade.py log      # 현재 screener_latest.json 신호를 가상진입 기록
  python paper_trade.py update   # 만기 도래분 실현수익 갱신
  python paper_trade.py report   # 신호별 실전 신뢰도 리포트
  python paper_trade.py weights  # 대시보드/추천에 쓸 라이브 신뢰도 계수(JSON)
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import json
from pathlib import Path
from datetime import datetime, timedelta

LEDGER = Path('results/paper_trades.json')
SCREENER = Path('results/screener_latest.json')
WEIGHTS_OUT = Path('results/signal_live_weights.json')

HORIZONS = {'1w': 7, '4w': 28, '13w': 91}     # 라벨 → 캘린더 일수

# 왕복 거래비용 (backtest_validation과 동일 철학, 보수적)
COST = {'KR': 0.40 / 100, 'US': 0.25 / 100}

SIG_FLAGS = ['sig_52w', 'sig_vol', 'sig_ma5', 'sig_cup', 'sig_maconv', 'sig_rsimacd']
SIG_LABEL = {
    'sig_52w': '52주신고가', 'sig_vol': '거래량폭발', 'sig_ma5': '5주라이딩',
    'sig_cup': '컵핸들', 'sig_maconv': '이평수렴', 'sig_rsimacd': 'RSI/MACD',
}

# 백테스트 기준 기대값(순EV%, 비용차감 후 근사) — 실전과 대조할 앵커
# 출처: results/backtest 리포트의 4주·13주 신호별 기대값을 보수적으로 반영
BACKTEST_REF = {
    'sig_52w':     {'4w': 1.0, '13w': 3.3},
    'sig_vol':     {'4w': 0.8, '13w': 0.8},
    'sig_ma5':     {'4w': 0.4, '13w': 2.2},
    'sig_cup':     {'4w': 0.5, '13w': 2.4},
    'sig_maconv':  {'4w': 1.6, '13w': 4.3},
    'sig_rsimacd': {'4w': 0.9, '13w': 2.7},
}


# ── 저장/로드 ────────────────────────────────────────────────────────
def _load():
    if LEDGER.exists():
        try:
            return json.loads(LEDGER.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {'created': datetime.now().strftime('%Y-%m-%d'), 'trades': []}


def _save(data):
    LEDGER.parent.mkdir(exist_ok=True)
    LEDGER.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


# ── 가격 조회 ────────────────────────────────────────────────────────
def _price_on_or_before(sym, market, target_date):
    """target_date 이하에서 가장 최근 종가. 데이터 없으면 None."""
    try:
        import FinanceDataReader as fdr
        code = sym.replace('.KS', '').replace('.KQ', '')
        fdr_sym = code if market == 'KR' else sym
        start = (target_date - timedelta(days=12)).strftime('%Y-%m-%d')
        end = (target_date + timedelta(days=1)).strftime('%Y-%m-%d')
        df = fdr.DataReader(fdr_sym, start, end)
        if df.empty:
            return None
        return float(df['Close'].iloc[-1])
    except Exception:
        return None


def _price_latest(sym, market):
    return _price_on_or_before(sym, market, datetime.now())


# ── 1) LOG: 신호 → 가상 진입 기록 ────────────────────────────────────
def log_from_screener(min_signals=1, max_log=40):
    if not SCREENER.exists():
        print("screener_latest.json 없음 — weekly_run.py 먼저 실행")
        return
    scr = json.loads(SCREENER.read_text(encoding='utf-8'))
    scr_date = scr.get('date', datetime.now().strftime('%Y-%m-%d'))
    data = _load()

    # 같은 (종목+주차) 중복 진입 방지
    existing = {(t['sym'], t['log_date']) for t in data['trades']}

    stocks = sorted(scr['stocks'], key=lambda s: -s.get('total_signals', 0))
    added = 0
    for s in stocks:
        if added >= max_log:
            break
        if s.get('total_signals', 0) < min_signals:
            continue
        key = (s['sym'], scr_date)
        if key in existing:
            continue
        px = _price_latest(s['sym'], s['market'])
        if px is None or px <= 0:
            continue
        flags = {f: bool(s.get(f)) for f in SIG_FLAGS}
        data['trades'].append({
            'id':        f"{s['sym']}_{scr_date}",
            'sym':       s['sym'],
            'name':      s['name'],
            'market':    s['market'],
            'log_date':  scr_date,
            'entry_px':  round(px, 4),
            'flags':     flags,
            'signals':   s.get('signals', []),
            'status':    'open',
            'realized':  {},          # {'1w': {'date','px','ret'}, ...}
        })
        added += 1
    _save(data)
    print(f"가상 진입 기록: {added}개 (기준일 {scr_date}) · 누적 {len(data['trades'])}건")


# ── 2) UPDATE: 만기 도래분 실현수익 계산 ─────────────────────────────
def update_outcomes():
    data = _load()
    today = datetime.now()
    updated = 0
    closed = 0
    for t in data['trades']:
        if t['status'] == 'closed':
            continue
        log_dt = datetime.strptime(t['log_date'], '%Y-%m-%d')
        cost = COST.get(t['market'], 0.004)
        for label, days in HORIZONS.items():
            if label in t['realized']:
                continue
            mature = log_dt + timedelta(days=days)
            if today < mature:
                continue
            px = _price_on_or_before(t['sym'], t['market'], mature)
            if px is None or t['entry_px'] <= 0:
                continue
            gross = px / t['entry_px'] - 1
            net = gross - cost
            t['realized'][label] = {
                'date': mature.strftime('%Y-%m-%d'),
                'px': round(px, 4),
                'ret': round(net * 100, 2),
            }
            updated += 1
        if '13w' in t['realized']:
            t['status'] = 'closed'
            closed += 1
    _save(data)
    print(f"실현수익 갱신: {updated}개 구간 · 신규 종료 {closed}건")


# ── 3) REPORT: 신호별 실전 vs 백테스트 ───────────────────────────────
def _agg_by_signal(trades, horizon):
    """각 신호 플래그를 가진 가상매매들의 실현수익 집계."""
    out = {}
    for flag in SIG_FLAGS:
        rets = [t['realized'][horizon]['ret']
                for t in trades
                if t['flags'].get(flag) and horizon in t['realized']]
        if len(rets) < 1:
            out[flag] = None
            continue
        n = len(rets)
        wr = sum(1 for r in rets if r > 0) / n * 100
        avg = sum(rets) / n
        out[flag] = {'n': n, 'wr': round(wr, 1), 'live_ev': round(avg, 2)}
    return out


def report():
    data = _load()
    trades = data['trades']
    n_total = len(trades)
    n_closed = sum(1 for t in trades if t['status'] == 'closed')
    n_matured_4w = sum(1 for t in trades if '4w' in t['realized'])

    print("\n" + "═" * 72)
    print("  📒 포워드 페이퍼 트레이딩 — 실전 신뢰도 리포트")
    print(f"  누적 가상매매 {n_total}건 · 4주 만기 {n_matured_4w}건 · 종료(13주) {n_closed}건")
    print("═" * 72)

    if n_matured_4w == 0:
        days_left = "데이터가 아직 익지 않음"
        if trades:
            first = min(datetime.strptime(t['log_date'], '%Y-%m-%d') for t in trades)
            ready = first + timedelta(days=28)
            days_left = f"첫 4주 만기 예정일: {ready.strftime('%Y-%m-%d')}"
        print(f"\n  아직 실현된 구간이 없습니다. {days_left}")
        print("  → 매주 log + update를 돌리면 여기 성적표가 채워집니다.")
        print("═" * 72)
        return

    for horizon in ['4w', '13w']:
        agg = _agg_by_signal(trades, horizon)
        if all(v is None for v in agg.values()):
            continue
        print(f"\n  ── {horizon} 보유 · 신호별 실전 vs 백테스트 ──────────────────")
        print(f"  {'신호':<12}{'표본':>5}{'실전승률':>9}{'실전EV':>9}{'백테EV':>9}{'괴리':>9}{'신뢰계수':>9}")
        print(f"  {'─'*11} {'─'*4} {'─'*7} {'─'*7} {'─'*7} {'─'*7} {'─'*7}")
        for flag in SIG_FLAGS:
            v = agg[flag]
            ref = BACKTEST_REF[flag][horizon]
            if v is None:
                print(f"  {SIG_LABEL[flag]:<12}{'—':>5}   (표본 없음)")
                continue
            gap = v['live_ev'] - ref
            mult = _reliability_mult(v['live_ev'], ref, v['n'])
            flag_mark = '✅' if gap >= 0 else ('⚠️' if gap > -1.5 else '❌')
            print(f"  {SIG_LABEL[flag]:<12}{v['n']:>5}{v['wr']:>8.1f}%"
                  f"{v['live_ev']:>8.2f}%{ref:>8.2f}%{gap:>+8.2f}%{mult:>8.2f}  {flag_mark}")

    print("\n  ─ 해석 ──────────────────────────────────────────────────────")
    print("  실전EV가 백테EV보다 크게 낮으면(괴리 음수↑) → 그 신호 과최적화 의심.")
    print("  신뢰계수<1 → 추천/사이징에서 비중 자동 축소(대응). 표본 늘수록 신뢰↑.")
    print("═" * 72)


def _reliability_mult(live_ev, ref_ev, n):
    """라이브 신뢰도 계수.
       - 실전이 백테스트만큼 나오면 ~1.0, 못 미치면 <1, 초과하면 >1(상한 1.3)
       - 표본이 적으면 1.0 쪽으로 수축(shrinkage) — 섣부른 과신/과소 방지
    """
    if ref_ev <= 0:
        raw = 1.0 if live_ev >= 0 else 0.5
    else:
        raw = live_ev / ref_ev
    raw = max(0.0, min(1.3, raw))
    # 베이지안 수축: n이 작을수록 1.0으로 끌어당김 (k=10 기준)
    k = 10
    shrunk = (n * raw + k * 1.0) / (n + k)
    return round(shrunk, 2)


# ── 4) WEIGHTS: 다른 모듈이 쓸 라이브 신뢰계수 내보내기 ───────────────
def export_weights(horizon='4w'):
    data = _load()
    agg = _agg_by_signal(data['trades'], horizon)
    weights = {}
    for flag in SIG_FLAGS:
        v = agg[flag]
        ref = BACKTEST_REF[flag][horizon]
        if v is None:
            weights[flag] = {'mult': 1.0, 'n': 0, 'note': '표본없음→중립'}
        else:
            weights[flag] = {
                'mult': _reliability_mult(v['live_ev'], ref, v['n']),
                'n': v['n'], 'live_ev': v['live_ev'], 'ref_ev': ref,
            }
    WEIGHTS_OUT.write_text(json.dumps(
        {'horizon': horizon, 'updated': datetime.now().strftime('%Y-%m-%d %H:%M'),
         'weights': weights}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"라이브 신뢰계수 저장: {WEIGHTS_OUT}")
    for f, w in weights.items():
        print(f"  {SIG_LABEL[f]:<12} ×{w['mult']:.2f}  (n={w['n']})")


# ── CLI ──────────────────────────────────────────────────────────────
def _main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'report'
    if cmd == 'log':
        log_from_screener()
    elif cmd == 'update':
        update_outcomes()
    elif cmd == 'report':
        report()
    elif cmd == 'weights':
        export_weights()
    elif cmd == 'all':
        log_from_screener(); update_outcomes(); report()
    else:
        print("사용법: python paper_trade.py [log|update|report|weights|all]")


if __name__ == '__main__':
    _main()
