"""
portfolio_monitor.py  —  포트폴리오 손절/목표가 모니터링 + 텔레그램 알림
실행: python portfolio_monitor.py
run_update.bat에 포함해서 매일 자동 실행
"""
import json, sys, socket, time
import pandas as pd
import FinanceDataReader as fdr
from pathlib import Path
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
socket.setdefaulttimeout(15)

PORTFOLIO_FILE = Path('data/portfolio.json')
RESULT_FILE    = Path('results/portfolio_latest.json')
PORTFOLIO_FILE.parent.mkdir(exist_ok=True)
RESULT_FILE.parent.mkdir(exist_ok=True)

DATE_STR = datetime.now().strftime('%Y-%m-%d %H:%M')


# ── config에서 텔레그램 정보 로드 ──────────────────────────────────────
try:
    import config
    TG_TOKEN   = config.TELEGRAM_TOKEN
    TG_CHAT_ID = config.TELEGRAM_CHAT_ID
    TG_ENABLED = config.TELEGRAM_ENABLED
except:
    TG_ENABLED = False


def tg_send(text: str):
    if not TG_ENABLED:
        print(text); return
    import requests
    try:
        requests.post(
            f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
            json={'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'HTML'},
            timeout=10,
        )
    except Exception as e:
        print(f'[텔레그램 오류] {e}')


def load_portfolio() -> list:
    if not PORTFOLIO_FILE.exists():
        return []
    try:
        return json.loads(PORTFOLIO_FILE.read_text(encoding='utf-8')).get('positions', [])
    except:
        return []


def save_portfolio(positions: list):
    data = {'updated': DATE_STR, 'positions': positions}
    PORTFOLIO_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def get_current_price(sym: str, market: str) -> float | None:
    try:
        code = sym.replace('.KS', '').replace('.KQ', '')
        fdr_sym = code if market == 'KR' else sym
        start = (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')
        df = fdr.DataReader(fdr_sym, start)
        if df.empty: return None
        return float(df['Close'].iloc[-1])
    except:
        return None


def main():
    positions = load_portfolio()
    if not positions:
        print("포트폴리오가 비어있습니다. 대시보드에서 종목을 추가하세요.")
        return

    print(f"[{DATE_STR}] 포트폴리오 모니터링 시작 — {len(positions)}개 종목")

    alerts = []
    results = []

    for pos in positions:
        sym    = pos['sym']
        market = pos.get('market', 'US')
        name   = pos.get('name', sym)
        qty    = float(pos.get('qty', 0))
        buy_px = float(pos.get('buy_price', 0))
        stop   = float(pos.get('stop_loss_pct', 7.0))
        target = float(pos.get('target_pct', 20.0))

        cur_px = get_current_price(sym, market)
        if cur_px is None:
            print(f"  [{sym}] 가격 조회 실패")
            results.append({**pos, 'cur_price': None, 'pnl_pct': None, 'pnl_amt': None})
            continue

        pnl_pct = (cur_px / buy_px - 1) * 100 if buy_px > 0 else 0
        pnl_amt = (cur_px - buy_px) * qty

        ccy = '₩' if market == 'KR' else '$'
        print(f"  [{market}] {name} ({sym}): {ccy}{cur_px:,.1f}  {pnl_pct:+.1f}%  P&L {ccy}{pnl_amt:,.0f}")

        # ── 손절 감시 (-stop%) ────────────────────────────────────────
        if pnl_pct <= -stop:
            alerts.append(
                f"🔴 <b>손절 경고</b>  [{market}] {name} ({sym})\n"
                f"  매수가: {ccy}{buy_px:,.2f}  현재가: {ccy}{cur_px:,.2f}\n"
                f"  수익률: <b>{pnl_pct:+.1f}%</b>  손절기준: -{stop}%\n"
                f"  즉각 매도 검토 필요 ⚠️"
            )

        # ── 목표가 도달 (+target%) ────────────────────────────────────
        elif pnl_pct >= target:
            alerts.append(
                f"🟢 <b>목표가 도달</b>  [{market}] {name} ({sym})\n"
                f"  매수가: {ccy}{buy_px:,.2f}  현재가: {ccy}{cur_px:,.2f}\n"
                f"  수익률: <b>{pnl_pct:+.1f}%</b>  목표: +{target}%\n"
                f"  분할 익절 또는 손절선 올리기 검토"
            )

        results.append({
            **pos,
            'cur_price': round(cur_px, 4),
            'pnl_pct':   round(pnl_pct, 2),
            'pnl_amt':   round(pnl_amt, 2),
            'stop_price': round(buy_px * (1 - stop / 100), 4),
            'target_price': round(buy_px * (1 + target / 100), 4),
            'updated':   DATE_STR,
        })
        time.sleep(0.1)

    # ── 포트폴리오 요약 알림 ──────────────────────────────────────────
    valid = [r for r in results if r.get('pnl_pct') is not None]
    if valid:
        total_invested = sum(float(r.get('buy_price',0)) * float(r.get('qty',0)) for r in valid)
        total_now      = sum(float(r.get('cur_price',0)) * float(r.get('qty',0)) for r in valid)
        total_pnl_pct  = (total_now / total_invested - 1) * 100 if total_invested > 0 else 0
        total_pnl_amt  = total_now - total_invested

        lines = [f"<b>💼 포트폴리오 일일 리포트</b>  {DATE_STR}\n"]
        lines.append(f"총 평가손익: <b>{total_pnl_pct:+.1f}%</b>  ({total_pnl_amt:+,.0f})")
        lines.append("")
        for r in sorted(valid, key=lambda x: x.get('pnl_pct', 0), reverse=True):
            ccy = '₩' if r.get('market') == 'KR' else '$'
            emoji = '🟢' if r['pnl_pct'] >= 0 else '🔴'
            lines.append(
                f"{emoji} {r.get('name', r['sym'])}  "
                f"{r['pnl_pct']:+.1f}%  "
                f"({ccy}{r['pnl_amt']:+,.0f})"
            )

        tg_send('\n'.join(lines))

    # ── 개별 경고 발송 ────────────────────────────────────────────────
    for alert in alerts:
        tg_send(alert)

    # ── 결과 저장 ─────────────────────────────────────────────────────
    out = {'date': DATE_STR, 'total': len(results), 'positions': results}
    RESULT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    save_portfolio(positions)  # 원본 포지션 유지

    print(f"\n✅ 완료 → {RESULT_FILE}")
    if alerts:
        print(f"⚠️  경고 {len(alerts)}건 텔레그램 발송 완료")


if __name__ == '__main__':
    main()
