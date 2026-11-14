# -*- coding: utf-8 -*-
"""📘 사용법·전체 설명서의 단일 원천 (2026-11-14).

화면 '사용법' 패널(한눈에 · 활용 루틴 · 전체 설명서)과 PDF(docs/manual.pdf)가 전부 이 파일에서 나온다.
2026-11-15 2차: 공개 = 한눈에(무엇) · 활용 루틴(언제·어떻게) · 전체 설명서(실전 규칙 · 데이터 · 텔레그램 봇 — 왜 믿나).
  개선 내역 · 검증·한계는 비공개(경영실, INTERNAL) · 용어 절과 '지키는 원칙' 카드는 삭제.
같은 내용을 두 곳에 쓰지 않는다 — 옛 GUIDE.md 는 화면이 바뀔 때마다 낡았다('검은 배너'·'이번 주 할 일'·'12종 카드').

자동으로 따라오는 것(손으로 안 고친다):
  · 실전 규칙 값        ← live/plan.py RULE
  · 백테스트 숫자       ← results/v19_bt.json
  · 갱신 시각           ← .github/workflows/*.yml cron(UTC → KST)
  · 데이터 마지막 갱신   ← data_freshness.statuses()(파일 안의 날짜, 화면에서만 — PDF 는 주기만)
  · 개선 내역(비공개)   ← docs/release_notes.json (화면이 바뀌는 작업마다 한 줄 — CLAUDE.md 규칙)
  · PDF                 ← manual-pdf 워크플로가 위 파일이 바뀔 때마다 다시 만든다
손으로 고치는 것: 아래 LEAD·CAPS·ROUTINES·DATA_FLOW·BOT_CMDS·DROPPED 문구. 고치면 화면·PDF 가 같이 바뀐다.

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
VERSION = '2026-11-16c'
SITE = 'https://stock-dashboard-dmfvhcig7brge7utl7et5r.streamlit.app/'
BOT = 'https://t.me/buza_alarm_bot'

# 신뢰 등급: g=실전 규칙(봇이 실제로 쓰는 것) · y=참고(검증 중·판단 보조) · k=사실(가공 없는 목록)
TAG_TXT = {'g': '실전 규칙', 'y': '참고', 'k': '사실'}
TAG_DESC = {'g': '자동매매 봇이 실제로 쓰는 규칙', 'y': '검증 중이거나 판단을 돕는 해석', 'k': '가공 없는 가격·재무·공시 목록'}

# 첫 문장 = 이 사이트가 하는 일 전부(실전 규칙 한 줄). 기능 나열이 아니라 규칙을 먼저 말한다 — 2026-11-15.
LEAD = "지수가 {kr_ix_weeks}주선 위일 때만, 이익이 막 흑자로 돌아선 주도주를 사고, 보유 중 고점에서 −{stop}% 빠지면 판다."
LEAD_SUB = ("이 한 줄을 매일 공식 공시(DART · SEC EDGAR)와 시장 가격으로 다시 계산해, 시장 → 종목 → 내 계좌 순서로 다섯 탭에 펼쳤습니다. "
            "운영자도 이 규칙(실전 v1.9 · 한국) 그대로 매매합니다.")

# (탭 이름, 답하는 질문, 한 줄 요약, [(기능, 등급)]) — 탭 이름은 dashboard._MAIN_TABS 와 글자까지 같아야 버튼이 작동한다
CAPS = [
    ("🏠 종합", "이번 주, 들어가도 되나?", "이번 주 시장 신호와 오늘 시장을 한 화면으로.", [
        ("이번 주 시장 신호 — 한국 지수 주봉 5주선 기준 신규 매수 가능/중지", 'g'),
        ("글로벌 마켓 14종 — 일·주·월 등락 전환 · 3개월 추이선", 'k'),
        ("시장 추세 판정(오닐 방식) · 주간 52주 신고가·신저가 · 한·미 대형주 상승 비율", 'y'),
        ("오늘의 시장(한국·미국 × 일·주·월) — 시장 폭·수급·업종(누르면 구성 종목)·테마·52주 신고가·히트맵", 'k'),
        ("매크로 국면 카드 · 시황 리포트(한·미 같은 양식) · 다가오는 일정", 'y')]),
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
        ("펀더멘탈 — 기업 개요·사업부문·이익 방향·재무제표·컨센서스 추세·밸류에이션·희석", 'y'),
        ("히스토리 — 차트(선형/로그·사이클 구간 색)·사이클·낙폭·멀티플 밴드·정류장", 'y'),
        ("수급 — 업종 온도 × 종목 RS·업종 내 순위·동종업계·내부자 거래", 'y'),
        ("깨지는 조건 — 결론 아래 체크(손절 고점 −{stop}%는 실전 봇 규칙)", 'k')]),
    ("🛡️ 내 포트폴리오", "산 뒤에, 원칙대로 지키고 있나?", "보유 종목을 넣으면 손절선·비중을 대신 셉니다.", [
        ("보유 종목 입력 · 토스 연동 계좌는 불러오기", 'k'),
        ("손절선(보유 중 고점 −{stop}%)·종목 비중 상한({cap}%) 위반 점검", 'g'),
        ("위반 건수·등급 요약 · 텔레그램 봇 연결", 'k')]),
]

# 규칙의 실제 리듬: 금요일 종가로 판정 → 토요일 계획 → 월요일 시가 매수 · 평일엔 가진 종목 손절만. 2026-11-15 재작성.
ROUTINES = [
    ("주 1회 · 토요일", "다음 주에 살 것 정하기", [
        "🏠 종합 — 이번 주 시장 신호. 중지면 여기서 끝",
        "🔎 종목 발굴 — 매수 대상 {slots}종(RS 높은 순)",
        "🔍 종목 분석 — 실전 규칙 대조 줄이 전부 ✓인지",
        "매수 전에 손절가(고점 −{stop}%)부터 적기"]),
    ("평일 · 장 마감 뒤", "가진 종목만 본다", [
        "📲 /market — 오늘 장 시황 카드",
        "🛡️ 내 포트폴리오 — 손절선에 닿은 종목",
        "RS {rs_exit} 아래로 내려간 종목",
        "걸린 종목은 다음 거래일에 정리"]),
    ("눈에 띈 종목이 있을 때", "결론 먼저, 근거는 필요한 만큼", [
        "🔍 코드 입력(005930 · NVDA) → 결론 한 줄",
        "대조 줄에 ✗ 가 하나라도 있으면 후보 아님",
        "근거는 펀더멘탈 · 히스토리 · 수급 탭에서 필요한 것만",
        "📲 /watch 종목 — 공시·중요 뉴스 알림"]),
    ("분기 1회 · 실적 시즌", "후보가 바뀌는 때", [
        "실적 발표 뒤 흑자전환 종목이 새로 들어옴",
        "🌍 매크로 — 국면이 바뀌었나",
        "신호 성적표 — 매크로 신호가 실제로 맞았나",
        "규칙은 그대로. 바꾸려면 백테스트 먼저"]),
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

# 데이터 워크플로(2026-11-15): 출처 → 항목 → 주기(워크플로 cron) → 마지막 갱신(data_freshness 의 파일 안 날짜).
# (출처, [(항목, 워크플로 이름들 또는 주기 문자열, data_freshness 경로 또는 None, 한계)])
DATA_FLOW = [
    ("네이버 금융 · KRX", [
        ("한국 가격 · 시총 · RS", ['daily-refresh'], 'results/screener_latest.json', ""),
        ("한국 수급 · 신용", ['kr-flow'], 'results/kr_flow.json', "비공식 API"),
        ("한국 컨센서스", "주 1회(월요일)", 'results/consensus_history.jsonl', ""),
        ("한국 분기 재무 보충", ['weekly-profile'], 'data/kr_fundamentals_q.parquet', "DART 가 닿지 않을 때"),
        ("업종 · 테마", ['sector-detail'], 'data/sector_detail.json', "시장 통용 분류"),
    ]),
    ("DART (한국 공시)", [
        ("한국 재무 원문", ['weekly-profile'], 'results/value_kr.json', "해외 서버 접속을 자주 거부"),
    ]),
    ("SEC EDGAR (미국 공시)", [
        ("미국 재무 · 주식수", ['fin-daily'], 'data/us_shares.csv', "실적 발표 후 공시까지 1~3주"),
    ]),
    ("Yahoo Finance", [
        ("미국 가격 · 시총", ['daily-refresh'], 'data/us_marketcap.csv', "비공식 — 끊기면 빈칸"),
    ]),
    ("FRED (미 연준)", [
        ("금리 · 물가 · 신용 스프레드", ['macro-long'], 'data/research/macro_long_fred.parquet', "하루 지연"),
    ]),
    ("자체 계산 (위 원천을 가공)", [
        ("실전 후보(주도주)", "주 1회(토요일)", 'results/leaders_accel.json', "금요일 종가 기준"),
        ("다음 주 계획표", ['live-plan'], 'live/plan_latest.json', "토요일 저녁 확정"),
        ("시황 리포트", ['market-report'], 'results/market_report.json', "숫자는 규칙 계산, 문장만 AI"),
        ("공통 재무 (매출·영업익 YoY·PER)", ['snap'], 'results/fund_snapshot.json', ""),
    ]),
]

# 텔레그램 봇 — 부자알람(@buza_alarm_bot). 문구는 buza-bot bot.py WELCOME 과 맞춘다.
BOT_CMDS = [
    ("📊 /market", "장 마감 시황 카드 — 한국 16:00 무렵 · 미국 다음 날 아침. /market on 이면 자동으로 받음"),
    ("📰 /watch 종목", "공시는 나오는 즉시, 중요한 뉴스는 08·20시에 요약. 중요한 게 없으면 보내지 않음 · 한국은 수급 포함"),
    ("🔍 /dashboard 종목", "이 사이트 종목 분석의 결론을 카드 한 장으로"),
    ("📑 /report 티커", "회사 개요·사업부문·재무 추이·밸류·경쟁사 심층 리포트"),
    ("🎬 유튜브 링크", "붙여넣으면 요약 · /add 채널 주소로 새 영상 자동 요약"),
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


def lead() -> str:
    return _f(LEAD)


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
  .mn-tbl td.v { color:var(--ink); } .mn-tbl td.nw { white-space:nowrap; font-variant-numeric:tabular-nums; }
  .mn-wrap { overflow-x:auto; }
  .mn-flow { display:grid; grid-template-columns:repeat(4,minmax(150px,1fr)); gap:8px; }
  .mn-flow .mn-card { position:relative; }
  @media (max-width:720px) { .mn-flow { grid-template-columns:repeat(2,minmax(0,1fr)); } .mn-tbl td:first-child { white-space:normal; } }
  .mn-src { font-size:11.5px; color:var(--ink-3); margin:6px 2px 0; line-height:1.6; }
  .mn-gap { height:14px; }
  .mn-df { display:grid; grid-template-columns:minmax(120px,170px) 1fr; gap:0 10px; border:1px solid var(--line); border-radius:10px;
           background:var(--surface); padding:8px 12px; margin-bottom:8px; }
  .mn-df-src { font-size:13px; font-weight:750; color:var(--ink); padding-top:6px; border-right:2px solid var(--accent-2); }
  .mn-df-row { display:grid; grid-template-columns:14px minmax(180px,300px) 14px minmax(110px,190px) 14px auto; justify-content:start;
               align-items:center; gap:4px 8px; padding:5px 0; border-top:1px dashed var(--line-2); }
  .mn-df-row:first-child { border-top:0; }
  .mn-df-it { font-size:12.5px; } .mn-df-it b { font-weight:650; color:var(--ink); }
  .mn-df-it small, .mn-df-row small { display:block; font-size:11px; color:var(--ink-3); }
  .mn-df-cy { font-size:12px; color:var(--ink-2); font-variant-numeric:tabular-nums; }
  .mn-df-row > span:last-child small { display:inline; margin-left:6px; }
  .mn-ar { color:var(--ink-3); font-size:12px; }
  .mn-st { font-size:11.5px; font-weight:700; padding:1px 8px; border-radius:999px; font-variant-numeric:tabular-nums; white-space:nowrap; }
  .mn-st.ok { background:var(--pos-bg); color:var(--pos); } .mn-st.bad { background:var(--neg-bg); color:var(--neg); }
  .mn-st.na { background:var(--line-2); color:var(--ink-3); }
  @media (max-width:720px) { .mn-df-row { grid-template-columns:14px 1fr; } .mn-df-row > .mn-ar:not(:first-child) { display:none; }
    .mn-df { grid-template-columns:1fr; } .mn-df-src { border-right:0; border-bottom:2px solid var(--accent-2); padding:0 0 4px; } }
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
    return f"""<div class="mn-lead"><b style="color:var(--ink)">{_e(lead())}</b><br>{_e(LEAD_SUB)}</div>
      <div class="mn-h"><b>데이터가 화면까지 오는 길</b><span>화면 · 백테스트 · 봇이 같은 정의를 씁니다</span></div>
      <div class="mn-flow">{flow}</div>
      <div class="mn-src">신뢰 등급 — {_legend()} · '-' 는 오류가 아니라 '데이터 없음'</div>"""


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


_FRESH: dict = {}


def fresh_all() -> dict:
    """데이터 절에 걸린 경로만 한 번에 읽는다 — 경로마다 레지스트리 전체(파일 45개)를 다시 열면
    배포 서버에서 수십 초가 걸려 사용법 패널 뒤 화면 전체가 멈췄다(2026-11-15). 10분 메모."""
    import time
    if _FRESH.get('t', 0) > time.time() - 600:
        return _FRESH['rows']
    paths = {p for _s, items in DATA_FLOW for _i, _w, p, _l in items if p}
    try:
        import data_freshness as _df
        try:
            rows = {r['path']: r for r in _df.statuses(only=paths)}
        except TypeError:                              # 클라우드가 옛 모듈(only 인자 없음)을 들고 있을 때
            import importlib
            _df = importlib.reload(_df)
            rows = {r['path']: r for r in _df.statuses(only=paths)}
    except Exception:
        rows = {}
    _FRESH.update(t=time.time(), rows=rows)
    return rows


def fresh(path) -> dict | None:
    """data_freshness 의 파일 안 날짜·상태. 없거나 실패하면 None(화면에 '-')."""
    return fresh_all().get(path) if path else None


def sec_data(live: bool = True) -> str:
    """출처 → 항목 → 주기 → 마지막 갱신. live=False(PDF)는 마지막 갱신 칸을 뺀다 — PDF 는 만든 날의 사진이라."""
    groups = []
    for src, items in DATA_FLOW:
        rows = []
        for item, wf, path, lim in items:
            st_ = ''
            if live:
                r = fresh(path)
                if r and r.get('date'):
                    ok = r['state'] == 'ok'
                    d = r['date']
                    lab = (f"{d[2:4]}Q{(int(d[5:7]) + 2) // 3} 분기" if str(path).endswith('fundamentals_q.parquet')   # 분기 재무 = 담긴 최신 분기
                           else d[5:].replace('-', '/'))
                    st_ = (f'<span class="mn-st {"ok" if ok else "bad"}">{"✓" if ok else "!"} {_e(lab)}</span>'
                           + ('' if ok else f'<small>{_e(r.get("note"))}</small>'))
                else:
                    st_ = '<span class="mn-st na">-</span>'
                st_ = f'<span class="mn-ar">→</span>{st_}'
            rows.append(f"""<div class="mn-df-row"><span class="mn-ar">→</span>
              <div class="mn-df-it"><b>{_e(item)}</b>{f'<small>{_e(lim)}</small>' if lim else ''}</div>
              <span class="mn-ar">→</span><span class="mn-df-cy">{_e(schedule(wf))}</span>{st_}</div>""")
        groups.append(f'<div class="mn-df"><div class="mn-df-src">{_e(src)}</div><div>{"".join(rows)}</div></div>')
    head = ('출처 → 항목 → 갱신 주기(KST) → 마지막 갱신. ✓ = 주기 안에 제대로 들어옴 · ! = 늦어짐 · 날짜는 파일 안에 적힌 데이터 날짜'
            if live else '출처 → 항목 → 갱신 주기(KST). 화면에서는 항목마다 마지막 갱신 날짜와 정상 여부가 함께 보입니다')
    return (f'<div class="mn-src" style="margin:0 2px 10px">{head}</div>' + ''.join(groups)
            + '<div class="mn-src">전부 무료·공개 원천 · 모든 표 바로 아래에 출처 · 마지막 갱신이 붙습니다 · 예약 실행은 몇 분~수십 분 늦을 수 있습니다.</div>')


def sec_bot() -> str:
    rows = [(f'<b style="color:var(--ink)">{_e(c)}</b>', _e(d)) for c, d in BOT_CMDS]
    return (f'<div class="mn-lead">사이트를 열지 않아도 되는 일은 텔레그램 <a href="{BOT}" target="_blank" '
            f'style="color:var(--accent);font-weight:700;text-decoration:none">@buza_alarm_bot</a>(부자알람)이 대신합니다. '
            '종목은 티커 · 6자리 코드 · 한글 이름 모두 됩니다.</div>'
            + _table(['명령', '하는 일'], rows, {1: 'v'})
            + '<div class="mn-src">🔍 종목 분석 화면의 텔레그램 버튼을 누르면 그 종목이 바로 /watch 로 등록됩니다 · 전체 명령은 봇에서 /help</div>')


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


def sec_notes(limit: int | None = 20) -> str:
    rows = [(_e(r.get('date')), _e(r.get('area')), _e(r.get('text'))) for r in notes(limit)]
    if not rows:
        return '<div class="mn-lead">기록 없음.</div>'
    return _table(['날짜', '화면', '바뀐 것'], rows, {0: 'nw', 2: 'v'}) + \
        '<div class="mn-src">화면이 바뀌는 작업마다 한 줄씩 추가됩니다.</div>'


# (id, 제목, 한 줄, 함수) — 공개. 화면 '전체 설명서' 하위 탭은 SCREEN 만, PDF 는 전부(같은 순서).
SECTIONS = [
    ('overview', '개요', '무엇을 하는 도구인가 · 데이터가 화면까지 오는 길', sec_overview),
    ('features', '탭별 기능', '다섯 탭이 답하는 질문과 기능 전부', sec_features),
    ('routines', '활용 루틴', '언제 무엇을 보면 되나', sec_routines),
    ('rules', '실전 규칙', '봇이 실제로 쓰는 규칙과 그 이유', sec_rules),
    ('data', '데이터', '출처 → 항목 → 갱신 주기 → 마지막 갱신', sec_data),
    ('bot', '텔레그램 봇', '사이트를 열지 않아도 되는 일', sec_bot),
]
SCREEN = ('rules', 'data', 'bot')            # 개요·탭별 기능은 '한눈에', 루틴은 '활용 루틴' 탭과 같은 내용이라 화면에서는 뺀다
# 비공개(경영실) — 고객에게 다 보여줄 필요 없는 것. 공개 문서·PDF 에 넣지 않는다(2026-11-15).
INTERNAL = [
    ('notes', '개선 내역', '최근 바뀐 것 — 배포 공지는 안정화 뒤', sec_notes),
    ('method', '검증 · 한계', '규칙을 고르는 방법 · 알고 써야 할 한계 · 해보고 버린 것', sec_method),
]

_VARS = """:root{--ink:#111827;--ink-2:#374151;--ink-3:#4B5563;--line:#E5E7EB;--line-2:#F3F4F6;--surface:#FFFFFF;
--accent:#2453C8;--accent-2:#EEF3FF;--pos:#15803D;--pos-bg:#DCFCE7;--neg:#DC2626;--neg-bg:#FEE2E2;--warn:#B45309;--warn-bg:#FEF3C7;}"""


def build_html(font_url: str | None = None) -> str:
    """PDF·인쇄용 단독 문서(A4 세로). 화면과 같은 조각을 순서대로 이어 붙인다."""
    font = (f"@font-face{{font-family:'Pretendard';src:url('{font_url}') format('woff2');font-weight:100 900;}}" if font_url else '')
    toc = ''.join(f'<li><b>{_e(t)}</b> — {_e(d)}</li>' for _i, t, d, _fn in SECTIONS)
    body = ''.join(f"""<section><div class="pg-h"><span>{i:02d}</span><h2>{_e(t)}</h2><em>{_e(d)}</em></div>
        {fn(False) if sid == 'data' else fn()}</section>""" for i, (sid, t, d, fn) in enumerate(SECTIONS, 1))
    b = backtest()
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><title>STOCK DASHBOARD 사용설명서</title>
<style>{font}{_VARS}
@page{{size:A4;margin:14mm 13mm 15mm}}
body{{margin:0;background:#fff;font-family:'Pretendard','Noto Sans CJK KR','Malgun Gothic',sans-serif;color:var(--ink);
  -webkit-print-color-adjust:exact;print-color-adjust:exact}}
.cover{{page-break-after:always;padding-top:38mm}}
.cover .kick{{font-size:12px;font-weight:700;letter-spacing:.16em;color:var(--accent)}}
.cover h1{{font-size:30px;letter-spacing:-.04em;margin:10px 0 12px;line-height:1.35}}
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
<h1>{_e(lead())}</h1>
<p>{_e(LEAD_SUB)}<br>실전 규칙 v1.9(한국) 백테스트 연 {b.get('CAGR', '-')}% · 최대 낙폭 {b.get('MDD', '-')}% (같은 기간 코스피 {b.get('BM_CAGR', '-')}% · {b.get('BM_MDD', '-')}%).</p>
<ol>{toc}</ol>
<div class="meta">이 문서는 화면의 '📘 사용법 → 전체 설명서'와 같은 원천에서 자동으로 만들어집니다.<br>
사이트 {SITE}<br>텔레그램 {BOT}</div></div>
{body}
<div class="foot">{_e(DISCLAIMER)}</div></div></body></html>"""


if __name__ == '__main__':
    # python manual.py → docs/manual.html (글꼴은 상대 경로 — docs/ 에서 열어야 한다). PDF 는 tools/build_manual_pdf.sh
    out = ROOT / 'docs' / 'manual.html'
    out.write_text(build_html('../static/fonts/PretendardVariable.woff2'), encoding='utf-8')
    print(f'wrote {out} ({out.stat().st_size:,} bytes)')
