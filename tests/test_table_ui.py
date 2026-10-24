"""table_ui 규칙 고정 — 색·숫자 해석·필터 재매핑 (2026-10-15).

규칙이 조용히 바뀌면 화면은 멀쩡해 보이면서 뜻이 뒤집힌다(초록이 '좋음'이 아닌 열을 칠하는 등).
그래서 '무엇을 칠하고 무엇을 안 칠하는가'를 테스트로 박아 둔다."""
import math
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import table_ui as T  # noqa: E402


def test_parse_strings():
    assert T._parse('+12.3%') == 12.3
    assert T._parse('✅ +61%') == 61
    assert T._parse('$-19M') == -19e6                 # 부호가 통화 기호 뒤
    assert T._parse('$-1.14B') < T._parse('$144M')    # 단위가 섞여도 크기 순 유지
    assert T._parse('1.2조') > T._parse('3,456억')
    assert math.isnan(T._parse('2026-03-31'))         # 날짜는 숫자가 아니다
    assert math.isnan(T._parse('-'))
    assert math.isnan(T._parse('흑자전환'))


def test_signed_vs_level_columns():
    df = pd.DataFrame({
        '수익률': [5, -3, 10, 2], 'PER': [-5, 10, 30, 12], '시총($B)': [1, 2, 3, 4],
        '위닝점수': [50, 60, 70, 80], '코드': ['1', '2', '3', '4'], 'OPM': [5, 6, 7, 8],
        '상위1% 의존': [10, 50, 80, 30], 'RS (L)': [70, 80, 90, 99]})
    plan = T.color_plan(df)
    assert '수익률' in plan and 'OPM' in plan          # 부호에 뜻이 있다(OPM 은 음수 없어도)
    for c in ('PER', '시총($B)', '위닝점수', '코드', '상위1% 의존', 'RS (L)'):
        assert c not in plan, c                        # 수준·위험·식별자는 칠하지 않는다


def test_centers():
    df = pd.DataFrame({'승률': [40, 60, 55, 30], 'RS13': [0.8, 1.2, 1.5, 0.9], '손익비': [0.5, 2, 3, 1.1]})
    plan = T.color_plan(df)
    assert plan['승률'][0] == 50 and plan['RS13'][0] == 1 and plan['손익비'][0] == 1


def test_colors_green_red_and_intensity():
    assert 'rgba(22,163,74' in T._bg(5, 10)          # + 초록
    assert 'rgba(220,38,38' in T._bg(-5, 10)         # − 빨강
    a = lambda s: float(s.rsplit(',', 1)[1].rstrip(')'))
    assert a(T._bg(9, 10)) > a(T._bg(2, 10))          # 클수록 진하다
    assert T._bg(0, 10) == '' and T._bg(float('nan'), 10) == ''


def test_word_columns_only_short_verdicts():
    df = pd.DataFrame({'판정': ['흑자전환', '적자전환', '-', '흑전'],
                       '설명': ['실적이 개선되는 구간을 찾는 규칙입니다'] * 4})
    plan = T.color_plan(df)
    assert '판정' in plan and '설명' not in plan       # 문장 속 '개선'은 판정이 아니다


def test_restyle_keeps_formats_after_row_filter():
    df = pd.DataFrame({'a': [1.234, -2.0, 3.5], 'b': ['x', 'y', 'z']})
    sty = df.style.format({'a': '{:+.2f}'})
    keep = pd.Series([False, True, True]).values
    new = T._restyle(sty, keep)
    html = new.to_html()
    assert '-2.00' in html and '+3.50' in html and '+1.23' not in html


# ── 2026-10-24 디자인 재점검 ─────────────────────────────────────
def test_fit_height_no_blank_row():
    """5행 표 = 머리행 31 + 5×31 + 테두리 2 — 35px 가정으로 빈 행이 생기던 사고 재발 방지(크로미움 실측값)."""
    import table_ui as t
    assert t.fit_height(5) == 31 + 5 * 31 + 2
    assert t.fit_height(0) == t.fit_height(1)          # 빈 표도 한 줄 자리


def test_split_note_keeps_all_text():
    import table_ui as t
    long = ('표본 21개월 — 분위가 불안정하다. 자본(잔액) 기준. 월말 시가총액 ÷ 그 시점 TTM. '
            '⚠️ 증자·자사주로 주식수가 크게 변한 종목은 과거 멀티플이 왜곡된다. ⚠️ **10분위는 바닥이 아니다** — 분모가 줄면 하단도 뚫린다. '
            '환산주가는 최근 TTM 이 유지된다면의 가정이다.')
    assert len(long) > t.NOTE_MAX
    head, rest = t.split_note(long)
    assert rest and len(head) <= t.NOTE_MAX
    assert (head + ' ' + rest).replace(' ', '') .startswith(long.replace(' ', '')[:20])
    assert len(head.replace(' ', '')) + len(rest.replace(' ', '')) >= len(long.replace(' ', '')) - 3   # 글자를 버리지 않는다
    short = '짧은 설명.'
    assert t.split_note(short) == (short, '')
