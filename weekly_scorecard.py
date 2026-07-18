"""
weekly_scorecard.py — 주간 성적표 텔레그램 브리핑
─────────────────────────────────────────────────────────────────
"성적표를 만들어놓고 안 보는" 상태 방지 — 매주 일요일 아침, 시스템이
자기 성적을 텔레그램으로 직접 보고한다. 대시보드 열 필요 없음.

내용: ①신호별 실전 vs 백테스트 ②주간 포트폴리오 알파 ③신뢰계수 반영 후
검증 진행상황(W30+ 픽이 나아지는가 — 8월 A/B/C 결정의 근거) ④가드레일
준수율 ⑤파이프라인 건강.

실행: python weekly_scorecard.py           # 생성+발송
      python weekly_scorecard.py --dry     # 발송 없이 출력만
워크플로: .github/workflows/weekly-scorecard.yml (일요일 08시 KST)
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import json
from datetime import datetime, timedelta
from pathlib import Path

# 신뢰계수(실전 할인)가 처음 유의미하게 반영된 날 — 이 날짜 이후 기록된
# 가상매매가 "개선된 시스템"의 픽. 이전 것과 성과를 갈라 보는 기준점.
WEIGHTS_LIVE_DATE = '2026-07-14'


def _sig_section():
    import paper_trade as pt
    data = pt._load()
    trades = data.get('trades', [])
    agg = pt._agg_by_signal(trades, '4w')
    lines = ["<b>🎯 신호별 실전 4주 (vs 백테스트)</b>"]
    for f in pt.SIG_FLAGS:
        v = agg.get(f)
        ref = pt.BACKTEST_REF[f]['4w']
        if v is None:
            continue
        gap = v['live_ev'] - ref
        mark = '✅' if gap >= 0 else ('⚠️' if gap > -1.5 else '❌')
        mult = pt._reliability_mult(v['live_ev'], ref, v['n'])
        lines.append(f"{mark} {pt.SIG_LABEL[f]}: {v['live_ev']:+.1f}% "
                     f"(백테 {ref:+.1f} · n={v['n']} · 계수 {mult:.2f})")
    return lines, trades


def _validation_section(trades):
    """신뢰계수 반영(07-14) 이후 픽의 검증 진행상황 — 8월 A/B/C 결정 근거."""
    post = [t for t in trades if t.get('log_date', '') >= WEIGHTS_LIVE_DATE]
    post_4w = [t for t in post if '4w' in t.get('realized', {})]
    lines = [f"<b>🔬 개선 검증 (신뢰계수 반영 후 픽)</b>",
             f"기록 {len(post)}건 · 4주 만기 {len(post_4w)}건"]
    if post_4w:
        rets = [t['realized']['4w']['ret'] for t in post_4w]
        avg = sum(rets) / len(rets)
        wr = sum(1 for r in rets if r > 0) / len(rets) * 100
        lines.append(f"실현: 평균 {avg:+.2f}% · 승률 {wr:.0f}% "
                     f"(반영 전 전체와 비교해서 판단)")
    elif post:
        first = min(t['log_date'] for t in post)
        mature = datetime.strptime(first, '%Y-%m-%d') + timedelta(days=28)
        lines.append(f"첫 4주 만기 {mature.strftime('%m/%d')} — 그때부터 판독 가능")
    return lines


def _portfolio_section():
    try:
        import weekly_portfolio as wp
        res = wp.analyze()
    except Exception as e:
        return [f"<b>📊 주간 포트폴리오</b>", f"분석 실패: {e}"]
    if not res:
        return ["<b>📊 주간 포트폴리오</b>", "히스토리 없음"]
    lines = ["<b>📊 주간 포트폴리오 (진입→현재, vs KOSPI·SPY)</b>"]
    for r in res[-6:]:                      # 최근 3주 × (10선/20선)
        tag = '10선' if r['set'] == 'p10' else '20선'
        a = f" · 알파 {r['alpha']:+.2f}%p" if r.get('alpha') is not None else ""
        lines.append(f"{r['week']} [{tag}] {r['port_return']:+.2f}%{a}")
    return lines


def _guardrail_section():
    try:
        import guardrail
        hist = guardrail.load_history()
    except Exception:
        hist = []
    if not hist:
        return ["<b>🛡️ 가드레일</b>",
                "포트폴리오 미입력 — 대시보드 💼포트폴리오 탭에 보유종목을 넣으면 "
                "매일 규율 준수를 채점합니다 (1억 손실 재발 방지 장치)"]
    stats = guardrail.compliance_stats(hist)
    last = hist[-1]
    return ["<b>🛡️ 가드레일 준수</b>",
            f"최근 {stats['n_days']}일 준수율 {stats['green_pct']:.0f}% · "
            f"연속 준수 {stats['cur_streak_green']}일 · 어제 {last['grade']}"]


def _health_section():
    try:
        import pipeline_health
        stale = pipeline_health.check()
    except Exception as e:
        return [f"<b>⚙️ 파이프라인</b>: 검사 실패 ({e})"]
    if not stale:
        return ["<b>⚙️ 파이프라인</b>: 정상 ✅"]
    return [f"<b>⚙️ 파이프라인</b>: 이상 {len(stale)}건 🚨", *[f"· {s}" for s in stale[:3]]]


def build_message():
    parts = [f"<b>📒 주간 성적표</b>  {datetime.now().strftime('%Y-%m-%d')}"]
    sig_lines, trades = _sig_section()
    for sec in (sig_lines, _validation_section(trades), _portfolio_section(),
                _guardrail_section(), _health_section()):
        parts.append("")
        parts.extend(sec)
    parts.append("")
    parts.append("상세: 대시보드 → 종목 발굴 → 📒 성적표")
    return "\n".join(parts)


def main():
    msg = build_message()
    print(msg.replace('<b>', '').replace('</b>', ''))
    if '--dry' in sys.argv:
        print("\n(--dry: 발송 생략)")
        return
    try:
        import config
        from telegram_notifier import send_message
        if config.TELEGRAM_ENABLED:
            send_message(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, msg)
            print("\n✅ 텔레그램 발송 완료")
        else:
            print("\nⓘ TELEGRAM_ENABLED=False — 발송 생략")
    except Exception as e:
        print(f"\n⚠️ 텔레그램 발송 실패: {e}")


if __name__ == '__main__':
    main()
