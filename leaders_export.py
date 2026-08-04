# -*- coding: utf-8 -*-
"""RAW 데이터 열람용 엑셀 내보내기
   python leaders_export.py            # 기본 워크북
   python leaders_export.py NVDA       # 특정 종목 전체 이력 시트 추가
"""
import os, sqlite3, sys
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "market.db")
OUT = os.path.join(BASE, "RAW_보기.xlsx")

DESC = [
    ("as_of", "스냅샷 주(월요일). 이 행의 모든 값은 이 시점에 '알 수 있었던' 값"),
    ("sym / name", "티커 / 회사명"),
    ("close", "그 주 종가 (수정주가)"),
    ("—— E 실적 ——", ""),
    ("earn_date", "실적 발표일. earn_src='8K'면 8-K item 2.02(진짜 발표일), '10Q'면 서류 접수일"),
    ("earn_time", "BMO=장전 / AMC=장후 / INTRADAY=장중"),
    ("weeks_since_earn", "발표 후 경과 주수. 8주 초과면 신호 만료"),
    ("earn_react_w0", "실적 반응 주의 주봉 수익률 % ★ E-signal 조건"),
    ("earn_react_d2", "발표 후 D0+D1 누적 %"),
    ("earn_react_gap", "발표 다음 거래일 시가갭 % (사이징 근거)"),
    ("—— V 가치 ——", ""),
    ("period_end / revenue / gross_profit / op_income / net_income", "최신 반영 분기와 원본 금액"),
    ("rev_yoy / rev_qoq", "매출 전년동기 / 전분기 대비 증감 %  ※ YoY는 게이트로 쓰지 말 것"),
    ("gpm / gpm_qoq / gpm_up2", "매출총이익률 %, 전분기 대비 %p, 2분기 연속 개선 여부"),
    ("opm / opm_qoq / opm_up2", "영업이익률 %, 전분기 대비 %p, 2분기 연속 개선"),
    ("npm / npm_qoq / npm_up2", "순이익률 %, 전분기 대비 %p, 2분기 연속 개선"),
    ("op_turn", "흑자전환(직전 4분기 중 영업적자 있었고 현재 흑자)"),
    ("op_pos_streak", "연속 영업흑자 분기수"),
    ("rev_q_count", "매출 인식 분기수. 4 미만이면 배제 대상"),
    ("—— T 추세 ——", ""),
    ("ma5 / ma10 / ma20", "5·10·20주 이동평균"),
    ("close_gt_ma20 / ma10_gt_ma20", "종가>20주선 / 10주선>20주선 (분석한 주도주 25/25 충족)"),
    ("hi_5w / hi_10w / hi_20w / hi_52w", "각 기간 신고가 여부 (1=신고가)"),
    ("dist_52w", "52주 신고가 대비 거리 %. −25% 이내가 매집 구간"),
    ("days_since_hi52", "52주 신고가 이후 경과일"),
    ("rs_4w / rs_13w / rs_26w", "SPY 대비 상대강도 배수. 1.0=지수와 동일"),
    ("above_ma20_52w", "최근 52주 중 20주선 위에 있던 비율 %"),
    ("break_ma20_52w", "최근 52주 중 20주선 이탈 횟수"),
    ("ret_1w / ret_4w / ret_13w / ret_ytd", "기간 수익률 %"),
    ("mdd_52w", "52주 종가 기준 최대낙폭 %"),
    ("low_52w_dist", "52주 저점 대비 상승률 %"),
    ("vol_x_20w", "거래량 / 20주 평균. ※ 검증 결과 진입 게이트로는 무용"),
    ("adv_20d", "20일 평균 거래대금 (달러)"),
    ("—— P 가격 ——", ""),
    ("marcap / psr / per / pbr", "시점 시총, 주가매출/이익/순자산 배수"),
    ("psr_pct5y", "자기 5년 밴드 내 PSR 백분위 (미구현)"),
    ("—— 메타 ——", ""),
    ("factor_ver", "팩터 정의 버전. 정의가 바뀌면 v2로 올려 나란히 보관"),
    ("built_at", "이 행을 계산한 날짜"),
]


def main():
    c = sqlite3.connect(DB)
    last = c.execute("SELECT MAX(as_of) FROM factor_weekly").fetchone()[0]
    w = pd.ExcelWriter(OUT, engine="openpyxl")

    pd.DataFrame(DESC, columns=["컬럼", "설명"]).to_excel(w, "0_컬럼설명", index=False)

    latest = pd.read_sql("SELECT * FROM factor_weekly WHERE as_of=? ORDER BY marcap DESC",
                         c, params=(last,))
    latest.to_excel(w, f"1_최신주차_{last}", index=False)

    pick = pd.read_sql("""SELECT * FROM v_pick WHERE as_of=? AND ok_base=1
                          ORDER BY gate_v DESC, gate_t DESC, score DESC""", c, params=(last,))
    pick.to_excel(w, "2_게이트판정_최신", index=False)

    # 종목별 요약 (전 기간)
    summ = pd.read_sql("""
        SELECT sym, name, COUNT(*) 주차수, MIN(as_of) 시작, MAX(as_of) 종료,
               ROUND(AVG(marcap)/1e9,1) 평균시총B, ROUND(AVG(psr),1) 평균PSR,
               ROUND(AVG(opm),1) 평균OPM, SUM(hi_52w) 신고가주수,
               ROUND(AVG(above_ma20_52w),0) 평균20주선위비율
        FROM factor_weekly GROUP BY sym, name ORDER BY 신고가주수 DESC""", c)
    summ.to_excel(w, "3_종목요약_1279종", index=False)

    for sym in (sys.argv[1:] or ["NVDA", "PLTR"]):
        d = pd.read_sql("SELECT * FROM factor_weekly WHERE sym=? ORDER BY as_of",
                        c, params=(sym.upper(),))
        if len(d):
            d.to_excel(w, f"4_{sym.upper()}_전체이력", index=False)

    w.close(); c.close()
    print(f"저장: {OUT}")
    print(f"  최신주차 {last} · {len(latest)}종")
    print(f"  게이트판정 {len(pick)}행 · 종목요약 {len(summ)}종")


if __name__ == "__main__":
    main()
