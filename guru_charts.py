"""구루 언급 종목 가격차트 — 당일 요약에서 자주 언급된 종목들의 미니 차트 1장 생성.

차트 제목/축은 ASCII(티커)만 사용해 CJK 폰트 깨짐을 회피. 한글 종목명은 텔레그램 캡션(텍스트)에.
"""
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import FinanceDataReader as fdr

TOP_N = 6
LOOKBACK_DAYS = 150
CHART_PATH = 'results/guru_chart_latest.png'


def collect_tickers(items: list) -> list:
    """relevant 영상들에서 ticker별 집계 → 언급 많은 순 정렬."""
    agg = {}
    for it in items:
        a = it.get('analysis', {})
        if not a.get('relevant', True):
            continue
        ch = it.get('channel', '')
        for t in a.get('tickers', []):
            code = (t.get('ticker') or '').strip()
            if not code:
                continue
            key = code.upper()
            d = agg.setdefault(key, {'ticker': key, 'name': t.get('name', ''),
                                     'count': 0, 'channels': set(), 'views': []})
            d['count'] += 1
            d['channels'].add(ch)
            if t.get('view'):
                d['views'].append(t['view'])
            if t.get('name'):
                d['name'] = t['name']
    return sorted(agg.values(), key=lambda x: -x['count'])


def _fetch_close(ticker: str):
    start = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime('%Y-%m-%d')
    try:
        df = fdr.DataReader(ticker, start)
        if df is None or df.empty or 'Close' not in df:
            return None
        s = df['Close'].dropna()
        return s if len(s) > 5 else None
    except Exception:
        return None


def build_chart(items: list, path: str = CHART_PATH):
    """(png_path, series) 또는 (None, []) 반환. series=[(info, close_series), ...]"""
    ranked = collect_tickers(items)
    series = []
    for r in ranked:
        s = _fetch_close(r['ticker'])
        if s is not None:
            series.append((r, s))
        if len(series) >= TOP_N:
            break
    if not series:
        return None, []

    n = len(series)
    cols = 2 if n <= 4 else 3
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 3.2, rows * 2.4))
    axes = axes.flatten() if hasattr(axes, 'flatten') else [axes]

    for ax, (r, s) in zip(axes, series):
        chg = (s.iloc[-1] / s.iloc[0] - 1) * 100
        color = '#d62728' if chg >= 0 else '#1f77b4'   # 국내 관행: 상승=빨강
        ax.plot(s.index, s.values, color=color, lw=1.5)
        ax.fill_between(s.index, s.values, s.min(), alpha=0.08, color=color)
        ax.set_title(f"{r['ticker']}  {chg:+.1f}%", fontsize=10, fontweight='bold')
        ax.tick_params(labelsize=7)
        ax.margins(x=0)
        ax.grid(alpha=0.15)
        ax.xaxis.set_major_locator(plt.MaxNLocator(4))
        for lbl in ax.get_xticklabels():
            lbl.set_fontsize(6)
        for sp in ('top', 'right'):
            ax.spines[sp].set_visible(False)
    for ax in axes[n:]:
        ax.axis('off')

    fig.suptitle(f"Stocks mentioned by gurus  ·  last ~{LOOKBACK_DAYS // 30}mo",
                 fontsize=11, fontweight='bold')
    fig.tight_layout()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=130, bbox_inches='tight')
    plt.close(fig)
    return path, series


def build_caption(series: list) -> str:
    mk = {'긍정': '🟢', '부정': '🔴'}
    lines = ['📊 오늘 구루들이 언급한 핵심 종목 (최근 5개월)']
    for r, s in series:
        view = Counter(r['views']).most_common(1)[0][0] if r['views'] else ''
        emoji = mk.get(view, '⚪')
        chg = (s.iloc[-1] / s.iloc[0] - 1) * 100
        chans = '·'.join(sorted(r['channels']))
        mention = f" ×{r['count']}" if r['count'] > 1 else ''
        lines.append(f"{emoji} {r['name']}({r['ticker']}) {chg:+.1f}%{mention} [{chans}]")
    return '\n'.join(lines)[:1024]
