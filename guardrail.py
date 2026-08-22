"""
포트폴리오 원칙 가드레일 — 감정이 아니라 규칙이 포지션을 강제한다.
─────────────────────────────────────────────────────────────────
사용자 원칙(2026-06-23, 1억 손실 후 정립 / 2026-08-16 백테 검증분 반영):
  · 종목당 **매입** 비중 20% 상한 · 균등 4분할(5%씩) — 증명된 만큼만 준다
  · **평가** 비중 40% 초과 → 리밸런싱에서 30%로 트림
  · 청산은 **고점 대비 −20% 트레일링** (전 물량 공통)
  · 보유 종목이 **3주간 52주 신고가 미갱신 → 30% 축소** (1회)
  · 현금은 매크로 신호 따라(10~70%) · 레버리지 ETF 합계 10% 이내

2026-08-16 변경 — 왜 바꿨나
  ① 손절: 기존 '매수가 대비 −8% 고정'은 백테로 검증된 적이 없다. 주도주 전략은
     평균 보유가 20주라 −8% 고정이면 거의 모든 포지션이 즉사한다. 검증된 규칙은
     고점 대비 −20% 트레일링이고(2019-01~2026-08 · A 회복 1.57 · MDD −20.7%),
     peak_price가 있는 포지션은 트레일링으로, 없으면 기존 고정 손절로 판정한다.
  ② 종목 캡: '상위2 20% / 3위~ 12%' 구분을 없애고 매입 20%로 통일. 백테가
     검증한 형태가 그것이고, 실제 억제는 현금(=분할 진입)이 먼저 한다.
     ⚠️ 3위 이하는 12%→20%로 완화되는 셈이니 lower_cap 슬라이더로 조일 수 있다.
  ③ 트림 임계: 30%→20% 였던 것을 **40%→30%** 로. 상한(20%)은 매입 기준이고
     트림(40%)은 평가 기준이라 서로 다른 자다.

"인간의 비이성적 판단을 없애고, 정한 원칙대로." — 이 엔진의 목적.
실제 매매는 사용자가 실행(자동 주문 아님). 엔진은 '무엇을 얼마나' 정확히 지시한다.

준수율 추적(2026-07-14): 이 UI 섹션이 2026-07-02 탭 재편 때 대시보드에서
빠진 채 12일간 방치됐던 것을 발견 — 복원하며 이력 기록도 함께 추가.
매일 portfolio_monitor.py가 append_snapshot()으로 그날의 평가를 남겨,
"규칙을 얼마나 지켰는가"를 신호 성적표처럼 실측 가능하게 한다.
"""
import json
from datetime import datetime
from pathlib import Path

HISTORY_FILE = Path('results/guardrail_history.jsonl')

# 대표적 레버리지/인버스 ETF (미국). 필요시 추가.
LEVERAGED = {
    'TSLL', 'TSLQ', 'TSLS', 'SOXL', 'SOXS', 'TQQQ', 'SQQQ', 'UPRO', 'SPXU', 'SPXL',
    'UDOW', 'SDOW', 'FNGU', 'FNGD', 'BULZ', 'NVDL', 'NVDU', 'NVDX', 'NVDD', 'AMZU',
    'GGLL', 'MSFU', 'METU', 'AAPU', 'AMDL', 'CONL', 'MSTX', 'MSTU', 'BITX', 'ETHU',
    'LABU', 'LABD', 'YINN', 'YANG', 'TNA', 'TZA', 'FAS', 'FAZ', 'DPST', 'WEBL',
}
LEV_KEYWORDS = ['2X', '3X', '1.5X', 'LEVERAGED', 'BULL 2', 'BULL 3', 'DAILY 2', 'DAILY 3',
                '레버리지', '곱버스', '인버스 2']


def is_leveraged(sym, name=''):
    s = str(sym).upper().replace('.KS', '').replace('.KQ', '')
    if s in LEVERAGED:
        return True
    nm = str(name or '').upper()
    return any(k in nm for k in LEV_KEYWORDS)


def evaluate(positions, total_capital=None,
             top_cap=20.0, lower_cap=20.0, trim_threshold=40.0, trim_to=30.0,
             lev_cap=10.0, stop_pct=8.0, trail_pct=20.0,
             quiet_wk=3, cut_frac=30.0, tranche_pct=5.0,
             cash_min=None, cash_max=None):
    """
    positions: [{sym,name,market,value,cost,pnl_pct,cur_price,peak_price,
                 weeks_since_high,qty}, ...]
        value        현재 평가금액          cost   매입원가(없으면 캡 점검은 평가로 대용)
        peak_price   매수 후 주봉 최고가    weeks_since_high  마지막 52주 신고가 이후 주수
    total_capital: 현금 포함 총자본 (있으면 현금% 점검). None이면 보유분만.
    반환: dict(grade, holdings[], violations[], summary{})
    """
    holds = [p for p in positions if p.get('value')]
    invested = sum(p['value'] for p in holds)
    if invested <= 0:
        return {'grade': '—', 'holdings': [], 'violations': [], 'summary': {}}

    # 비중은 항상 '현재 보유가치' 기준 (총자본 아님)
    base = invested
    cost_base = sum(p.get('cost') or p['value'] for p in holds)
    for p in holds:
        p['weight'] = p['value'] / base * 100
        p['cost_weight'] = (p.get('cost') or p['value']) / cost_base * 100
        p['tranche'] = min(4, max(1, round(p['cost_weight'] / tranche_pct))) if tranche_pct else None
        p['lev'] = is_leveraged(p['sym'], p.get('name'))
    holds.sort(key=lambda x: -x['weight'])

    violations = []   # {sev, sym, rule, msg, trim_value, trim_pct}

    # ── 평가 비중 트림 (40% 초과 → 30%로) ──
    for p in holds:
        w = p['weight']
        if w > trim_threshold:
            trim_v = (w - trim_to) / 100 * base
            violations.append({'sev': '🔴', 'sym': p['sym'], 'name': p.get('name', p['sym']),
                'rule': f'평가비중 {trim_threshold:.0f}% 초과',
                'msg': f"{p.get('name', p['sym'])} 평가 {w:.0f}% → {trim_to:.0f}%로 트림",
                'trim_value': trim_v, 'trim_pct': w - trim_to,
                'qty_cut': trim_v / p['cur_price'] if p.get('cur_price') else None})

    # ── 매입 비중 상한 (종목당 20%) ──
    for i, p in enumerate(holds):
        cap = top_cap if i < 2 else lower_cap
        cw = p['cost_weight']
        if cw > cap + 0.5:
            trim_v = (cw - cap) / 100 * cost_base
            violations.append({'sev': '🟠', 'sym': p['sym'], 'name': p.get('name', p['sym']),
                'rule': f'매입비중 {cap:.0f}% 초과',
                'msg': f"{p.get('name', p['sym'])} 매입 {cw:.0f}% — 신규 매수 중단, "
                       f"{cap:.0f}%까지 축소",
                'trim_value': trim_v, 'trim_pct': cw - cap,
                'qty_cut': trim_v / p['cur_price'] if p.get('cur_price') else None})

    # ── 청산: 고점 대비 트레일링 (peak 없으면 기존 고정 손절로 대체) ──
    for p in holds:
        peak, cur = p.get('peak_price'), p.get('cur_price')
        if peak and cur:
            dd = (cur / peak - 1) * 100
            p['drawdown'] = dd
            if dd <= -trail_pct:
                violations.append({'sev': '🔴', 'sym': p['sym'], 'name': p.get('name', p['sym']),
                    'rule': f'트레일링 -{trail_pct:.0f}% 이탈',
                    'msg': f"{p.get('name', p['sym'])} 고점대비 {dd:+.0f}% — 전량 청산",
                    'trim_value': p['value'], 'trim_pct': p['weight'], 'qty_cut': p.get('qty')})
        elif p.get('pnl_pct') is not None and p['pnl_pct'] <= -stop_pct:
            violations.append({'sev': '🔴', 'sym': p['sym'], 'name': p.get('name', p['sym']),
                'rule': f'손절선 -{stop_pct:.0f}% 이탈 (고점 미상)',
                'msg': f"{p.get('name', p['sym'])} {p['pnl_pct']:+.0f}% — 손절선 이탈, 전량 매도 검토",
                'trim_value': p['value'], 'trim_pct': p['weight'], 'qty_cut': p.get('qty')})

    # ── 3주간 52주 신고가 미갱신 → 30% 축소 ──
    # 이미 트레일링에 걸려 전량 청산 대상인 종목은 제외한다. 백테도 청산을 먼저
    # 판정하고 살아남은 종목만 축소하므로, 같은 종목에 두 지시가 겹치면 안 된다.
    _exiting = {v['sym'] for v in violations if '이탈' in v['rule']}
    for p in holds:
        q = p.get('weeks_since_high')
        if p['sym'] in _exiting:
            continue
        if q is not None and q >= quiet_wk:
            cut_v = p['value'] * cut_frac / 100
            violations.append({'sev': '🟠', 'sym': p['sym'], 'name': p.get('name', p['sym']),
                'rule': f'{quiet_wk}주 신고가 미갱신',
                'msg': f"{p.get('name', p['sym'])} {q:.0f}주째 신고가 없음 — "
                       f"{cut_frac:.0f}% 축소(모멘텀 소진)",
                'trim_value': cut_v, 'trim_pct': p['weight'] * cut_frac / 100,
                'qty_cut': cut_v / p['cur_price'] if p.get('cur_price') else None})

    # ── 레버리지 합계 ──
    lev_w = sum(p['weight'] for p in holds if p['lev'])
    lev_names = [p.get('name', p['sym']) for p in holds if p['lev']]
    if lev_w > lev_cap + 0.5:
        trim_v = (lev_w - lev_cap) / 100 * base
        violations.append({'sev': '🔴', 'sym': 'LEV', 'name': '레버리지 합계',
            'rule': f'레버리지 {lev_cap:.0f}% 초과',
            'msg': f"레버리지({', '.join(lev_names)}) 합계 {lev_w:.0f}% → {lev_cap:.0f}%로. 양날의 검.",
            'trim_value': trim_v, 'trim_pct': lev_w - lev_cap, 'qty_cut': None})

    # ── 현금 (총자본 입력 시) ──
    cash_pct = None
    if total_capital and total_capital >= invested > 0:
        cash_pct = (total_capital - invested) / total_capital * 100
        if cash_min is not None and cash_pct < cash_min - 0.5:
            need = (cash_min - cash_pct) / 100 * total_capital
            violations.append({'sev': '🟠', 'sym': 'CASH', 'name': '현금',
                'rule': f'안전 현금 {cash_min:.0f}% 미달',
                'msg': f"현금 {cash_pct:.0f}% (권고 {cash_min:.0f}~{cash_max:.0f}%) — {need:,.0f}원 더 확보",
                'trim_value': need, 'trim_pct': cash_min - cash_pct, 'qty_cut': None})

    # ── 등급 ──
    n_red = sum(1 for v in violations if v['sev'] == '🔴')
    n_org = sum(1 for v in violations if v['sev'] == '🟠')
    if n_red >= 2:
        grade, gmsg = '🔴 위험', '원칙 다수 위반 — 즉시 비중 조절 필요'
    elif n_red == 1:
        grade, gmsg = '🟠 주의', '긴급 위반 1건 — 조치 필요'
    elif n_org > 0:
        grade, gmsg = '🟡 점검', '경미한 초과 — 조정 권장'
    else:
        grade, gmsg = '🟢 양호', '원칙 준수 중 — 잘하고 있어요'

    summary = {
        'invested': invested, 'base': base, 'cash_pct': cash_pct,
        'top1': holds[0]['weight'] if holds else 0,
        'top2': sum(p['weight'] for p in holds[:2]),
        'top3': sum(p['weight'] for p in holds[:3]),
        'lev_pct': lev_w, 'n_pos': len(holds),
        'max_cost_w': max((p['cost_weight'] for p in holds), default=0),
        'n_full': sum(1 for p in holds if p.get('tranche') == 4),
        'n_red': n_red, 'n_org': n_org, 'msg': gmsg,
    }
    return {'grade': grade, 'holdings': holds, 'violations': violations, 'summary': summary}


def append_snapshot(result: dict, path: Path = HISTORY_FILE):
    """그날의 가드레일 평가를 이력에 남긴다. 같은 날 재실행되면 마지막 것으로 덮어씀
       (하루 1행 유지 — 대시보드에서 여러 번 열어봐도 이력이 부풀지 않도록)."""
    if not result.get('summary'):
        return
    today = datetime.now().strftime('%Y-%m-%d')
    row = {
        'date': today, 'grade': result['grade'],
        'n_red': result['summary'].get('n_red', 0), 'n_org': result['summary'].get('n_org', 0),
        'top1': round(result['summary'].get('top1', 0), 1),
        'top2': round(result['summary'].get('top2', 0), 1),
        'lev_pct': round(result['summary'].get('lev_pct', 0), 1),
        'cash_pct': result['summary'].get('cash_pct'),
        'n_pos': result['summary'].get('n_pos', 0),
        'violation_rules': [v['rule'] for v in result.get('violations', [])],
    }
    path.parent.mkdir(exist_ok=True)
    rows = []
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                if r.get('date') != today:
                    rows.append(r)
            except Exception:
                continue
    rows.append(row)
    rows.sort(key=lambda r: r['date'])
    path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n', encoding='utf-8')


def load_history(path: Path = HISTORY_FILE) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def compliance_stats(history: list, window_days: int = 30) -> dict:
    """최근 window_days간 준수율 — 신호 성적표와 같은 형식으로 '규율' 자체를 채점."""
    if not history:
        return {}
    recent = history[-window_days:]
    n = len(recent)
    n_green = sum(1 for r in recent if '🟢' in r.get('grade', ''))
    n_red_days = sum(1 for r in recent if r.get('n_red', 0) > 0)
    return {
        'n_days': n, 'green_pct': round(n_green / n * 100, 0) if n else 0,
        'red_days': n_red_days,
        'cur_streak_green': _cur_green_streak(history),
    }


def _cur_green_streak(history: list) -> int:
    streak = 0
    for r in reversed(history):
        if '🟢' in r.get('grade', ''):
            streak += 1
        else:
            break
    return streak
