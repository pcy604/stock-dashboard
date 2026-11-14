# -*- coding: utf-8 -*-
"""📘 사용법·전체 설명서의 단일 원천 (2026-11-14).

화면 '사용법' 패널(한눈에 · 활용 루틴 · 전체 설명서)과 PDF(docs/manual.pdf)가 전부 이 파일에서 나온다.
같은 내용을 두 곳에 쓰지 않는다 — 옛 GUIDE.md 는 화면이 바뀔 때마다 낡았다('검은 배너'·'이번 주 할 일'·'12종 카드').

자동으로 따라오는 것(손으로 안 고친다):
  · 실전 규칙 값        ← live/plan.py RULE
  · 백테스트 숫자       ← results/v19_bt.json
  · 갱신 시각           ← .github/workflows/*.yml cron(UTC → KST)
  · 개선 내역           ← docs/release_notes.json (화면이 바뀌는 작업마다 한 줄 — CLAUDE.md 규칙)
  · PDF                 ← manual-pdf 워크플로가 위 파일이 바뀔 때마다 다시 만든다
손으로 고치는 것: 아래 CAPS·ROUTINES·GLOSSARY·DROPPED·DATA_ROWS 문구. 고치면 화면·PDF 가 같이 바뀐다.

공개 문서다 — 운영자 이름·계좌 금액·실행 인프라·사용자 수·마케팅 계획은 넣지 않는다(tests/test_manual.py 가 금칙어 검사).
streamlit 을 import 하지 않는다(CI 에서 PDF 만 만들 때도 돌아야 한다).
"""
from __future__ import annotations

import ast
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = '2026-11-14a'
SITE = 'https://stock-dashboard-dmfvhcig7brge7utl7et5r.streamlit.app/'
BOT = 'https://t.me/buza_alarm_bot'

# 신뢰 등급: g=실전 규칙(봇이 실제로 쓰는 것) · y=참고(검증 중·판단 보조) · k=사실(가공 없는 목록)
TAG_TXT = {'g': '실전 규칙', 'y': '참고', 'k': '사실'}
TAG_DESC = {'g': '자동매매 봇이 실제로 쓰는 규칙', 'y': '검증 중이거나 판단을 돕는 해석', 'k': '가공 없는 가격·재무·공시 목록'}

# (탭 이름, 답하는 질문, 한 줄 요약, [(기능, 등급)]) — 탭 이름은 dashboard._MAIN_TABS 와 글자까지 같아야 버튼이 작동한다
CAPS = [
    ("🏠 종합", "이번 주, 들어가도 되나?", "이번 주 시장 신호와 오늘 시장을 한 화면으로.", [
        ("이번 주 시장 신호 — 한국 지수 주봉 5주선 기준 신규 매수 가능/중지", 'g'),
        ("글로벌 마켓 14종 — 지수·환율·금리·원자재·비트코인·하이일드 스프레드", 'k'),
        ("시장 추세 판정(오닐 방식) · 한·미 대형주 상승 비율 30거래일", 'y'),
        ("오늘의 시장(한국·미국) — 시장 폭·업종(누르면 구성 종목)·52주 신고가·시총 상위", 'k'),
        ("매크로 국면 카드 · 시황 리포트 · 리포트에 질문하기", 'y')]),
    ("🌍 매크로", "왜 그렇게 판정했나?", "글로벌 돈의 흐름과 경기 국면.", [
        ("세계 증시 강도판 — 어느 시장이 가장 강한가", 'k'),
        ("축 1 돈의 흐름 · 축 2 경제(선행·동행)", 'y'),
        ("실전 판정 — 지금 돈을 움직이는 규칙은 이 칸뿐", 'g'),
        ("국면 지도(4계절·달걀) · 왜 이 계절인가 · 신호 성적표", 'y'),
        ("한국 수급·신용 · 정책금리·국채·수익률곡선·물가·유동성", 'k')]),
    ("🔎 종목 발굴", "그럼 뭘 살까?", "실전 규칙이 고른 이번 주 후보.", [
        ("실전 후보 — RS {rs_min} 이상 × 영업이익 흑자전환 × 주봉 5주선 위", 'g'),
        ("이번 주 매수 대상 — RS 높은 순 위 {slots}종", 'g'),
        ("재료 목록 — 상승 상위·52주 신고가·시총 상위·CANSLIM·이익가속·흑자전환·가치", 'k')]),
    ("🔍 종목 분석", "이 종목, 진짜 맞나?", "코드 입력(005930 · NVDA) → 결론 한 줄 → 원하는 축만.", [
        ("결론 한 줄 + 실전 규칙 대조(이익·RS·추세·시총·지수)", 'y'),
        ("수급(업종 온도 × 종목 RS) · 이익 방향(컨센서스·사이클 위치)", 'y'),
        ("가격(자기 과거 밴드·업종 대비) · 정체(유형·업종 내 순위) · 깨지는 조건·촉매", 'y'),
        ("매매 계획 — 손절가(고점 −{stop}%)·불타기 가격", 'g'),
        ("원자료 — 공식 재무제표·사업부문·사이클 비교·내부자 거래 · 텔레그램 감시 등록", 'k')]),
    ("🛡️ 내 포트폴리오", "내 계좌는 원칙대로인가?", "구글 로그인 후 내 계정에만 저장.", [
        ("보유 종목 입력 · 토스 연동 계좌는 불러오기", 'k'),
        ("손절선(보유 중 고점 −{stop}%)·종목 비중 상한({cap}%) 위반 점검", 'g'),
        ("위반 건수·등급 요약 · 텔레그램 봇 연결", 'k')]),
]

PRINCIPLES = [
    ('acc', "판정 → 후보 → 검증", "지수가 5주선 아래면 후보가 좋아 보여도 신규 매수를 쉽니다."),
    ('warn', "손절가를 먼저", "사기 전에 자를 가격부터. 기준은 진입가가 아니라 보유 중 고점 대비."),
    ('pos', "숫자는 확률", "점수·신호는 보장이 아니며 매수 권유가 아닙니다. '-' 는 오류가 아니라 '데이터 없음'."),
]

ROUTINES = [
    ("매일 아침 · 1분", "오늘 장이 지수만 오른 장인지 확인", [
        "텔레그램 @buza_alarm_bot 아침 요약을 받습니다",
        "🏠 종합 맨 위 '이번 주 시장 신호' — 신규 매수 가능/중지",
        "'오늘의 시장'(한국·미국 전환) — 시장 폭과 강한 업종이 지수와 같은 방향인지",
        "강한 업종 줄을 눌러 구성 종목을 봅니다"]),
    ("종목이 궁금할 때 · 5분", "후보를 의심하는 단계", [
        "🔍 종목 분석에 코드 입력(005930 · NVDA)",
        "결론 한 줄 → 실전 규칙 대조 줄을 먼저 읽습니다",
        "수급 → 이익 방향 → 가격 순으로 궁금한 축만 엽니다",
        "'매매 계획' 축의 손절가·불타기 가격을 적어 둡니다"]),
    ("주말 · 15분", "다음 주 계획 — 후보는 토요일에 갱신", [
        "🏠 종합 시황 리포트 — '다음 거래일에 볼 것'·숫자 조건",
        "🔎 종목 발굴 — 이번 주 후보와 들어온 이유(재료 목록과 대조)",
        "🛡️ 내 포트폴리오 — 손절선(고점 −{stop}%)·RS {rs_exit} 미만 탈락 확인",
        "월요일 시가 전, 종목별 손절가를 먼저 적습니다"]),
    ("월 1회 · 20분", "규칙이 아니라 국면을 점검", [
        "🌍 매크로 — 국면이 바뀌었나, '왜 이 계절인가'",
        "신호 성적표 — 매크로 신호가 실제로 시장을 이겼나",
        "내 성과를 코스피·코스닥과 같은 기간으로 비교합니다",
        "한 달 성적으로 규칙을 바꾸지 않습니다 — 바꾸려면 먼저 백테스트"]),
]

# (항목, 값 — {…} 는 RULE 에서 채움, 이유)
RULE_ROWS = [
    ("대상", "한국 상장 · 시총 {kr_mc}억원 이상", "유동성이 없는 종목은 백테스트 가격에 사고팔 수 없음"),
    ("후보 조건", "RS {rs_min} 이상 × 영업이익 흑자전환 × 주봉 종가 > {ma_weeks}주선",
     "이익이 막 돌아선 회사(펀더멘털)와 시장이 이미 사고 있는 회사(수급)의 교집합. 한쪽만으로는 시장을 일관되게 이기지 못함"),
    ("순서 · 보유", "RS 높은 순 · 동시 보유 {slots}종 · 종목당 목표 비중 계좌의 1/{slots}", "주도주를 넓게 맛보고 오르는 종목에 싣기 위함"),
    ("신규 매수 조건", "종목이 속한 지수(코스피/코스닥) 주봉이 {kr_ix_weeks}주선 위일 때만",
     "좋은 종목도 시장이 무너지면 같이 하락. 지수 게이트를 빼면 최대 낙폭이 크게 악화"),
    ("첫 매수 · 불타기", "목표 비중의 {first}% → {adds}",
     "맞은 종목에 더 싣는 쪽이 틀린 종목 물타기보다 나았음(리버모어·오닐 방식)"),
    ("손절", "보유 중 고점 대비 −{stop}% (진입가 대비 아님)",
     "진입가 기준이면 크게 오른 종목은 손절이 영영 안 걸림. −8% 같은 좁은 손절은 주도주가 흔들리는 폭보다 좁아 살아 있는 종목을 자름"),
    ("주도주 탈락 매도", "RS 가 {rs_exit} 아래로 떨어지면 매도", "칸을 약해진 종목이 차지하면 새 주도주를 못 삼"),
    ("종목 상한", "계좌의 {cap}% — 넘으면 상한까지 덜어냄", "한 종목이 계좌를 좌우하지 않게"),
]

# (항목, 출처, 워크플로 이름들 — cron 에서 시각을 읽는다 / 없으면 문자열 그대로, 한계)
DATA_ROWS = [
    ("가격 · 시총 · RS", "네이버 금융 · KRX(한국) / Yahoo Finance(미국)", ['daily-refresh'], "Yahoo 는 비공식 — 끊기면 빈칸"),
    ("한국 재무", "DART 원문 → 닿지 않으면 네이버 금융 기업분석으로 보충", ['weekly-profile'], "DART 가 해외 서버 접속을 자주 거부"),
    ("미국 재무", "SEC EDGAR 원문(10-Q · 10-K)", ['fin-daily'], "실적 발표 후 공시까지 1~3주"),
    ("실전 후보(주도주)", "위 가격 + 분기 재무", ['weekly-accel'], "금요일 종가 기준 — 주중에는 안 바뀜"),
    ("다음 주 계획표", "실전 후보 + 지수 5주선", ['live-plan'], "토요일 저녁 확정"),
    ("오늘의 시장 · 시황 리포트", "네이버 전 종목 시세 · 미국 시총 상위 500 · 문장은 AI 작성", ['market-report'], "숫자 조건은 규칙 계산, 문장만 AI"),
    ("종목 분석 결론(스냅샷)", "위 전부를 종목별로 묶음", ['snap'], "장 마감 후 1회"),
    ("한국 수급 · 신용", "네이버 금융", ['kr-flow'], "비공식 API"),
    ("매크로", "FRED(금리·물가·신용 스프레드) · Yahoo(VIX)", ['macro-long'], "FRED 는 하루 지연"),
    ("컨센서스", "네이버 금융(한국) · Yahoo(미국)", "주 1회(월요일)", "변화 이력은 2026-10 부터 축적"),
    ("업종 · 테마 분류", "네이버 테마(한국) · Yahoo 산업(미국)", ['sector-detail'], "공식 분류가 아닌 시장 통용 분류"),
    ("사업부문 구조 · 기업 개요", "공시 원문 → AI 추출", "조회 시", "AI 추출 — 원문 대조 권장"),
    ("백테스트 패널", "주봉 패널(상장폐지 포함 · 수정주가)", ['quant-panel'], "한국 분기 재무는 2018-06 부터"),
    ("정답 점검 · 화면 점검", "반드시 참인 사실(예: 삼성전자 매출 범위) 대조", ['keepalive'], "틀리면 그날 데이터를 되돌림"),
]

FLOW = [
    ("① 원천", ["가격·시총 — 네이버·KRX·Yahoo", "재무·공시 — DART·SEC EDGAR", "매크로·수급 — FRED·네이버"]),
    ("② 가공 · 점검", ["같은 숫자는 한 곳에서 계산(RS·YoY·PER)", "시장 판정도 한 곳에서", "매일 정답 점검 — 틀리면 되돌림"]),
    ("③ 화면", ["🏠 종합 — 들어가도 되나", "🔎 발굴 → 🔍 분석 — 뭘, 맞나", "🛡️ 내 포트폴리오 — 원칙대로인가"]),
    ("④ 실행 · 알림", ["토요일 계획표", "자동매매 봇(같은 규칙)", "텔레그램 @buza_alarm_bot"]),
]

METHOD = [
    ("사전 등록", "결과를 보기 전에 합격 기준을 저장소에 먼저 커밋. 기준을 사후에 바꾸지 않음."),
    ("학습 · 검증 분할", "앞 구간에서 고른 규칙을 뒤 구간에서 다시 측정. 한국에서 통과한 규칙은 미국(독립 표본)에서도 확인."),
    ("현실 반영", "상장폐지 종목 포함 · 수정주가 · 왕복 비용 0.3% · 주봉 종가 신호 → 다음 주 시가 체결."),
    ("성적이 나쁜 신호도 표시", "기각된 규칙은 지우지 않고 '참고·불합격'으로 남김."),
]
LIMITS = [
    "과거 성적은 미래를 보장하지 않습니다. 같은 기간에 규칙을 여러 번 시험하면 우연히 좋은 조합을 고를 위험(과적합)이 남습니다.",
    "한국 분기 재무가 2018-06 부터라 하락장 표본이 적습니다.",
    "실적이 아직 안 나온 '기대 선반영 랠리'는 흑자전환 조건으로 잡지 못합니다.",
    "손절은 하루 1회 판정 — 장중 급락 때는 −{stop}% 보다 깊게 체결될 수 있습니다.",
    "백테스트는 주봉 체결 가정 — 소액 계좌의 정수 주문·호가 차이는 반영되지 않습니다.",
    "가격은 전일 종가 기준입니다. 실시간 시세가 아닙니다.",
]

# 해보고 버린 것 (시기, 시도, 결과)
DROPPED = [
    ("2026-11", "미국에 같은 규칙 적용", "S&P500(배당 포함)에 못 미침 → 실전은 한국 단독"),
    ("2026-11", "지수 신호로 현금 비중 확대(96조합)", "합격 0 — 낙폭 개선보다 수익 손실이 큼. 방어는 종목 손절이 이미 수행"),
    ("2026-11", "과열 고점(클라이맥스) 매도", "검증 구간에서 악화 — 과열은 고점이 아니라 변동성 확대"),
    ("2026-11", "손절 후 무조건 재매수 · 월 1회 매수 · 52주 신고가 주에만 매수", "셋 다 불합격(신고가 필터는 미국에서 재현 안 됨)"),
    ("2026-11", "RS 변화·가속 지표(8종)", "전부 불합격 — RS 수준 자체가 가장 나음"),
    ("2026-10", "사이클 국면으로 비중 조절", "4계절·경고 3종 모두 비중 규칙으로는 통과 못 함 → 표시만"),
    ("2026-10", "이긴 종목에 좁은 추적 손절", "측정한 모든 폭에서 안 파는 것보다 나쁨 → 고점 −20% + RS 탈락으로 정리"),
    ("2026-09", "급등 + 거래량 규칙", "대상승의 출발점을 못 잡아 폐기"),
]

GLOSSARY = [
    ("RS(상대강도)", "3개월 수익률 40% + 6·9·12개월 각 20% 가중 수익률의 시장 내 백분위(0~100). 높을수록 시장보다 강했음."),
    ("5주선", "최근 5주 주봉 종가 평균. 지수가 이 아래면 신규 매수를 쉼."),
    ("흑자전환", "이번 분기 영업이익 흑자 + 전년 같은 분기 적자. 그래서 영업익YoY 는 정의되지 않아 '-'."),
    ("불타기", "오른 종목에 추가 매수. 내린 종목에 더 사는 물타기의 반대."),
    ("시장 폭", "오른 종목 수 vs 내린 종목 수. 지수가 올라도 오른 종목이 적으면 소수 대형주 장세."),
    ("분배일 · 팔로스루", "오닐 방식 추세 판정. 거래량이 늘며 지수가 내린 날(분배일)이 쌓이면 약세, 반등 시도 뒤 강한 상승일(팔로스루)이 나오면 추세 전환."),
    ("업종 온도", "같은 업종 종목들의 RS 중앙값 순위. 업종 전체에 돈이 들어오는지."),
    ("사이클 위치", "이익률이 그 회사 과거 분포에서 몇 번째 백분위인지. 천장권이면 좋아 보이는 실적이 정점일 수 있음."),
    ("하이일드 스프레드", "투기등급 회사채 금리 − 국채 금리. 벌어지면 시장이 부도 위험을 크게 본다는 뜻."),
    ("최대 낙폭(MDD)", "고점에서 저점까지 가장 크게 빠진 폭."),
    ("'-'", "오류가 아니라 그 종목에 그 데이터가 없다는 뜻. 없는 값을 추정해 채우지 않음."),
]

DISCLAIMER = ("정보 도구이며 투자 권유가 아닙니다 · 모든 백테스트 수치는 과거 성적이며 실현 수익이 아닙니다 · "
              "운영자는 화면에 나온 종목을 보유하고 있을 수 있습니다")

# 공개 문서에 나오면 안 되는 말 — tests/test_manual.py
FORBIDDEN = ['차니', '박찬의', '오버라이드', '노트북', '30만', '100만원', '경영실', '연구실', '허용 IP', 'ledger']


# ── 자동 원천 ──────────────────────────────────────────────────────────
def rule() -> dict:
    """live/plan.py 의 RULE 을 import 없이 읽는다(그 모듈은 pandas·원장을 건드린다)."""
    try:
        tree = ast.parse((ROOT / 'live' / 'plan.py').read_text(encoding='utf-8'))
        for n in tree.body:
            if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') == 'RULE':
                return {k.arg: ast.literal_eval(k.value) for k in n.value.keywords}
    except Exception:
        pass
    return {}


def _n(x) -> str:
    """0.5 → '50', 0.2 → '20' (퍼센트 정수)."""
    return f"{x * 100:.0f}"


def ctx() -> dict:
    r = rule()
    if not r:
        return dict(rs_min='-', slots='-', stop='-', cap='-', rs_exit='-', first='-', adds='-', kr_mc='-', ma_weeks='-', kr_ix_weeks='-')
    adds = ' · '.join(f"+{_n(a)}%" for a, _ in r['add_steps'])
    sz = {_n(b) for _, b in r['add_steps']}
    adds += f"에서 {sz.pop()}%씩 추가" if len(sz) == 1 else "에서 추가"
    return dict(rs_min=r['rs_min'], slots=r['slots'], stop=_n(r['stop']), cap=_n(r['cap']), rs_exit=r['rs_exit'],
                first=_n(r['first']), adds=adds, kr_mc=f"{r['kr_min_mc'] / 1e8:,.0f}", ma_weeks=r['ma_weeks'],
                kr_ix_weeks=r['kr_ix_weeks'])


def _f(s: str, c: dict | None = None) -> str:
    try:
        return s.format(**(c or ctx()))
    except Exception:
        return s


def caps() -> list:
    c = ctx()
    return [(t, q, _f(d, c), [(_f(x, c), g) for x, g in feats]) for t, q, d, feats in CAPS]


def routines() -> list:
    c = ctx()
    return [(w, why, [_f(s, c) for s in steps]) for w, why, steps in ROUTINES]


def backtest() -> dict:
    try:
        return json.loads((ROOT / 'results' / 'v19_bt.json').read_text(encoding='utf-8'))
    except Exception:
        return {}


_DOW = ['일', '월', '화', '수', '목', '금', '토']


def _dows(spec: str) -> set:
    if spec == '*':
        return set(range(7))
    out = set()
    for part in spec.split(','):
        if '-' in part:
            a, b = part.split('-')
            out |= set(range(int(a), int(b) + 1))
        else:
            out.add(int(part) % 7)
    return out


def _dow_txt(d: set) -> str:
    if len(d) == 7:
        return '매일'
    if d == {1, 2, 3, 4, 5}:
        return '평일'
    s = sorted(d)
    if len(s) > 2 and s == list(range(s[0], s[-1] + 1)):
        return f"{_DOW[s[0]]}~{_DOW[s[-1]]}"
    return '·'.join(_DOW[i] for i in s)


def cron_kst(expr: str) -> str:
    """'30 21 * * 0-4'(UTC) → '평일 06:30'. 날짜 조건(첫 주 등)은 '월 1회'로만."""
    p = expr.split()
    if len(p) != 5:
        return expr
    m, h, dom, _mon, dow = p
    if '/' in h:
        return f"{h.split('/')[1]}시간마다"
    hours = [int(x) for x in h.split(',')]
    if len(hours) > 2:
        return f"하루 {len(hours)}회"
    days = _dows(dow)
    out = []
    for hh in hours:
        k = hh + 9
        d = {(x + 1) % 7 for x in days} if k >= 24 else days
        pre = '월 1회 ' if dom != '*' else ''
        out.append(f"{pre}{_dow_txt(d)} {k % 24:02d}:{int(m):02d}")
    return ' · '.join(out)


def schedule(names) -> str:
    """워크플로 이름들 → KST 갱신 시각. 문자열이면 그대로."""
    if isinstance(names, str):
        return names
    out = []
    for n in names:
        try:
            src = (ROOT / '.github' / 'workflows' / f'{n}.yml').read_text(encoding='utf-8')
        except Exception:
            continue
        for e in re.findall(r"cron:\s*'([^']+)'", src):
            t = cron_kst(e)
            if t not in out:
                out.append(t)
    return ' · '.join(out) if out else '수시'


def notes(limit: int | None = None) -> list:
    try:
        rows = json.loads((ROOT / 'docs' / 'release_notes.json').read_text(encoding='utf-8'))
        rows = sorted(rows, key=lambda r: r.get('date', ''), reverse=True)
        return rows[:limit] if limit else rows
    except Exception:
        return []


def updated() -> str:
    n = notes(1)
    return n[0]['date'] if n else '-'


# ── HTML 조각 (화면 st.html 과 PDF 가 같이 쓴다) ─────────────────────────
def _e(x) -> str:
    return html.escape(str(x if x is not None else '-'))


CSS = """
<style>
  .mn { font-family:'Pretendard',-apple-system,'Malgun Gothic','Noto Sans CJK KR',system-ui,sans-serif; color:var(--ink); }
  .mn, .mn * { word-break:keep-all; overflow-wrap:anywhere; box-sizing:border-box; }
  .mn-lead { font-size:13px; color:var(--ink-2); line-height:1.6; margin:0 2px 10px; }
  .mn-h { display:flex; align-items:baseline; gap:10px; margin:2px 2px 8px; }
  .mn-h b { font-size:15px; font-weight:750; letter-spacing:-.02em; }
  .mn-h span { font-size:12px; color:var(--ink-3); }
  .mn-grid { display:grid; gap:10px; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); }
  .mn-card { border:1px solid var(--line); border-radius:10px; background:var(--surface); padding:12px 14px; }
  .mn-card .k { font-size:11px; font-weight:700; letter-spacing:.06em; color:var(--ink-3); }
  .mn-card .t { font-size:14px; font-weight:750; letter-spacing:-.02em; margin:1px 0 4px; }
  .mn-card .q { font-size:12px; color:var(--accent); font-weight:650; margin-bottom:6px; }
  .mn-card p, .mn-card li { font-size:12.5px; color:var(--ink-2); line-height:1.6; margin:0; }
  .mn-card ul, .mn-card ol { margin:0; padding-left:16px; }
  .mn-card.acc { border-left:4px solid var(--accent); } .mn-card.warn { border-left:4px solid var(--warn); }
  .mn-card.pos { border-left:4px solid var(--pos); }
  .mn-big { font-size:22px; font-weight:800; letter-spacing:-.03em; font-variant-numeric:tabular-nums; }
  .mn-big small { font-size:12px; font-weight:600; color:var(--ink-3); margin-left:4px; }
  .mn-tag { display:inline-block; font-size:10.5px; font-weight:700; padding:0 6px; border-radius:999px; margin-left:4px; vertical-align:1px; white-space:nowrap; }
  .mn-tag.g { background:var(--pos-bg); color:var(--pos); } .mn-tag.y { background:var(--warn-bg); color:var(--warn); }
  .mn-tag.k { background:var(--line-2); color:var(--ink-2); }
  .mn-tbl { width:100%; border-collapse:collapse; background:var(--surface); border:1px solid var(--line); border-radius:10px; overflow:hidden; font-size:12.5px; }
  .mn-tbl th { text-align:left; font-size:11.5px; font-weight:700; color:var(--ink-3); background:var(--line-2); padding:6px 10px; white-space:nowrap; }
  .mn-tbl td { padding:6px 10px; border-top:1px solid var(--line-2); vertical-align:top; color:var(--ink-2); line-height:1.55; }
  .mn-tbl td:first-child { font-weight:700; color:var(--ink); white-space:nowrap; }
  .mn-tbl td.f { font-weight:400 !important; white-space:normal !important; color:var(--ink-2) !important; }
  .mn-tbl td.nw:last-child { width:1%; }
  @media (min-width:900px) { .mn-tour { min-height:308px; } }
  .mn-tbl td.v { color:var(--ink); } .mn-tbl td.nw { white-space:nowrap; font-variant-numeric:tabular-nums; }
  .mn-wrap { overflow-x:auto; }
  .mn-flow { display:grid; grid-template-columns:repeat(4,minmax(150px,1fr)); gap:8px; }
  .mn-flow .mn-card { position:relative; }
  @media (max-width:720px) { .mn-flow { grid-template-columns:repeat(2,minmax(0,1fr)); } .mn-tbl td:first-child { white-space:normal; } }
  .mn-src { font-size:11.5px; color:var(--ink-3); margin:6px 2px 0; line-height:1.6; }
  .mn-gap { height:14px; }
</style>
"""


def _tag(g: str) -> str:
    return f'<span class="mn-tag {g}">{TAG_TXT[g]}</span>'


def _legend() -> str:
    return ' · '.join(f'{_tag(g)} {_e(TAG_DESC[g])}' for g in 'gyk')


def _table(head, rows, cls=None) -> str:
    cls = cls or {}
    th = ''.join(f'<th>{_e(h)}</th>' for h in head)
    tr = ''.join('<tr>' + ''.join(f'<td class="{cls.get(i, "")}">{c}</td>' for i, c in enumerate(r)) + '</tr>' for r in rows)
    return f'<div class="mn-wrap"><table class="mn-tbl"><tr>{th}</tr>{tr}</table></div>'


def sec_overview() -> str:
    flow = ''.join(f"""<div class="mn-card"><div class="k">{_e(k)}</div><ul>{''.join(f'<li>{_e(x)}</li>' for x in xs)}</ul></div>"""
                   for k, xs in FLOW)
    pr = ''.join(f'<div class="mn-card {c}"><div class="t">{_e(t)}</div><p>{_e(d)}</p></div>' for c, t, d in PRINCIPLES)
    return f"""<div class="mn-lead">공식 공시(DART · SEC EDGAR)와 시장 가격을 매일 자동으로 모아 <b>지금 들어가도 되나 · 뭘 살까 · 얼마에 자를까</b>를
      숫자로 답하는 리서치 도구입니다. 화면에 보이는 것과 같은 규칙(실전 v1.9 — 한국)으로 운영자의 자동매매 봇이 실제 계좌를 굴립니다.</div>
      <div class="mn-h"><b>데이터가 화면까지 오는 길</b><span>화면 · 백테스트 · 봇이 같은 정의를 씁니다</span></div>
      <div class="mn-flow">{flow}</div><div class="mn-gap"></div>
      <div class="mn-h"><b>지키는 원칙</b><span>도구보다 먼저</span></div><div class="mn-grid">{pr}</div>
      <div class="mn-src">신뢰 등급 — {_legend()}</div>"""


def sec_features() -> str:
    out = []
    for t, q, d, feats in caps():
        rows = [((f"<b style='color:var(--ink)'>{_e(f.split(' — ')[0])}</b> — {_e(f.split(' — ', 1)[1])}" if ' — ' in f else
                  f"<b style='color:var(--ink)'>{_e(f)}</b>"), _tag(g)) for f, g in feats]
        out.append(f'<div class="mn-h"><b>{_e(t)}</b><span>{_e(q)} {_e(d)}</span></div>'
                   + _table(['기능', '등급'], rows, {0: 'f', 1: 'nw'}) + '<div class="mn-gap"></div>')
    return ''.join(out) + f'<div class="mn-src">{_legend()}</div>'


def sec_routines() -> str:
    cards = ''.join(f"""<div class="mn-card acc"><div class="k">{_e(w)}</div><div class="q">{_e(why)}</div>
        <ol>{''.join(f'<li>{_e(s)}</li>' for s in steps)}</ol></div>""" for w, why, steps in routines())
    return f'<div class="mn-grid" style="grid-template-columns:repeat(auto-fit,minmax(240px,1fr))">{cards}</div>'


def sec_rules() -> str:
    c, b = ctx(), backtest()
    kpi = ''
    if b:
        kpi = f"""<div class="mn-grid" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr))">
          <div class="mn-card"><div class="k">연 수익률 (백테스트)</div><div class="mn-big">{b.get('CAGR', '-')}%<small>코스피 {b.get('BM_CAGR', '-')}%</small></div></div>
          <div class="mn-card"><div class="k">최대 낙폭</div><div class="mn-big">{b.get('MDD', '-')}%<small>코스피 {b.get('BM_MDD', '-')}%</small></div></div>
          <div class="mn-card"><div class="k">매도 건수 · 이긴 비율</div><div class="mn-big">{b.get('sells', '-')}<small>건 · {b.get('win', '-')}%</small></div></div>
          <div class="mn-card"><div class="k">측정 기간</div><div class="mn-big" style="font-size:16px;line-height:1.9">{_e(b.get('start'))} ~ {_e(b.get('end'))}</div></div>
        </div><div class="mn-src">백테스트 {_e(b.get('run'))} 측정 · 상장폐지 포함 · 수정주가 · 주봉 체결 · 비용 0.3% · 과거 성적이며 실현 수익이 아닙니다.
          이긴 비율이 낮아도 수익이 나는 구조 — 작게 여러 번 잃고 소수 주도주에서 크게 법니다.</div><div class="mn-gap"></div>"""
    rows = [(_e(k), _e(_f(v, c)), _e(_f(w, c))) for k, v, w in RULE_ROWS]
    return kpi + _table(['항목', '규칙', '왜'], rows, {1: 'v'}) + \
        '<div class="mn-src">규칙 값은 봇이 읽는 설정에서 그대로 가져옵니다 — 규칙이 바뀌면 이 표도 같이 바뀝니다.</div>'


def sec_data() -> str:
    rows = [(_e(k), _e(src), _e(schedule(wf)), _e(lim)) for k, src, wf, lim in DATA_ROWS]
    return ('<div class="mn-lead">전부 무료·공개 원천입니다. 시각은 한국 시간(KST). 모든 표 바로 아래에 <b>출처 · 마지막 갱신</b>이 붙습니다.</div>'
            + _table(['항목', '출처', '갱신(KST)', '한계'], rows, {1: 'v', 2: 'nw'})
            + '<div class="mn-src">갱신 시각은 실제 예약 실행 설정에서 읽어 옵니다. 예약 실행은 몇 분~수십 분 늦을 수 있습니다.</div>')


def sec_method() -> str:
    c = ctx()
    m = ''.join(f'<div class="mn-card"><div class="t">{_e(t)}</div><p>{_e(d)}</p></div>' for t, d in METHOD)
    lim = ''.join(f'<li>{_e(_f(x, c))}</li>' for x in LIMITS)
    rows = [(_e(a), _e(b), _e(r)) for a, b, r in DROPPED]
    return f"""<div class="mn-h"><b>규칙을 고르는 방법</b><span>규칙을 바꾸려면 이 절차를 통과해야 합니다</span></div>
      <div class="mn-grid">{m}</div><div class="mn-gap"></div>
      <div class="mn-h"><b>알고 써야 할 한계</b></div><div class="mn-card warn"><ul>{lim}</ul></div><div class="mn-gap"></div>
      <div class="mn-h"><b>해보고 버린 것</b><span>잘 된 것만 보여주지 않습니다</span></div>
      {_table(['시기', '시도', '결과'], rows, {1: 'v'})}"""


def sec_glossary() -> str:
    return _table(['용어', '뜻'], [(_e(k), _e(v)) for k, v in GLOSSARY])


def sec_notes(limit: int | None = 20) -> str:
    rows = [(_e(r.get('date')), _e(r.get('area')), _e(r.get('text'))) for r in notes(limit)]
    if not rows:
        return '<div class="mn-lead">기록 없음.</div>'
    return _table(['날짜', '화면', '바뀐 것'], rows, {0: 'nw', 2: 'v'}) + \
        '<div class="mn-src">화면이 바뀌는 작업마다 한 줄씩 추가됩니다.</div>'


# (id, 제목, 한 줄, 함수) — 화면 하위 탭과 PDF 목차가 같은 순서
SECTIONS = [
    ('overview', '개요', '무엇을 하는 도구인가 · 데이터가 화면까지 오는 길', sec_overview),
    ('features', '탭별 기능', '다섯 탭이 답하는 질문과 기능 전부', sec_features),
    ('routines', '활용 루틴', '시간대별로 무엇을 보면 되나', sec_routines),
    ('rules', '실전 규칙', '봇이 실제로 쓰는 규칙과 그 이유', sec_rules),
    ('data', '데이터 · 갱신', '숫자의 출처와 갱신 시각 · 한계', sec_data),
    ('method', '검증 · 한계', '규칙을 고르는 방법 · 해보고 버린 것', sec_method),
    ('glossary', '용어', '화면에 나오는 말', sec_glossary),
    ('notes', '개선 내역', '최근 바뀐 것', sec_notes),
]

_VARS = """:root{--ink:#111827;--ink-2:#374151;--ink-3:#4B5563;--line:#E5E7EB;--line-2:#F3F4F6;--surface:#FFFFFF;
--accent:#2453C8;--accent-2:#EEF3FF;--pos:#15803D;--pos-bg:#DCFCE7;--neg:#DC2626;--neg-bg:#FEE2E2;--warn:#B45309;--warn-bg:#FEF3C7;}"""


def build_html(font_url: str | None = None) -> str:
    """PDF·인쇄용 단독 문서(A4 세로). 화면과 같은 조각을 순서대로 이어 붙인다."""
    font = (f"@font-face{{font-family:'Pretendard';src:url('{font_url}') format('woff2');font-weight:100 900;}}" if font_url else '')
    toc = ''.join(f'<li><b>{_e(t)}</b> — {_e(d)}</li>' for _i, t, d, _fn in SECTIONS)
    body = ''.join(f"""<section><div class="pg-h"><span>{i:02d}</span><h2>{_e(t)}</h2><em>{_e(d)}</em></div>
        {fn(None) if sid == 'notes' else fn()}</section>""" for i, (sid, t, d, fn) in enumerate(SECTIONS, 1))
    b = backtest()
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><title>STOCK DASHBOARD 사용설명서</title>
<style>{font}{_VARS}
@page{{size:A4;margin:14mm 13mm 15mm}}
body{{margin:0;background:#fff;font-family:'Pretendard','Noto Sans CJK KR','Malgun Gothic',sans-serif;color:var(--ink);
  -webkit-print-color-adjust:exact;print-color-adjust:exact}}
.cover{{page-break-after:always;padding-top:38mm}}
.cover .kick{{font-size:12px;font-weight:700;letter-spacing:.16em;color:var(--accent)}}
.cover h1{{font-size:38px;letter-spacing:-.04em;margin:10px 0 8px;line-height:1.2}}
.cover p{{font-size:14px;color:var(--ink-2);line-height:1.7;max-width:150mm}}
.cover ol{{margin:26px 0 0;padding-left:20px;font-size:13px;line-height:2;color:var(--ink-2)}}
.cover .meta{{margin-top:30px;font-size:12px;color:var(--ink-3);line-height:1.8;border-top:1px solid var(--line);padding-top:12px}}
section{{page-break-before:always}} section:first-of-type{{page-break-before:auto}}
.pg-h{{display:flex;align-items:baseline;gap:10px;border-bottom:2px solid var(--ink);padding-bottom:6px;margin-bottom:14px}}
.pg-h span{{font-size:12px;font-weight:800;color:var(--accent)}} .pg-h h2{{font-size:20px;margin:0;letter-spacing:-.03em}}
.pg-h em{{font-style:normal;font-size:12px;color:var(--ink-3)}}
.mn-tbl tr,.mn-card{{page-break-inside:avoid}} .mn-h{{page-break-after:avoid}}
.mn-flow{{grid-template-columns:repeat(4,1fr)!important}}
.foot{{margin-top:18px;font-size:11px;color:var(--ink-3);line-height:1.7;border-top:1px solid var(--line);padding-top:8px}}
</style>{CSS}</head><body><div class="mn">
<div class="cover"><div class="kick">STOCK DASHBOARD · 사용설명서</div>
<h1>시장 → 종목 → 내 계좌,<br>위에서 아래로 좁혀 갑니다</h1>
<p>공식 공시와 시장 가격으로 <b>지금 들어가도 되나 · 뭘 살까 · 얼마에 자를까</b>를 숫자로 답하는 리서치 도구.
실전 규칙 v1.9(한국) 백테스트 연 {b.get('CAGR', '-')}% · 최대 낙폭 {b.get('MDD', '-')}% (같은 기간 코스피 {b.get('BM_CAGR', '-')}% · {b.get('BM_MDD', '-')}%).</p>
<ol>{toc}</ol>
<div class="meta">최근 개선 {_e(updated())} · 이 문서는 화면의 '📘 사용법 → 전체 설명서'와 같은 원천에서 자동으로 만들어집니다.<br>
사이트 {SITE}<br>텔레그램 {BOT}</div></div>
{body}
<div class="foot">{_e(DISCLAIMER)}</div></div></body></html>"""


if __name__ == '__main__':
    # python manual.py → docs/manual.html (글꼴은 상대 경로 — docs/ 에서 열어야 한다). PDF 는 tools/build_manual_pdf.sh
    out = ROOT / 'docs' / 'manual.html'
    out.write_text(build_html('../static/fonts/PretendardVariable.woff2'), encoding='utf-8')
    print(f'wrote {out} ({out.stat().st_size:,} bytes)')
