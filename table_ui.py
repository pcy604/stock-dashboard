"""표 공통 레이어 — 대시보드의 **모든 st.dataframe 이 이 모듈을 거친다** (2026-10-15).

표 50여 개가 각자 색·필터를 가지면 규칙이 표마다 달라진다(실제로 세 가지 색 규칙이
공존했다: 초록 단색 크기 / 빨강=상승·파랑=하락 / 표별 글자색). 그래서 한 곳에서 정한다.

1) 부호 색  : + 초록, − 빨강. |값|이 클수록 진하다.
   · 강도 기준은 열마다 따로 — 그 열 |편차|의 90분위에서 포화 + 0.6승 압축. 이상치 하나(+829%)가
     나머지를 전부 연하게 뭉개는 걸 막는다(2026-10-15 실측: 95분위·선형이면 +61% 가 거의 무색).
   · **부호에 의미가 있는 열만 칠한다.** 시총·가격·PER·점수처럼 '수준'인 열을
     초록으로 칠하면 '클수록 좋다'는 거짓 신호가 된다(PER 은 낮을수록 싸다).
     판정: 이름이 변화·수익·성장·대비 류이거나, 값에 음수가 섞여 있으면 부호 열.
   · 기준점이 0이 아닌 열: RS(시장 대비 배수)=1, 승률=50, 손익비=1.
   · 높을수록 '위험'인 열(의존·집중·변동성)은 칠하지 않는다 — 초록=좋음이 뒤집힌다.
   · 문자열 숫자("+12.3%", "✅ +23%", "$12B")도 숫자로 읽어 칠한다. 날짜는 안 읽는다.
   · 결측은 칠하지 않는다. 없는 값을 있는 척하지 않는다.
2) 필터    : 8행 이상 표 위에 🔎 필터 — 검색 · 열 조건(숫자 범위/값 선택/글자 포함) · 열 숨기기.
   호출부에서 st.dataframe(..., filters=False) 로 끌 수 있다.
"""
from __future__ import annotations

import math
import os
import re
import sys

import pandas as pd
from pandas.io.formats.style import Styler

GREEN = (22, 163, 74)
RED = (220, 38, 38)
A_MIN, A_MAX = 0.07, 0.48          # 0.48 보다 진하면 검정 글자가 배경에 먹힌다
MIN_ROWS_FOR_FILTER = 8

# 크기가 의미 없는 열 — 식별자·순번·날짜
NO_COLOR = {'회차', '주차', '코드', '종목', '종목명', '연도', '달', '연월', '월', '시장', '섹터',
            '그 해 회차', '신호', '표본', '신호 수', '첫 신호', '마지막 신호', '기준일', '날짜'}
# '수준' 열 — 부호가 아니라 크기라서 칠하지 않는다(음수가 있어도: PER<0 은 적자일 뿐)
_LEVEL = re.compile(r'PER|PBR|PSR|PEG|EV/|시총|가격|현재가|진입가|매수가|평단|종가|52주고|52주저|'
                    r'점수|등급|수량|주수|비중|통과율|통과수|개수|표본|건수|거래량|배수|RS ?\(L\)|퍼센타일|'
                    r'^N$|^n$|평가금|원금|매입|중요도|경과|주기|의존|집중|변동성|베타')
# ↑ '의존·집중·변동성' 은 높을수록 '위험'이라 초록(=좋음)으로 칠하면 뜻이 뒤집힌다 → 칠하지 않는다
# 부호 열 힌트 — 이름만으로 '변화량'임을 알 수 있는 것
_SIGNED = ('%', '률', '대비', 'YoY', 'QoQ', '가속', 'Δ', '이후', '상승', '하락', '변화', '성장',
           '수익', '손익', '증감', '전일', '계절성', '낙폭', '최고', '최저', '초과', '알파', 'MDD',
           '리비전', '서프라이즈', '괴리', 'ret', 'chg', '1주', '4주', '12주', '13주', '26주', '52주',
           # 이익·마진·수익성 — 부호 자체가 흑자/적자를 뜻한다(표마다 음수 유무로 색이 갈리지 않게)
           'GPM', 'OPM', 'NPM', 'ROE', 'ROA', '마진', '순익', '영업익', '이익', '평균', '중앙값')
_WORD_SIGN = {'흑자전환': 1, '흑전': 1, '흑자지속': 1, '개선': 1, '상향': 1, '✅': 1,
              '적자전환': -1, '적전': -1, '적자지속': -1, '악화': -1, '하향': -1, '❌': -1}
_WORD_MAXLEN = 10                       # 이보다 긴 글은 문장 — '개선'이 들어 있어도 판정 아님
_NUM_RE = re.compile(r'^\s*(?:[✅❌🔺🔻▲▼]\s*)?([+\-−]?)\s*\$?\s*([+\-−]?)(\d[\d,]*(?:\.\d+)?)\s*'
                     r'(%p|%|p|x|배|억|조|원|\$?B|M|K|T|bp)?\s*$')
_UNIT = {'K': 1e3, 'M': 1e6, 'B': 1e9, '$B': 1e9, 'T': 1e12, '억': 1e8, '조': 1e12}


# ── 숫자 해석 ──────────────────────────────────────────────────────
def _parse(v):
    if v is None:
        return math.nan
    if isinstance(v, bool):
        return math.nan
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s or s in ('-', '—', '?', '??', '·', 'nan', 'None'):
        return math.nan
    m = _NUM_RE.match(s)
    if not m:
        return math.nan
    x = float(m.group(3).replace(',', '')) * _UNIT.get(m.group(4) or '', 1)
    # '$-19M' 처럼 부호가 통화 기호 뒤에 와도 읽는다. '$144M'·'$1.1B' 가 한 열에 섞여도 크기 순이 맞게 단위를 곱한다
    return -x if (m.group(1) + m.group(2)) in ('-', '−') else x


def numeric_view(col: pd.Series) -> pd.Series:
    """열을 숫자로 읽은 값(실패는 NaN). 숫자 dtype 이면 그대로."""
    if pd.api.types.is_bool_dtype(col):
        return pd.Series(math.nan, index=col.index)
    if pd.api.types.is_numeric_dtype(col):
        return col.astype(float)
    return col.map(_parse).astype(float)


def _word_sign(v):
    s = str(v).strip()
    if not s or len(s) > _WORD_MAXLEN:
        return 0
    for w, sg in _WORD_SIGN.items():
        if w in s:
            return sg
    return 0


def _center(name: str, vals: pd.Series) -> float:
    if '승률' in name:
        return 50.0
    if '손익비' in name or 'Profit Factor' in name:   # 1 = 본전. 0 기준이면 전부 초록이 된다
        return 1.0
    if name.upper().startswith('RS') and vals.notna().any():
        med = vals.median()
        if 0.2 < med < 5:                      # 배수(1=시장과 같음). 퍼센타일(0~100)이면 해당 없음
            return 1.0
    return 0.0


def signed_column(name: str, vals: pd.Series) -> bool:
    n = str(name)
    if n in NO_COLOR or n.startswith('_'):
        return False
    if _LEVEL.search(n):
        return False
    if vals.notna().sum() == 0:
        return False
    if (vals < 0).any():
        return True
    return any(h in n for h in _SIGNED) or n.upper().startswith('RS')


def _bg(d: float, scale: float) -> str:
    if d != d or d == 0 or scale <= 0:
        return ''
    t = min(1.0, abs(d) / scale) ** 0.6     # 제곱근 근처 압축 — 두꺼운 꼬리(수익률·성장률)에서 보통 값이 묻히지 않게
    a = A_MIN + t * (A_MAX - A_MIN)
    r, g, b = GREEN if d > 0 else RED
    return f'background-color: rgba({r},{g},{b},{a:.3f})'


def color_plan(df: pd.DataFrame) -> dict:
    """열 → (center, scale). 칠할 열만 담는다. 테스트·설명용으로 따로 뺐다."""
    plan = {}
    for c in df.columns:
        if isinstance(df[c], pd.DataFrame):     # 중복 열 이름
            continue
        v = numeric_view(df[c])
        if v.notna().sum() == 0:
            # 글자 판정 열(흑자전환/악화/✅ …) — 값의 절반 이상이 짧은 판정어일 때만
            nn = df[c].dropna().astype(str)
            nn = nn[~nn.isin(['-', '—', '?', ''])]
            if (len(nn) and str(c) not in NO_COLOR
                    and nn.map(_word_sign).ne(0).mean() >= 0.5):
                plan[c] = (0.0, 1.0)
            continue
        if not signed_column(c, v):
            continue
        ctr = _center(str(c), v)
        d = (v - ctr).abs().dropna()
        d = d[d > 0]
        if d.empty:
            continue
        scale = float(d.quantile(.90)) if len(d) >= 5 else float(d.max())
        plan[c] = (ctr, scale or float(d.max()))
    return plan


def apply_colors(sty: Styler, df: pd.DataFrame) -> Styler:
    for c, (ctr, scale) in color_plan(df).items():
        def _f(x, ctr=ctr, scale=scale):
            v = _parse(x) if not isinstance(x, (int, float)) or isinstance(x, bool) else float(x)
            if v != v:
                ws = _word_sign(x)
                return _bg(ws * scale, scale) if ws else ''
            return _bg(v - ctr, scale)
        sty = sty.map(_f, subset=[c])
    return sty


# ── 필터 ──────────────────────────────────────────────────────────
def _filter_ui(st, df: pd.DataFrame, key: str):
    """(필터된 df, 숨길 열 목록) 을 돌려준다. 위젯은 popover 안에 둔다."""
    ss = st.session_state
    cols = [c for c in df.columns if not str(c).startswith('_')]

    def _reset():
        for k in list(ss.keys()):
            if isinstance(k, str) and k.startswith(key + '|'):
                del ss[k]

    n_act = len(ss.get(f'{key}|cols') or []) + bool(ss.get(f'{key}|q')) + bool(ss.get(f'{key}|hide'))
    label = '🔎 필터' + (f' · {n_act}개 적용' if n_act else '')
    mask = pd.Series(True, index=df.index)
    with st.popover(label):
        q = st.text_input('검색 — 글자 열 전체에서 (쉼표로 여러 개 = 또는)', key=f'{key}|q',
                          placeholder='예: 삼성, NVDA, 반도체')
        sel = st.multiselect('조건을 걸 열', cols, key=f'{key}|cols')
        for c in sel:
            raw = df[c]
            num = numeric_view(raw)
            if num.notna().sum() >= max(2, 0.5 * raw.notna().sum()) and num.nunique() > 1:
                lo, hi = float(num.min()), float(num.max())
                is_int = bool((num.dropna() % 1 == 0).all())
                step = 1.0 if is_int else max((hi - lo) / 200, 1e-6)
                r = st.slider(f'{c} 범위', lo, hi, (lo, hi), step=step, key=f'{key}|n|{c}')
                if (r[0], r[1]) != (lo, hi):
                    mask &= num.between(r[0], r[1])          # 범위를 좁히면 결측은 빠진다
                    st.caption(f'↳ 범위를 좁히면 {c} 값이 없는 행(-)은 제외됩니다.')
            else:
                vals = raw.astype(str)
                uniq = sorted(vals.unique().tolist())
                if len(uniq) <= 40:
                    pick = st.multiselect(f'{c} — 포함할 값 (비우면 전체)', uniq, key=f'{key}|v|{c}')
                    if pick:
                        mask &= vals.isin(pick)
                else:
                    t = st.text_input(f'{c} — 포함 글자', key=f'{key}|t|{c}')
                    if t:
                        mask &= vals.str.contains(re.escape(t), case=False, na=False)
        hide = st.multiselect('숨길 열', cols, key=f'{key}|hide')
        st.button('↺ 초기화', key=f'{key}|reset', on_click=_reset)
    if q:
        terms = [t.strip() for t in q.split(',') if t.strip()]
        txt = df[cols].astype(str).agg(' '.join, axis=1)
        mask &= txt.apply(lambda s: any(t.lower() in s.lower() for t in terms))
    out = df[mask.values]
    if len(out) != len(df):
        st.caption(f'🔎 필터 적용 — {len(out):,} / {len(df):,}행')
    return out, hide, mask.values


def _restyle(sty: Styler, keep) -> Styler:
    """Styler 의 행을 걸러낸 새 Styler. 포맷 함수는 위치(행,열) 키라서 위치를 다시 매핑한다."""
    import numpy as np
    pos = np.flatnonzero(keep)
    new = type(sty)(sty.data.iloc[pos])
    remap = {int(old): i for i, old in enumerate(pos)}
    new._display_funcs.update({(remap[r], c): f for (r, c), f in sty._display_funcs.items()
                               if r in remap})
    for a in ('_todo', 'table_styles', 'css', 'hide_index_', 'hide_columns_',
              'hide_index_names', 'hide_column_names', 'hidden_columns', 'table_attributes'):
        if hasattr(sty, a):
            v = getattr(sty, a)
            setattr(new, a, list(v) if isinstance(v, list) else (dict(v) if isinstance(v, dict) else v))
    return new


# ── 설치 ──────────────────────────────────────────────────────────
def begin_run(st):
    """스크립트 매 실행 맨 위에서 호출 — 같은 줄의 표가 여러 번 그려질 때 키 순번을 0부터."""
    st.session_state['_tbl_seen'] = {}


def install(st):
    """st.dataframe 을 감싼다. 한 번만 감싸고(재실행·다중 세션에서 겹치지 않게),
    세션별 상태는 session_state 에만 둔다(모듈 전역 금지 — 세션 간 공유된다)."""
    if getattr(st, '_tbl_patched', False):
        return
    orig = st.dataframe

    def dataframe(data=None, *a, filters=None, color=True, **kw):
        try:
            sty = data if isinstance(data, Styler) else None
            df = sty.data if sty is not None else data
            if not isinstance(df, pd.DataFrame):
                return orig(data, *a, **kw)

            # 표시 소수 1자리(2026-08-17 규칙) — 호출부가 column_config 를 안 줬을 때만
            if 'column_config' not in kw:
                cfg = {c: st.column_config.NumberColumn(format='%.1f')
                       for c in df.columns if pd.api.types.is_float_dtype(df[c])}
                if cfg:
                    kw['column_config'] = cfg

            use_f = filters if filters is not None else len(df) >= MIN_ROWS_FOR_FILTER
            if use_f and not kw.get('on_select'):
                fr = sys._getframe(1)
                base = f'tf|{os.path.basename(fr.f_code.co_filename)}:{fr.f_lineno}'
                seen = st.session_state.setdefault('_tbl_seen', {})
                seen[base] = seen.get(base, -1) + 1
                key = f'{base}#{seen[base]}'
                _, hide, keep = _filter_ui(st, df, key)
                if not keep.all():
                    if sty is not None:
                        sty = _restyle(sty, keep)
                    df = df[keep]
                if hide:
                    order = kw.get('column_order') or list(df.columns)
                    kw['column_order'] = [c for c in order if c not in hide]
                if 'height' in kw and isinstance(kw['height'], int) and len(df) < len(data.data if isinstance(data, Styler) else data):
                    kw['height'] = min(kw['height'], 35 + 26 * max(len(df), 1) + 4)

            if color:
                if sty is None:
                    sty = df.style
                sty = apply_colors(sty, df)
            return orig(sty if sty is not None else df, *a, **kw)
        except Exception as e:                      # 표시 보정 실패가 화면을 죽이면 안 된다
            if type(e).__module__.startswith('streamlit'):
                raise
            # 조용히 넘기지 않는다 — 원본 표는 그리되 로그를 남긴다
            print(f'[table_ui] 보정 실패 → 원본 표로 표시: {type(e).__name__}: {e}', file=sys.stderr)
            st.session_state.setdefault('_tbl_errors', []).append(f'{type(e).__name__}: {e}')
            return orig(data, *a, **kw)

    st.dataframe = dataframe
    st._tbl_patched = True
