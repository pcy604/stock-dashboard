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
3) 표 형식 (2026-10-19 사용자 규칙 — 모든 표 공통)
   ① 가장 좌측 열은 행번호 'No.' (필터 후 1부터 다시 센다)
   ② 좌측 열 순서: No. → 종목 → 코드 → 시총 (있는 것만). 종목명/티커/sym 등은 이름을 통일
   ③ 칸 안의 단위는 지우고 머리행(1행)에 적는다: '+12.3%' → 12.3, 열 이름 '수익률(%)'
      · 억/조 는 억으로, K/M/B/T 는 B 로 환산해 한 단위로 맞춘다
      · ✅/❌ 같은 판정 기호가 붙은 열은 바꾸지 않는다 — 숫자만 남기면 판정이 사라진다
   ④ 모든 표 바로 밑에 '출처 · 마지막 갱신' — src()/st.dataframe(src=, asof=) 로 준다.
      안 주면 '출처 미지정'으로 그대로 드러낸다(빈칸을 숨기지 않는다)
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
API_VERSION = 3          # install() 동작·인자를 바꾸면 올린다(옛 래퍼 교체 신호)

# 크기가 의미 없는 열 — 식별자·순번·날짜
NO_COLOR = {'No.', '회차', '주차', '코드', '종목', '종목명', '연도', '달', '연월', '월', '시장', '섹터',
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


# ── 표 형식 (2026-10-19) ───────────────────────────────────────────
_ALIAS = {'종목명': '종목', '기업': '종목', '기업명': '종목', 'name': '종목',
          '티커': '코드', 'Ticker': '코드', 'ticker': '코드', 'sym': '코드',
          'Symbol': '코드', 'symbol': '코드', '심볼': '코드', '종목코드': '코드'}
_ROWNO = {'#', 'No', 'No.', 'no', '순번', '번호'}
_CELL_RE = re.compile(r'^\s*([+\-−]?)\s*([$₩]?)\s*([+\-−]?)(\d[\d,]*(?:\.\d+)?)\s*'
                      r'(%p|%|bp|p|x|배|억|조|원|B|M|K|T)?\s*$')
_SCALE = {'억': ('억', 1), '조': ('억', 1e4),
          'K': ('B', 1e-6), 'M': ('B', 1e-3), 'B': ('B', 1), 'T': ('B', 1e3)}
_MISSING = {'', '-', '—', '·', 'None', 'nan', 'NaN', 'N/A', 'n/a'}


_ID_COLS = {'코드', 'sym', '티커', 'Ticker', 'ticker', 'Symbol', 'symbol', '종목코드', '심볼',
            '주차', '연도', '연월', '월', '달', '기준일', '날짜', '일자', '진입일', '회복일', '고점일', '저점일',
            '발표일', '기준분기', '분기', 'period', '기간'}


def _unit_convert(col: pd.Series):
    """칸 단위가 한 가지로 모이는 글자 열이면 (숫자 열, 단위) — 아니면 None."""
    if col.dtype != object or str(col.name) in _ID_COLS:
        return None
    _sv = col.dropna().astype(str).str.strip()
    if _sv.str.fullmatch(r'0\d+').any():          # '005930' 같은 코드 — 숫자로 바꾸면 0 이 사라진다
        return None
    vals = col.dropna().astype(str).str.strip()
    vals = vals[~vals.isin(_MISSING)]
    if len(vals) == 0:
        return None
    out, units, curs = {}, set(), set()
    for i, v in vals.items():
        m = _CELL_RE.match(v)
        if not m:
            return None
        s1, d, s2, n, u = m.groups()
        x = float(n.replace(',', '')) * (-1 if '-' in (s1 + s2) or '−' in (s1 + s2) else 1)
        if d:
            curs.add(d)
        if u in _SCALE:
            base, k = _SCALE[u]
            x *= k
            u = base
        if u:
            units.add(u)
        out[i] = x
    if not (units or curs):
        # 단위 없는 숫자 + None 이 섞인 글자 열 → 숫자 열로(화면에 'None' 이 찍히던 문제, 2026-10-19)
        num = pd.Series(float('nan'), index=col.index)
        for i, x in out.items():
            num[i] = x
        return num, ''
    if len(units) > 1 or len(curs) > 1:
        return None
    u = units.pop() if units else ''
    c = curs.pop() if curs else ''
    if c == '₩':
        u = u + '원' if u in ('', '억') else u
    elif c == '$':
        u = '$' + u
    num = pd.Series(float('nan'), index=col.index)
    for i, x in out.items():
        num[i] = x
    # 2026-10-21 — 규모에 맞는 단위로: '853,000억' 처럼 0 이 줄줄이 붙지 않게 중앙값이 1조 이상이면 조,
    #   $B 인데 중앙값이 1 미만이면 $M. 시총 열은 사용자 규칙(한국 시총 = 억원)이라 그대로 둔다.
    med = num.abs().median()
    if '시총' not in str(col.name) and med == med:
        if u in ('억', '억원') and med >= 1e4:
            num, u = num / 1e4, u.replace('억', '조')
        elif u in ('B', '$B') and med < 1:
            num, u = num * 1e3, u.replace('B', 'M')
    return num, u


# 숫자 열인데 머리에 단위가 없는 것 — 이름으로 단위를 단다(규칙 ③)
_HEAD_UNIT = [
    (re.compile(r'^(평균|중앙값|시장대비|그주상승|고점대비|저점대비|YTD|매출YoY|매출성장|GPM|OPM|NPM|ROE|ROA|'
                r'이후\d+주|\d+개월상승|향후\dM계절성|수익률|상승률|승률|알파|MDD)$'), '%'),
    (re.compile(r'^(매출가속|이익가속|ΔGPM|ΔOPM|ΔNPM|ΔROE)$'), '%p'),
    (re.compile(r'^(RS\d*|PER|PBR|PSR|PEG|손익비)$'), '배'),
    (re.compile(r'^(신호|신호 수|표본)$'), '건'),
    (re.compile(r'^(누적|보유|청산|통과수)$'), '종'),
    (re.compile(r'^(종가|현재가|52주고|52주저|진입가|매수가|평단|그주종가)$'), '현지'),
]


def _head_unit(name: str, col: pd.Series):
    if '(' in name or '%' in name or col.dtype.kind not in 'fi':
        return None
    for rx, u in _HEAD_UNIT:
        if rx.match(name):
            return u
    return None


def normalize(df: pd.DataFrame):
    """(새 df, 이름 변환표 old→new, 단위를 걷어낸 열 집합)."""
    df = df.copy()
    if not isinstance(df.index, pd.RangeIndex) and df.index.name not in (None, ''):
        df = df.reset_index()
    elif not isinstance(df.index, pd.RangeIndex) and df.index.dtype == object:
        df = df.reset_index().rename(columns={'index': '항목'})
    df = df.reset_index(drop=True)
    ren, conv = {}, set()
    cols = [str(c) for c in df.columns]
    for c in df.columns:
        new = c
        if c in _ALIAS and _ALIAS[c] not in cols and _ALIAS[c] not in ren.values():
            new = _ALIAS[c]
        r = _unit_convert(df[c])
        if r is not None:
            num, u = r
            df[c] = num
            bare = u.lstrip('$')
            if u and u not in str(new) and not (bare and bare in str(new)):
                new = f'{new}({u})'
            elif not u:
                hu = _head_unit(str(new), df[c])
                if hu:
                    new = f'{new}({hu})'
            conv.add(new)
        else:
            hu = _head_unit(str(new), df[c])
            if hu:
                new = f'{new}({hu})'
        if new != c:
            ren[c] = new
    df = df.rename(columns=ren)
    # 2026-10-19 사용자 요청 — 한국 종목이 있는 표의 시총은 **억원**. ($B 로 '0.3B' 는 감이 안 온다)
    #   미국만 있는 표는 $B 그대로. 섞인 표도 억원으로 통일(같은 단위여야 정렬·필터가 성립한다).
    capb = next((c for c in df.columns if str(c) == '시총($B)'), None)
    if capb is not None and FX['fn']:
        kr = _kr_rows(df)
        if kr is not None and kr.any():
            try:
                rate = float(FX['fn']())
                df[capb] = (pd.to_numeric(df[capb], errors='coerce') * rate * 10).round(0)
                df = df.rename(columns={capb: '시총(억원)'})
                src = next((k for k, v in ren.items() if v == capb), capb)
                ren[src] = '시총(억원)'
                conv.add('시총(억원)')
            except Exception:
                pass
    # 가격 머리글의 통화 — 전부 한국이면 (원), 전부 미국이면 ($), 섞이면 (현지). 머리글이 짧아야 표가 안 넓어진다.
    _kr = _kr_rows(df)
    if _kr is not None and len(df):
        tag = '원' if _kr.all() else ('$' if not _kr.any() else None)
        if tag:
            r2 = {c: str(c).replace('(현지)', f'({tag})') for c in df.columns if str(c).endswith('(현지)')}
            if r2:
                df = df.rename(columns=r2)
                for k, v in list(ren.items()):
                    if v in r2:
                        ren[k] = r2[v]
                for old_c, new_c in r2.items():
                    if old_c not in ren.values() and old_c not in ren:
                        ren[old_c] = new_c
                conv = {r2.get(c, c) for c in conv}
    n = len(df)
    for c in list(df.columns):
        if str(c) in _ROWNO and n and pd.to_numeric(df[c], errors='coerce').tolist() == list(range(1, n + 1)):
            df = df.drop(columns=[c])
    df.insert(0, 'No.', range(1, n + 1))
    cap = next((c for c in df.columns if str(c).startswith('시총') or '시가총액' in str(c)), None)
    lead = ['No.'] + [c for c in ('종목', '코드', cap) if c is not None and c in df.columns]
    df = df[lead + [c for c in df.columns if c not in lead]]
    return df, ren, conv


def _remap_subset(sub, ren):
    if sub is None:
        return None
    if isinstance(sub, str):
        return ren.get(sub, sub)
    if isinstance(sub, (list, tuple, pd.Index)) and not (isinstance(sub, tuple) and len(sub) == 2
                                                       and not isinstance(sub[0], str)):
        return [ren.get(x, x) for x in sub]
    return sub


def _safe(func):
    def f(*a, **k):
        try:
            return func(*a, **k)
        except Exception:
            return ''
    return f


_PRINTF = re.compile(r'%([+]?)(,?)\.?(\d*)([dfi])')


def _na_dash(sty: Styler, df: pd.DataFrame, cfg: dict) -> Styler:
    """수치 열의 결측만 '-' 로. 값 표시는 column_config 의 printf 형식(없으면 소수 1자리)을 따른다.
    호출부가 이미 서식을 단 칸은 건드리지 않는다."""
    taken = {c for (_, c) in sty._display_funcs} if hasattr(sty, '_display_funcs') else set()
    fm = {}
    for i, c in enumerate(df.columns):
        if c == 'No.' or i in taken or not pd.api.types.is_numeric_dtype(df[c]) or not df[c].isna().any():
            continue
        f = (cfg.get(c) or {}).get('type_config', {}).get('format') if isinstance(cfg.get(c), dict) else None
        m = _PRINTF.search(f or '')
        plus, dp = (m.group(1), (0 if m.group(4) in 'di' else int(m.group(3) or 0))) if m else ('', 1)
        if not m and pd.api.types.is_integer_dtype(df[c].dropna()):
            dp = 0
        if not m and df[c].dropna().apply(lambda v: float(v).is_integer()).all():
            dp = 0
        fm[c] = (lambda v, dp=dp, plus=plus: '-' if pd.isna(v) else f"{v:{plus},.{dp}f}")
    return sty.format(fm) if fm else sty


def restyle_for(sty: Styler, new_df: pd.DataFrame, ren: dict, conv: set) -> Styler:
    """호출부 Styler 의 서식·색 함수를 정규화한 표로 옮긴다."""
    new = new_df.style
    for fn, args, kw in sty._todo:
        args = list(args)
        if args:
            args[0] = _safe(args[0]) if callable(args[0]) else args[0]
            args[-1] = _remap_subset(args[-1], ren)
        new._todo.append((fn, tuple(args), kw))
    pos = {c: i for i, c in enumerate(new_df.columns)}
    for (r, c), f in sty._display_funcs.items():
        old = sty.data.columns[c]
        nm = ren.get(old, old)
        if nm in pos and nm not in conv:
            new._display_funcs[(r, pos[nm])] = f
    # 2026-10-21 — conv 가 비면 format({}) 가 **모든 열의 서식을 기본값으로 덮어** 호출부 서식(부호·소수 자리)이
    #   사라졌다(재무제표 증감 '+17' → '16.800000'). 변환한 열이 있을 때만, 그 열에만 건다.
    if conv:
        new.format({c: (lambda v: '-' if pd.isna(v) else f'{v:,.0f}') if str(c).endswith('원)')
                    else (lambda v: '-' if pd.isna(v) else f'{v:,.1f}') for c in conv}, subset=list(conv))
    for a in ('table_styles', 'css', 'table_attributes'):
        if hasattr(sty, a):
            setattr(new, a, getattr(sty, a))
    return new


_FMT_SPEC = re.compile(r'%[+\-#0 ]*\d*(?:\.\d+)?[dfeEgGis]')


def strip_fmt_units(cfg: dict) -> dict:
    """column_config 의 표시 포맷이 칸 안에 단위를 다시 붙이지 않게('$%.1fB' → '%.1f')."""
    for k, v in list(cfg.items()):
        if not isinstance(v, dict):
            continue
        tc = v.get('type_config') or {}
        f = tc.get('format')
        if isinstance(f, str) and '%' in f:
            m = _FMT_SPEC.search(f.replace('%%', ''))
            if m and m.group(0) != f:
                v = dict(v)
                v['type_config'] = dict(tc, format=m.group(0))
                cfg[k] = v
    return cfg


# ── 종목 클릭 → 종목 분석 (2026-10-19) ────────────────────────────
NAV = {'fn': None}
FX = {'fn': None}      # 원/달러 — 대시보드가 set_fx(_usdkrw) 로 넣는다


def set_fx(fn):
    FX['fn'] = fn


def _kr_rows(df):
    """행마다 한국 종목인가. '시장' 열이 있으면 그걸, 없으면 코드 모양(6자리)으로."""
    if '시장' in df.columns:
        return df['시장'].astype(str).str.upper().eq('KR')
    if '코드' in df.columns:
        return df['코드'].astype(str).str.fullmatch(r'\d{5}[0-9A-Z]')
    return None


def set_nav(fn):
    """dashboard 가 '종목 분석으로 이동' 함수를 꽂는다. 표의 종목·코드 칸 클릭 → fn(코드)."""
    NAV['fn'] = fn


# ── 열 폭을 내용에 맞춘다 (2026-10-19) ────────────────────────────
#   Streamlit 기본 폭은 내용과 무관하게 넓다(No. 열이 숫자 한 자리에 100px+).
#   머리글·값 중 가장 긴 것 기준으로 px 를 잡고, 표 전체 폭도 내용만큼만 쓴다.
import unicodedata as _ud


def _dw(s: str) -> int:
    return sum(2 if _ud.east_asian_width(ch) in ('W', 'F') else 1 for ch in s)


def _fmt_len(v) -> int:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return 1
    if isinstance(v, float):
        return len(f'{v:,.1f}')
    return _dw(str(v))


def auto_widths(df: pd.DataFrame, cfg: dict) -> dict:
    cfg = dict(cfg or {})
    for c in df.columns:
        col = df[c].head(300)
        # 머리글(12px)은 값(12.5px 고정폭 숫자)보다 좁게 친다 — 머리글이 열 폭을 지배하지 않게
        # 2026-10-19 '너무 넉넉하다' — 머리글은 12px 글꼴(한글 ≈ 12px = _dw 2칸), 값은 12.5px 고정폭.
        hw = _dw(str(c)) * 6.1 + 22
        vw = max([_fmt_len(v) for v in col.tolist()] or [1]) * 7.3 + 18
        px = int(min(max(hw, vw, 44), 240))     # 긴 글(회사명·업종)은 잘리고 마우스를 올리면 전체가 보인다
        if str(c) == '종목':
            px = min(px, 170)                   # 미국 회사명이 길어 표를 옆으로 밀었다(2026-10-19)
        cur = cfg.get(c)
        if isinstance(cur, dict):
            if not cur.get('width'):
                cur = dict(cur); cur['width'] = px; cfg[c] = cur
        elif cur is None:
            cfg[c] = {'width': px}
    return cfg


def src(text: str, asof: str | None = None):
    """이후 그려지는 표들의 출처·갱신일. 다음 src() 호출 전까지 유지된다."""
    import streamlit as st
    st.session_state['_tbl_src'] = (text, asof)


def _footer(st, text, asof):
    if not text:
        text, asof = st.session_state.get('_tbl_src') or (None, None)
    st.caption(f"출처: {text or '⚠️ 미지정'} · 마지막 갱신: {asof or '미상'}")


# ── 설치 ──────────────────────────────────────────────────────────
def begin_run(st):
    """스크립트 매 실행 맨 위에서 호출 — 같은 줄의 표가 여러 번 그려질 때 키 순번을 0부터."""
    st.session_state['_tbl_seen'] = {}
    st.session_state['_tbl_src'] = (None, None)


def install(st):
    """st.dataframe 을 감싼다. 한 번만 감싸고(재실행·다중 세션에서 겹치지 않게),
    세션별 상태는 session_state 에만 둔다(모듈 전역 금지 — 세션 간 공유된다)."""
    # 2026-10-20 사고: 클라우드 프로세스가 **옛 래퍼**를 st 에 붙인 채로 새 코드를 돌려
    #   새 인자(footer)가 Streamlit 원본까지 흘러가 종목분석 섹션이 죽었다. 그래서 버전이 다르면
    #   다시 감싸고, 원본은 늘 st._main.dataframe(감싸지 않은 진짜)에서 가져온다(겹겹이 감싸지 않게).
    if getattr(st, '_tbl_ver', None) == API_VERSION:
        return
    orig = st._main.dataframe

    def dataframe(data=None, *a, filters=None, color=True, src=None, asof=None, footer=True, **kw):
        # footer=False: 바로 아래 이어지는 표(한 묶음)가 출처를 대신 단다 — 같은 줄이 두 번 뜨지 않게
        try:
            return _dataframe(data, *a, filters=filters, color=color, **kw)
        finally:
            if footer:
                _footer(st, src, asof)

    def _dataframe(data=None, *a, filters=None, color=True, **kw):
        try:
            sty = data if isinstance(data, Styler) else None
            df = sty.data if sty is not None else data
            if not isinstance(df, pd.DataFrame):
                return orig(data, *a, **kw)

            # 표 형식(행번호·좌측 열 순서·단위는 머리행) — 2026-10-19
            df, ren, conv = normalize(df)
            if sty is not None:
                sty = restyle_for(sty, df, ren, conv)
            data = sty if sty is not None else df
            kw['hide_index'] = True
            if isinstance(kw.get('column_config'), dict):
                kw['column_config'] = strip_fmt_units(
                    {ren.get(k, k): v for k, v in kw['column_config'].items()})
                kw['column_config'].setdefault('No.', st.column_config.NumberColumn('No.', format='%d'))
            if kw.get('column_order'):
                kw['column_order'] = ['No.'] + [ren.get(c, c) for c in kw['column_order'] if c != 'No.']

            # 표시 소수 1자리(2026-08-17 규칙) — 호출부가 column_config 를 안 줬을 때만
            if 'column_config' not in kw:
                cfg = {c: st.column_config.NumberColumn(format='%.1f')
                       for c in df.columns if pd.api.types.is_float_dtype(df[c])}
                cfg['No.'] = st.column_config.NumberColumn('No.', format='%d')
                kw['column_config'] = cfg

            fr = sys._getframe(2)   # dataframe() → _dataframe() 한 겹 더
            base = f'tf|{os.path.basename(fr.f_code.co_filename)}:{fr.f_lineno}'
            seen = st.session_state.setdefault('_tbl_seen', {})
            seen[base] = seen.get(base, -1) + 1
            key = f'{base}#{seen[base]}'
            use_f = filters if filters is not None else len(df) >= MIN_ROWS_FOR_FILTER
            if use_f and not kw.get('on_select'):
                _, hide, keep = _filter_ui(st, df, key)
                if not keep.all():
                    if sty is not None:
                        sty = _restyle(sty, keep)
                        sty.data['No.'] = range(1, len(sty.data) + 1)
                    df = df[keep].copy()
                    df['No.'] = range(1, len(df) + 1)
                if hide:
                    order = kw.get('column_order') or list(df.columns)
                    kw['column_order'] = [c for c in order if c not in hide]
                if 'height' in kw and isinstance(kw['height'], int) and len(df) < len(data.data if isinstance(data, Styler) else data):
                    kw['height'] = min(kw['height'], 35 + 26 * max(len(df), 1) + 4)

            if '시총(억원)' in df.columns:          # 억원은 천 단위 쉼표 정수
                kw.setdefault('column_config', {})
                kw['column_config']['시총(억원)'] = st.column_config.NumberColumn('시총(억원)', format='localized')

            # 높이 — 25행 이하는 스크롤 없이 전부 보이게(2026-10-19: 7행 표인데 6행만 보이고 세로 드래그).
            #   호출부의 _dfh 는 행 25px 를 가정했는데 실제 행은 35px(테마·기본) 이라 늘 한두 행이 잘렸다.
            _rh = kw.get('row_height') or 35
            if len(df) <= 25:
                kw['height'] = (len(df) + 1) * _rh + 3 + (12 if len(df) <= 4 else 0)
                # ↑ 2026-10-20: 2행 표(사업부문)가 가로 스크롤바 높이만큼 잘려 세로 드래그가 생겼다 — 짧은 표에 여유
            elif not kw.get('height'):
                kw['height'] = 26 * _rh + 3

            # 열 폭 = 내용 폭, 표 폭 = 열 합 (컨테이너를 억지로 채우지 않는다)
            kw['column_config'] = auto_widths(df, kw.get('column_config'))
            # 2026-10-21 — 열이 많은 표(재무제표 13열+)는 가로 스크롤바가 생기고, 그 높이(≈14px)만큼 마지막 행이 가려져
            #   세로 드래그가 생겼다. 열 폭 합이 화면 본문 폭을 넘을 만한 표는 스크롤바 자리를 더 준다.
            if len(df) <= 25:
                _tw = sum((v.get('width') or 0) for v in kw['column_config'].values() if isinstance(v, dict))
                if _tw > 900:
                    kw['height'] += 16
            kw.pop('use_container_width', None)
            kw['width'] = 'content'

            # 종목·코드 칸 클릭 → 종목 분석으로 (호출부가 선택을 따로 쓰지 않을 때만)
            if NAV['fn'] and '코드' in df.columns and not kw.get('on_select') and 'key' not in kw:
                codes = df['코드'].astype(str).tolist()
                skey = key + '|sel'

                def _go(skey=skey, codes=codes):
                    ev = st.session_state.get(skey) or {}
                    sel = ev.get('selection', {}) if isinstance(ev, dict) else getattr(ev, 'selection', {})
                    for r, c in (sel.get('cells') or []):
                        if c in ('종목', '코드') and 0 <= r < len(codes) and codes[r] not in ('', 'nan', 'None'):
                            NAV['fn'](codes[r])
                            return
                kw.update(on_select=_go, selection_mode='single-cell', key=skey)
                cc = kw['column_config']
                for c in ('종목', '코드'):
                    if isinstance(cc.get(c), dict):
                        cc[c] = dict(cc[c], help='클릭하면 종목 분석으로 이동')

            if color:
                if sty is None:
                    sty = df.style
                sty = apply_colors(sty, df)
            # 결측은 '-' — Streamlit 은 NaN 을 'None' 으로 그린다(2026-10-19, 데이터 원칙)
            sty = _na_dash(sty if sty is not None else df.style, df, kw.get('column_config') or {}) \
                if df.select_dtypes('number').isna().any().any() else sty
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
    st._tbl_ver = API_VERSION
