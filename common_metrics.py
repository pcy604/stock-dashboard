"""종목 발굴 표 표준 — 공통 열 사전 + 공통 지표 (2026-10-26).

문제(2026-10-26 전수조사): 표 28개가 각자 열을 골라 같은 뜻이 다른 이름·다른 정의로 나왔다.
  · RS 가 세 가지 뜻(가중 백분위 · 12개월 백분위 · 시장 대비 배수) — 교집합은 백테스트와 다른 공식
  · 매출%/매출YoY(%)/매출성장%, 고점대비%/고점대비(%) … 같은 종목이 탭마다 다른 숫자
  · PER 이 어떤 탭엔 있고 어떤 탭엔 없음
해법: **종목 목록 표는 전부 같은 뼈대**를 쓴다.

  [고정 좌측] No. · 종목 · 코드 · (시장) · 시총 · 업종
  [탭 고유]   그 탭이 왜 이 종목을 골랐는지 — 최대 5열
  [공통 우측] RS · 1개월(%) · 52주고점대비(%) · 매출YoY(%) · 영업익YoY(%) · PER(배)

공통 열은 여기 한 곳에서만 계산한다. 탭은 `frame(rows, specific=[...])` 로 감싸기만 한다.

RS 정의 — 백테스트(research/rs_accel_bt.rs_rank)와 같은 IBD 식 가중:
  0.4 × 3개월 + 0.2 × 6개월 + 0.2 × 9개월 + 0.2 × 12개월 수익률 → **그 시장 안** 백분위(0~99).
  144조합 강건성(robust_rs.json) 중앙 CAGR: 가중 17.9% · 12-1개월 16.8% · 13주 12.8% → 가중을 표준으로.
"""
from __future__ import annotations

import json
import os

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))

# ── 열 사전: 이름(단위) · 정의 · 출처 — 화면의 help 와 테스트가 이걸 쓴다 ──────────────
COLS = {
    '종목': ('', '종목명', 'KRX 상장목록 · SEC'),
    '코드': ('', '한국 6자리 · 미국 티커. 누르면 🔍 종목 분석', ''),
    '시장': ('', 'KR / US (시장 선택이 전체일 때만)', ''),
    '시총': ('억원 · $B', '한국 = 억원, 미국 = $B. 섞인 표는 머리행에 두 단위', 'returns.json'),
    '업종': ('', '한국 표준산업분류 · 미국 SEC SIC', 'sectors.json · us_domicile.csv'),
    'RS': ('백분위', '0.4×3개월+0.2×6개월+0.2×9개월+0.2×12개월 수익률의 그 시장 안 백분위(99=최상위) — 백테스트와 같은 식',
           'returns.json'),
    '1개월(%)': ('%', '최근 21거래일 주가 수익률', 'returns.json'),
    '52주고점대비(%)': ('%', '현재가 ÷ 52주 최고가 − 1 (0 = 신고가)', 'perf_latest.json'),
    '매출YoY(%)': ('%', '최근 분기 매출 ÷ 전년 같은 분기 − 1 (전년이 0 이하면 -)', 'fund_snapshot.json'),
    '영업익YoY(%)': ('%', '최근 분기 영업이익 ÷ 전년 같은 분기 − 1 (전년이 적자면 - · 흑자전환은 흑자전환 탭)',
                    'fund_snapshot.json'),
    'PER(배)': ('배', '지금 시총 ÷ 최근 4분기 순이익 합(TTM). 적자면 -', 'fund_snapshot.json · returns.json'),
}
LEFT = ['종목', '코드', '시장', '시총', '업종']
COMMON = ['RS', '1개월(%)', '52주고점대비(%)', '매출YoY(%)', '영업익YoY(%)', 'PER(배)']
MAX_SPECIFIC = 5
SECTOR_MAX = 14            # 한국 업종명은 40자가 넘는 것도 있다 — 칸을 먹지 않게 자른다


def _j(path):
    try:
        with open(os.path.join(ROOT, path), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def rs_scores(ret: pd.DataFrame) -> tuple[pd.Series, bool]:
    """sym 인덱스 · ret_3m/6m/9m/12m 열 → (RS 백분위, 정식 여부).
    9개월 수익률이 아직 없는 옛 returns.json 이면 3·6·12개월로 근사하고 False 를 돌려준다(화면에 표시)."""
    need = ['ret_3m', 'ret_6m', 'ret_12m']
    ok = ret[need].notna().all(axis=1)
    exact = 'ret_9m' in ret and ret['ret_9m'].notna().mean() > 0.5
    if exact:
        ok &= ret['ret_9m'].notna()
        s = 0.4 * ret.ret_3m + 0.2 * ret.ret_6m + 0.2 * ret.ret_9m + 0.2 * ret.ret_12m
    else:
        s = 0.4 * ret.ret_3m + 0.3 * ret.ret_6m + 0.3 * ret.ret_12m
    s = s.where(ok)
    rs = (s.groupby(ret.market).rank(pct=True) * 99).round(0)
    return rs, exact


def _sector_map():
    out = {}
    out.update(_j('data/sectors.json'))
    try:
        d = pd.read_csv(os.path.join(ROOT, 'data', 'us_domicile.csv'), usecols=['sym', 'sic_desc'])
        out.update({str(a): b for a, b in zip(d.sym, d.sic_desc) if isinstance(b, str)})
    except Exception:
        pass
    return out


def build(usdkrw: float) -> tuple[pd.DataFrame, dict]:
    """공통 지표 표(index=코드) 와 메타(기준일·RS 정식 여부)."""
    rj = _j('results/returns.json')
    ret = pd.DataFrame(rj.get('stocks') or [])
    if ret.empty:
        return pd.DataFrame(), {}
    ret['sym'] = ret.sym.astype(str)
    ret = ret.drop_duplicates('sym').set_index('sym')
    rs, exact = rs_scores(ret)
    out = pd.DataFrame(index=ret.index)
    out['종목'] = ret['name']
    out['시장'] = ret['market']
    mc = pd.to_numeric(ret['marcap'], errors='coerce')
    out['_mc_usd'] = mc.where(ret.market == 'US', mc / usdkrw)
    out['_mc_local'] = mc
    out['RS'] = rs
    out['1개월(%)'] = ret.get('ret_1m')

    pj = _j('results/perf_latest.json')
    perf = {str(r['sym']): r for r in (pj.get('stocks') or [])}
    out['52주고점대비(%)'] = [(perf.get(s) or {}).get('dist52') for s in out.index]

    fj = _j('results/fund_snapshot.json')
    fs = fj.get('stocks') or {}
    out['매출YoY(%)'] = [(fs.get(s) or {}).get('rev_yoy') for s in out.index]
    out['영업익YoY(%)'] = [(fs.get(s) or {}).get('op_yoy') for s in out.index]
    ni = pd.Series([(fs.get(s) or {}).get('ttm_ni') for s in out.index], index=out.index, dtype=float)
    out['PER(배)'] = (mc / ni).where(ni > 0).round(1)

    sec = _sector_map()
    out['업종'] = [(sec.get(s) or None) for s in out.index]
    out['업종'] = out['업종'].map(lambda x: x if not isinstance(x, str) or len(x) <= SECTOR_MAX
                                else x[:SECTOR_MAX - 1] + '…')
    meta = dict(ret_date=rj.get('date'), perf_date=pj.get('date'), fund_date=fj.get('date'),
                rs_exact=exact, n_fund_kr=fj.get('n_kr'), n_fund_us=fj.get('n_us'))
    return out, meta


def frame(rows: pd.DataFrame, base: pd.DataFrame, specific: list[str], market: str = '전체',
          sort_by: str | None = None, ascending: bool = False) -> pd.DataFrame:
    """탭의 표(최소 '코드' 열 + 탭 고유 열)를 표준 뼈대로 감싼다.

    · 공통 열은 base(build 결과)에서만 가져온다 — 탭이 같은 이름의 열을 줘도 공통 값으로 덮지 않고 버린다.
    · 시총: 한국만 → 시총(억원), 미국만 → 시총($B), 섞이면 → 시총($B) 로 넘겨 table_ui 가 행마다 단위를 바꾸고
      머리행을 '시총(억원·$B)' 로 단다. 기본 순서는 달러 환산 시총(정렬 키가 필요할 때).
    """
    if rows is None or rows.empty:
        return pd.DataFrame()
    spec = [c for c in specific if c in rows.columns][:MAX_SPECIFIC]
    r = rows[['코드'] + spec].copy()
    r['코드'] = r['코드'].astype(str)
    b = base.reindex(r['코드'])
    b.index = r.index
    df = pd.DataFrame(index=r.index)
    df['종목'] = rows['종목'] if '종목' in rows.columns else b['종목']
    df['종목'] = df['종목'].fillna(b['종목'])
    df['코드'] = r['코드']
    mkt = b['시장'].fillna(r['코드'].map(lambda c: 'KR' if c[:5].isdigit() and len(c) == 6 else 'US'))
    df['시장'] = mkt
    usd_b = (b['_mc_usd'] / 1e9)
    if (mkt == 'KR').all():
        df['시총(억원)'] = (b['_mc_local'] / 1e8).round(0)
    elif (mkt == 'US').all():
        df['시총($B)'] = usd_b.round(1)
    else:
        df['시총($B)'] = usd_b               # table_ui.normalize 가 한국 행만 억원으로 바꾼다
    df['업종'] = b['업종']
    for c in spec:
        df[c] = r[c]
    for c in COMMON:
        df[c] = b[c]
    df['_sort_usd'] = b['_mc_usd']
    if market != '전체' or df['시장'].nunique() <= 1:
        df = df.drop(columns=['시장'])
    if sort_by:
        key = '_sort_usd' if sort_by == '시총' else sort_by
        if key in df.columns:
            df = df.sort_values(key, ascending=ascending, na_position='last')
    return df.drop(columns=['_sort_usd']).reset_index(drop=True)


def help_config(st, df: pd.DataFrame) -> dict:
    """공통 열의 정의를 머리글 도움말로 — 표마다 설명 캡션을 따로 달지 않게."""
    cfg = {}
    for c in df.columns:
        if c in COLS and c not in ('종목', '코드', '시장'):
            unit, desc, _src = COLS[c]
            if c == 'RS':
                cfg['RS'] = st.column_config.NumberColumn('RS', format='%d', help=desc)
            elif c in ('업종',):
                cfg[c] = st.column_config.TextColumn(c, help=desc)
            else:
                fmt = '%+.1f' if '(%)' in c else '%,.1f'
                cfg[c] = st.column_config.NumberColumn(c, format=fmt, help=desc)
    return cfg


def source_label(meta: dict) -> str:
    return (f"공통 열: 수익률·RS returns.json({meta.get('ret_date', '-')}) · 52주고점 perf_latest.json({meta.get('perf_date', '-')}) "
            f"· 매출·영업익·PER fund_snapshot.json({meta.get('fund_date', '-')}, DART·네이버·SEC EDGAR)")
