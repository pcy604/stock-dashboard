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
API_VERSION = 6          # install() 동작·인자를 바꾸면 올린다(옛 래퍼 교체 신호)

# 크기가 의미 없는 열 — 식별자·순번·날짜
NO_COLOR = {'No.', '회차', '주차', '코드', '종목', '종목명', '연도', '달', '연월', '월', '시장', '섹터',
            '그 해 회차', '신호', '표본', '신호 수', '첫 신호', '마지막 신호', '기준일', '날짜'}
# '수준' 열 — 부호가 아니라 크기라서 칠하지 않는다(음수가 있어도: PER<0 은 적자일 뿐)
_LEVEL = re.compile(r'PER|PBR|PSR|PEG|EV/|시총|가격|현재가|진입가|매수가|평단|종가|52주고|52주저|'
                    r'점수|등급|백분위|수량|주수|비중|통과율|통과수|개수|표본|건수|거래량|배수|RS ?\(L\)|퍼센타일|'
                    r'^N$|^n$|평가금|원금|매입|중요도|경과|주기|의존|집중|변동성|베타|'
                    r'전환가|조정가|행사가|단가|발행액|희석|발행주식|보유\(주\)')
# ↑ 2026-10-21 실화면: '최저 조정가'(이름의 '최저')·'발행주식 대비'(이름의 '대비')가 초록으로 칠해졌다 — 가격·물량은 수준이고,
#   희석 비율은 높을수록 위험이라 초록이면 뜻이 뒤집힌다.
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
CAP_MIXED = '시총(억원·$B)'
_MISSING = {'', '-', '—', '·', 'None', 'nan', 'NaN', 'N/A', 'n/a'}


_ID_COLS = {'코드', 'sym', '티커', 'Ticker', 'ticker', 'Symbol', 'symbol', '종목코드', '심볼',
            '주차', '연도', '연월', '월', '달', '기준일', '날짜', '일자', '진입일', '회복일', '고점일', '저점일',
            '발표일', '기준분기', '분기', 'period', '기간', '회차', '결정일', '청구 종료'}


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
    (re.compile(r'^(RS\d+|PER|PBR|PSR|PEG|손익비)$'), '배'),   # RS 단독은 백분위(2026-10-26 'RS(배)' 오표기)
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
    # 2026-10-26 사용자 규칙 갱신 — 한국 = 억원, 미국 = $B. **섞인 표는 값은 각자 단위 그대로 두고
    #   머리행에 두 단위를 함께 적는다** '시총(억원·$B)'(두 단위가 다르다는 걸 보이게). 기본 정렬은 호출부가 달러 환산으로.
    capb = next((c for c in df.columns if str(c) == '시총($B)'), None)
    if capb is not None and FX['fn']:
        kr = _kr_rows(df)
        if kr is not None and kr.any():
            try:
                rate = float(FX['fn']())
                v = pd.to_numeric(df[capb], errors='coerce')
                name = '시총(억원)' if kr.all() else CAP_MIXED
                df[capb] = v.where(~kr, (v * rate * 10).round(0)).where(kr, v.round(1))
                df = df.rename(columns={capb: name})
                src = next((k for k, v in ren.items() if v == capb), capb)
                ren[src] = name
                conv.add(name)
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


_PRINTF_NUM = re.compile(r'%(\+)?(0|\'.)?(-)?(,|_)?(\d+)?(\.\d+)?([dif])')


def _yearish(s: pd.Series) -> bool:
    """연도·코드처럼 쉼표를 찍으면 안 되는 정수 열(2,025 가 되면 안 된다)."""
    if str(s.name) in _ID_COLS or str(s.name) == 'No.':
        return True
    v = pd.to_numeric(s, errors='coerce').dropna()
    return len(v) > 0 and bool(((v >= 1900) & (v <= 2100) & (v == v.round())).all())


def add_thousands(cfg: dict, df: pd.DataFrame) -> dict:
    """2026-10-21 — 모든 표 숫자에 천 단위 쉼표. Streamlit 기본 표시는 쉼표를 안 찍는다(numbro thousandSeparated:false).
    printf 서식 '%.1f'·'%+.1f'·'%d' → '%,.1f'·'%+,.1f'·'%,d' (Streamlit sprintf-js 는 '+' 다음 ',' 순서만 받는다)."""
    for k, v in list(cfg.items()):
        if not isinstance(v, dict) or k not in df.columns or _yearish(df[k]):
            continue
        tc = v.get('type_config') or {}
        f = tc.get('format')
        if not (isinstance(f, str) and '%' in f):
            continue
        m = _PRINTF_NUM.search(f)
        if not m or m.group(4):
            continue
        sign, pad, left, _, width, prec, typ = m.groups()
        nf = f[:m.start()] + '%' + (sign or '') + (pad or '') + (left or '') + ',' + (width or '') + (prec or '') + typ + f[m.end():]
        v = dict(v)
        v['type_config'] = dict(tc, format=nf)
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


# 표 높이 계측값(2026-10-24, 크로미움 실측): 앱 CSS 가 글자 기준을 14px 로 줄여 머리행·행이 31px.
#   row_height 를 따로 주면 행만 그 값이고 머리행은 31 그대로다. 테두리 2px.
HEAD_PX, ROW_PX, BORDER_PX = 31, 31, 2
HSCROLL = 8           # 가로 스크롤바 자리(윈도, CSS 로 6px). 넓은 표에만


def fit_height(n: int, row_height=None) -> int:
    """n행이 빈 행 없이 딱 들어가는 높이(px)."""
    return HEAD_PX + max(int(n), 1) * int(row_height or ROW_PX) + BORDER_PX


# ── 표가 놓인 칸의 폭 (2026-10-24) ─────────────────────────────────
#   종목마다 글 길이가 달라(부문명·주요제품) 반쪽 칸에서 표가 넘쳐 오른쪽 열이 잘렸다.
#   서버는 화면 폭을 모르지만 st.columns 비율은 안다 → 본문 폭 × 비율로 '들어갈 자리'를 어림한다.
PAGE_PX = 1150          # 본문 최대 1320(1400−여백)이지만 노트북(1280~1366px) 화면에 맞춰 보수적으로 — 넘쳐서 숫자가 잘리는 것보다 글이 줄어드는 게 낫다
GAP_PX = 28             # 칸 사이 간격(중간 gap) 몫


def _patch_blocks():
    """st.columns 가 만든 칸에 비율(_mo_frac)을 붙인다. 한 번만."""
    from streamlit.delta_generator import DeltaGenerator as _DG
    if getattr(_DG._block, '_mo_frac', False):
        return
    _orig = _DG._block

    def _block(self, block_proto=None, dg_type=None):
        dg = _orig(self, block_proto, dg_type)
        try:
            if block_proto is not None and block_proto.WhichOneof('type') == 'column':
                dg._mo_frac = float(block_proto.column.weight) or 1.0
        except Exception:
            pass
        return dg
    _block._mo_frac = True
    _DG._block = _block


def avail_px() -> int:
    """지금 그리려는 자리의 대략적 폭(px). 칸 안의 칸이면 비율을 곱한다."""
    try:
        import streamlit as st
        dg = st._main._active_dg
        w, n = float(PAGE_PX), 0
        while dg is not None and n < 12:
            # DeltaGenerator 는 없는 속성도 함수로 돌려준다(__getattr__) → __dict__ 에서 직접 읽는다
            f = vars(dg).get('_mo_frac')
            if isinstance(f, float) and f > 0:
                w = w * f - GAP_PX
            dg = vars(dg).get('_parent')
            n += 1
        return int(max(w, 240))
    except Exception:
        return PAGE_PX


def auto_widths(df: pd.DataFrame, cfg: dict, avail: int | None = None) -> dict:
    """열 폭 = 내용 폭. 자리(avail)를 넘으면 **글 열부터** 줄여 맞춘다 — 숫자 열은 자르지 않는다
    (잘린 글은 마우스를 올리면 전체가 보인다)."""
    cfg = dict(cfg or {})
    want, floor, textcol, fixed = {}, {}, set(), {}
    for c in df.columns:
        col = df[c].head(300)
        # 머리글(12px)은 값보다 좁게 친다 — 머리글이 열 폭을 지배하지 않게(2026-10-19)
        hw = _dw(str(c)) * 6.1 + 22
        vw = max([_fmt_len(v) for v in col.tolist()] or [1]) * 7.3 + 18
        is_text = col.dtype == object and str(c) not in ('No.', '코드')
        # 문장 열('할 일·근거')은 넓게, 이름 열은 240·종목은 170 상한(2026-10-19·24)
        _cap = 520 if (is_text and str(c) != '종목' and vw > 360) else 240
        px = int(min(max(hw, vw, 44), _cap))
        if str(c) == '종목':
            px = min(px, 170)
        cur = cfg.get(c)
        if isinstance(cur, dict) and isinstance(cur.get('width'), (int, float)):
            fixed[c] = cur['width']                       # 호출부가 정한 숫자 폭은 존중
            continue
        if isinstance(cur, dict) and isinstance(cur.get('width'), str) and px <= 400:
            continue                                      # 'small'·'medium'·'large' 그대로
        want[c] = px
        if is_text:
            textcol.add(c)
            floor[c] = int(max(hw, 96))                   # 글 열은 머리글이 보이는 만큼까지 줄일 수 있다
        else:
            floor[c] = px
    if avail:
        total = sum(want.values()) + sum(fixed.values())
        over = total - avail
        room = sum(want[c] - floor[c] for c in textcol)
        if over > 0 and room > 0:
            k = min(1.0, over / room)                     # 글 열의 '줄일 수 있는 몫'을 같은 비율로
            for c in textcol:
                want[c] = int(want[c] - (want[c] - floor[c]) * k)
    for c, px in want.items():
        cur = cfg.get(c)
        cfg[c] = dict(cur, width=px) if isinstance(cur, dict) else {'width': px}
    return cfg


def total_width(cfg: dict) -> int:
    return int(sum(v['width'] for v in cfg.values()
                   if isinstance(v, dict) and isinstance(v.get('width'), (int, float))))


def src(text: str, asof: str | None = None):
    """이후 그려지는 표들의 출처·갱신일. 다음 src() 호출 전까지 유지된다."""
    import streamlit as st
    st.session_state['_tbl_src'] = (text, asof)


def _footer(st, text, asof):
    if not text:
        text, asof = st.session_state.get('_tbl_src') or (None, None)
    st.caption(f"출처: {text or '⚠️ 미지정'} · 마지막 갱신: {asof or '미상'}")


# ── 긴 설명 접기 (2026-10-24) ─────────────────────────────────────
#   캡션이 최대 415자 — 표·차트 아래 회색 문단이 화면을 덮었다. 첫 문장만 보이고 나머지는 '자세히'.
#   글자를 지우지 않는다(데이터 원칙: 한계는 화면에 남긴다). 출처 줄·예외 문구(백틱 시작)는 그대로.
NOTE_MAX = 150


def _md_inline(t: str) -> str:
    import html as _h, re as _re
    t = _h.escape(t, quote=False)
    t = _re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', t)
    t = _re.sub(r'`([^`]+)`', r'<code>\1</code>', t)
    t = _re.sub(r'\[([^\]]+)\]\((https?://[^)\s]+)\)', r'<a href="\2" target="_blank">\1</a>', t)
    return t.replace('\n', '<br>')


def split_note(text: str, limit: int = NOTE_MAX):
    """(머리, 나머지). 짧으면 나머지는 ''. 문장 끝(. — ·) 에서 자르고 없으면 공백에서."""
    t = text.strip()
    if len(t) <= limit:
        return t, ''
    cut = -1                                     # 첫 문장(30자 이상)에서 끊는다 — 요지만 보이게
    for mark in ('. ', ' — ', '; '):
        i = t.find(mark, 30)
        if i != -1 and i + 1 <= limit and (cut < 0 or i + 1 < cut):
            cut = i + (1 if mark == '. ' else 0)
    if cut < 20:
        cut = t.rfind(' ', 0, limit)
    if cut < 20:
        cut = limit
    head, rest = t[:cut].strip(), t[cut:].strip(' —;')
    if head.count('**') % 2:                     # 굵게 표시가 반으로 갈라지지 않게
        return t, ''
    return head, rest


def _caption_patch(st, orig):
    def caption(body, *a, **kw):
        try:
            if a or set(kw) - {'unsafe_allow_html'} or not isinstance(body, str):
                return orig(body, *a, **kw)
            t = body.strip()
            # 법적 안내(투자 권유 아님·면책)는 접지 않는다 — 다 보여야 한다
            if t.startswith('`') or t.startswith('출처') or '<' in t or '$' in t or '권유' in t or '책임' in t:
                return orig(body, *a, **kw)
            head, rest = split_note(t)
            if not rest:
                return orig(body, *a, **kw)
            return st.markdown(f"<div class='mo-note'>{_md_inline(head)}<details><summary>자세히 ▾</summary>"
                               f"{_md_inline(rest)}</details></div>", unsafe_allow_html=True)
        except Exception as e:
            if type(e).__module__.startswith('streamlit'):
                raise
            return orig(body, *a, **kw)
    return caption


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
    _patch_blocks()

    def dataframe(data=None, *a, filters=None, color=True, src=None, asof=None, footer=True, tkey=None, **kw):
        # tkey: 공통 함수(dashboard._std_table)가 대신 부를 때 호출 자리를 키로 넘긴다 — 안 주면 모든 표가
        #   같은 줄 번호 키를 써서 필터 위젯 키가 겹친다(2026-10-26 DuplicateElementKey)
        # footer=False: 바로 아래 이어지는 표(한 묶음)가 출처를 대신 단다 — 같은 줄이 두 번 뜨지 않게
        try:
            return _dataframe(data, *a, filters=filters, color=color, _tkey=tkey, **kw)
        finally:
            if footer:
                _footer(st, src, asof)

    def _dataframe(data=None, *a, filters=None, color=True, _tkey=None, **kw):
        try:
            sty = data if isinstance(data, Styler) else None
            df = sty.data if sty is not None else data
            if not isinstance(df, pd.DataFrame):
                return orig(data, *a, **kw)

            # 표 형식(행번호·좌측 열 순서·단위는 머리행) — 2026-10-19
            df, ren, conv = normalize(df)
            # 2026-10-24 행 높이 하나로 — 표마다 25·31px 가 섞여 탭마다 표 밀도가 달랐다
            kw.pop('row_height', None)
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
            # 2026-10-21 — column_config 서식은 Styler 서식보다 우선한다(Streamlit 문서). 호출부가 Styler 로 서식을 정한 열
            #   (재무제표처럼 행마다 단위가 다른 표)에 기본 '%.1f' 를 깔면 그 서식(부호·쉼표·소수 자리)이 지워졌다 → 건너뛴다.
            _sty_cols = set()
            if sty is not None:
                _sty_cols = {sty.data.columns[c] for (_r, c) in sty._display_funcs.keys()
                             if c < len(sty.data.columns)}
            cfg = kw.get('column_config') if isinstance(kw.get('column_config'), dict) else None
            if cfg is None:
                cfg = {'No.': st.column_config.NumberColumn('No.', format='%d')}
            for c in df.columns:
                if c in cfg or c in _sty_cols or c == 'No.':
                    continue
                if pd.api.types.is_float_dtype(df[c]):
                    # 주식 수는 정수로(6,539.0 → 6,539) — 2026-10-21 실화면
                    _int = '(주)' in str(c) or str(c) in ('주수', '수량') or (df[c].dropna() % 1 == 0).all() and df[c].abs().max() >= 1000
                    cfg[c] = st.column_config.NumberColumn(format='%.0f' if _yearish(df[c]) else '%,.0f' if _int else '%,.1f')
                elif pd.api.types.is_integer_dtype(df[c]) and not _yearish(df[c]):
                    cfg[c] = st.column_config.NumberColumn(format='%,d')
            kw['column_config'] = add_thousands(cfg, df)

            fr = sys._getframe(2)   # dataframe() → _dataframe() 한 겹 더
            base = f'tf|{_tkey}' if _tkey else f'tf|{os.path.basename(fr.f_code.co_filename)}:{fr.f_lineno}'
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
                    kw['height'] = min(kw['height'], fit_height(len(df), kw.get('row_height')))

            # 시총 — 억원은 쉼표 정수, $B 는 소수 1자리, 섞인 열은 행마다 자기 단위(localized 가 소수 자리를 값대로 보인다)
            kw.setdefault('column_config', {})
            if '시총(억원)' in df.columns:
                kw['column_config']['시총(억원)'] = st.column_config.NumberColumn('시총(억원)', format='localized')
            if '시총($B)' in df.columns:
                kw['column_config']['시총($B)'] = st.column_config.NumberColumn('시총($B)', format='%,.1f')
            if CAP_MIXED in df.columns:
                kw['column_config'][CAP_MIXED] = st.column_config.NumberColumn(
                    CAP_MIXED, format='localized',
                    help='한국 종목 = 억원, 미국 종목 = $B (값의 단위가 다르다). 기본 순서는 달러 환산 시총 기준 — '
                         '머리글을 눌러 정렬하면 두 단위가 섞여 정렬된다')

            # 높이 — 25행 이하는 스크롤 없이 전부, 빈 행 없이(2026-10-24 재설계).
            #   원인: 행 높이를 35px 로 가정했는데 이 앱은 글자 기준을 14px 로 줄여(rem) 실제 행·머리행이 31px 다.
            #   행마다 4px 씩 남아 5행이면 빈 행 하나가 생겼고, 짧은 표 +12·넓은 표 +16 여유분이 그 위에 더해졌다.
            _av = avail_px()
            kw['column_config'] = auto_widths(df, kw.get('column_config'), _av)
            _tw = total_width(kw['column_config'])
            if len(df) <= 25:
                # 가로 스크롤바가 자리를 차지하는 환경(윈도 크롬)에서 마지막 행이 가려지지 않게 — 실제로 넘칠 표만
                kw['height'] = fit_height(len(df), kw.get('row_height')) + (HSCROLL if _tw > _av else 0)
            elif not kw.get('height'):
                kw['height'] = fit_height(25, kw.get('row_height'))
            kw.pop('use_container_width', None)
            kw['width'] = 'content'
            # 2026-10-21 — 빈 칸을 '-' 로. Streamlit 은 결측을 Styler 서식과 무관하게 회색 'None' 으로 그린다
            #   (프런트 기본 placeholder='None'). 그래서 _na_dash 만으로는 안 바뀌었다(실화면 확인). streamlit>=1.66 인자.
            kw.setdefault('placeholder', '-')

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
    st.caption = _caption_patch(st, st._main.caption)
    st._tbl_patched = True
    st._tbl_ver = API_VERSION
