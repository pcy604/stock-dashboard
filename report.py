"""주봉/월봉 리포트 생성 — 시총 순 요약 + 종목 상세"""
import pandas as pd
from datetime import datetime

SIG_LABEL_MAP = {
    '52w_high': '52주신고가', 'volume': '거래량폭발',
    'ma5_ride': '5일선라이딩', 'cup_handle': '컵위드핸들',
    'ma_convergence': '이평선수렴', 'rsi_macd': 'RSI/MACD',
}


def _fmt_cap(marcap: int, market: str = 'KR') -> str:
    if not marcap:
        return '      N/A'
    if market == 'US':
        b = marcap / 1_000_000_000
        return f"${b:6.0f}B" if b < 1000 else f"${b/1000:5.1f}T"
    # KR: 원 단위
    if marcap >= 1_000_000_000_000:
        return f"{marcap/1_000_000_000_000:5.1f}조"
    return f"{marcap//100_000_000:5,}억"




def _get_signal_labels(result: dict) -> list:
    return [SIG_LABEL_MAP[k] for k in SIG_LABEL_MAP if result.get(k, {}).get('signal')]


def _high_type(result: dict) -> str:
    if not result.get('52w_high', {}).get('signal'):
        return ''
    dist = result['52w_high'].get('dist_pct', 0)
    return '역사적' if dist and dist > 5 else '52주'


def _calc_period_return(df: pd.DataFrame, mode: str) -> float:
    """mode: 'weekly' or 'monthly'"""
    try:
        days = 5 if mode == 'weekly' else 21
        if len(df) < days + 1:
            return 0.0
        past = df['Close'].iloc[-days - 1]
        curr = df['Close'].iloc[-1]
        return (curr - past) / past * 100
    except:
        return 0.0


def build_summary(hits: list, mode: str, date_str: str) -> str:
    """
    hits: [(market, symbol, name, result, earnings, tf_labels, df, sector, marcap), ...]
    mode: 'weekly' | 'monthly'
    """
    label = '주봉' if mode == 'weekly' else '월봉'
    period = '주간' if mode == 'weekly' else '월간'

    kr_rows, us_rows = [], []
    for item in hits:
        market, sym, name, result, _, _, df, sector, *rest = item
        marcap = rest[0] if rest else 0
        pct = _calc_period_return(df, mode)
        sig_labels = _get_signal_labels(result)
        ht = _high_type(result)
        row = (marcap, pct, sym, name, sig_labels, ht)
        if market == 'KR':
            kr_rows.append(row)
        else:
            us_rows.append(row)

    kr_rows.sort(key=lambda x: -x[0])
    us_rows.sort(key=lambda x: -x[0])

    def _render(rows, market):
        lines = []
        for marcap, pct, sym, name, sig_labels, ht in rows:
            cap_str = _fmt_cap(marcap, market)
            sign = '+' if pct >= 0 else ''
            pct_str = f"[{sign}{pct:.1f}%]".rjust(9)
            ht_str = f"({ht})" if ht else ''
            sig_str = ', '.join(sig_labels[:2])
            lines.append(f"{cap_str}  {pct_str}  {name}{ht_str}  ← {sig_str}")
        return lines

    lines = [
        f"📌 {label} 신호 종목 현황 ({date_str} 기준)",
        f"시총 높은 순 | 총 {len(hits)}개 종목",
    ]

    if kr_rows:
        lines += ['', f"🇰🇷 한국 ({len(kr_rows)}개)", f"{'시총':>9}  [{period}%]  종목명"]
        lines += _render(kr_rows, 'KR')

    if us_rows:
        lines += ['', f"🇺🇸 미국 ({len(us_rows)}개)", f"{'시총':>9}  [{period}%]  종목명"]
        lines += _render(us_rows, 'US')

    return '\n'.join(lines)


def build_detail_kr(hits: list, mode: str) -> str:
    """한국 종목 상세 카드 (fundamentals_kr.py 연동)"""
    from fundamentals_kr import build_stock_card

    parts = []
    for item in hits:
        market, sym, name, result, _, _, df, sector, *rest = item
        marcap = rest[0] if rest else 0
        if market != 'KR':
            continue
        pct = _calc_period_return(df, mode)
        try:
            card = build_stock_card(sym, name, result, pct, marcap)
            parts.append(card)
        except Exception as e:
            parts.append(f"[{sym}] 상세 조회 실패: {e}")

    return '\n\n'.join(parts)


def save_report(text: str, mode: str):
    import os
    os.makedirs('results', exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M')
    fname = f"results/report_{mode}_{ts}.txt"
    with open(fname, 'w', encoding='utf-8') as f:
        f.write(text)
    return fname
