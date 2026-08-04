-- ══════════════════════════════════════════════════════════════════
-- 주도주 탐지 DB — RAW 단일 테이블 (마더 테이블)
--   · 주 1회 스냅샷(월요일 기준). 한 번 적재하면 수정하지 않음
--   · 판정 로직은 전부 VIEW로 분리 → 규칙이 바뀌어도 RAW는 불변
--   · 미국 전용 (한국은 잠정실적 공시일 확보 후 합류)
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS factor_weekly (
  as_of              TEXT NOT NULL,   -- 스냅샷 주 월요일  YYYY-MM-DD
  sym                TEXT NOT NULL,
  name               TEXT,
  sector             TEXT,

  -- ── E: 실적 이벤트 ────────────────────────────────────────────
  earn_date          TEXT,     -- 실적 발표일 (8-K item 2.02 · 없으면 10-Q 접수일)
  earn_src           TEXT,     -- '8K' | '10Q'   ← 신뢰도 구분
  earn_time          TEXT,     -- 'BMO' | 'AMC' | 'INTRADAY'
  earn_week_flag     INTEGER,  -- 이번 주가 실적 반응 주인가 (금요일 AMC는 다음 주로 이월)
  weeks_since_earn   REAL,     -- 공시 후 경과 주수  ★ 8주 초과 시 신호 만료
  earn_react_w0      REAL,     -- 실적 반응 주의 주봉 수익률 %  ★ E-signal
  earn_react_d2      REAL,     -- D0+D1 누적 %
  earn_react_gap     REAL,     -- D0 시가갭 %   (사이징 근거)
  earn_streak_pos    INTEGER,  -- 연속 양(+) 실적 반응 횟수

  -- ── V: 가치 (받는 것) ─────────────────────────────────────────
  period_end         TEXT,     -- 최신 반영 분기
  revenue            REAL,
  gross_profit       REAL,
  op_income          REAL,
  net_income         REAL,
  rev_yoy            REAL,     -- %   ⚠ 게이트 금지 (범위 −60~297)
  rev_qoq            REAL,     -- %   ★ NVDA를 잡은 지표
  gpm                REAL,     -- %
  gpm_qoq            REAL,     -- %p
  gpm_up2            INTEGER,  -- GPM 2분기 연속 개선
  opm                REAL,     -- %
  opm_qoq            REAL,     -- %p  ★★
  opm_up2            INTEGER,  -- ★★ 커버 50%, 오탐 0
  npm                REAL,     -- 순이익률 %
  npm_qoq            REAL,     -- %p  ★★
  npm_up2            INTEGER,  -- ★★ 실측 최강 (T결합 승률 85%)
  op_turn            INTEGER,  -- 흑자전환 (직전4Q 적자 존재 & 현재 흑자)
  op_pos_streak      INTEGER,  -- 연속 영업흑자 분기수
  rev_q_count        INTEGER,  -- 매출 인식 분기수  ← 4 미만이면 배제
  eps_yoy            REAL,     -- 저장만. 게이트 금지 (일회성 오염)

  -- ── T: 추세 (시장의 투표) ─────────────────────────────────────
  close              REAL,
  close_gt_ma20      INTEGER,  -- ★ 25/25 필수조건
  ma10_gt_ma20       INTEGER,  -- ★ 25/25 필수조건
  ma5 REAL, ma10 REAL, ma20 REAL,
  hi_5w              INTEGER,  -- 5주 신고가
  hi_10w             INTEGER,
  hi_20w             INTEGER,
  hi_52w             INTEGER,
  dist_52w           REAL,     -- 52주 신고가 대비 %  ★ −25% 이내가 매집 구간
  days_since_hi52    INTEGER,
  rs_4w REAL, rs_13w REAL, rs_26w REAL,   -- vs SPY  ★ rs_26w ≥ 1.2
  above_ma20_52w     REAL,     -- 52주 중 20주선 위 비율 %  ★ ≥70%
  break_ma20_52w     INTEGER,  -- 52주 중 20주선 이탈 횟수  ★ ≤4
  ret_1w REAL, ret_4w REAL, ret_13w REAL, ret_ytd REAL,
  mdd_52w            REAL,     -- 52주 종가 기준 최대낙폭 %
  low_52w_dist       REAL,     -- 52주 저점 대비 %
  vol_x_20w          REAL,     -- 거래량 / 20주 평균  ⚠ 저장만, 게이트 금지
  adv_20d            REAL,     -- 20일 평균 거래대금 (유동성)

  -- ── P: 가격 (주는 것) — 게이트 아님, 사이즈 배율용 ─────────────
  marcap             REAL,
  psr REAL, per REAL, pbr REAL,
  psr_pct5y          REAL,     -- 자기 5년 밴드 내 백분위

  -- ── 메타 ──────────────────────────────────────────────────────
  factor_ver         TEXT NOT NULL DEFAULT 'v1',   -- ★ 정의 바뀌면 올릴 것
  built_at           TEXT,
  PRIMARY KEY (as_of, sym, factor_ver)
);

CREATE INDEX IF NOT EXISTS ix_fw_sym   ON factor_weekly(sym, as_of);
CREATE INDEX IF NOT EXISTS ix_fw_asof  ON factor_weekly(as_of);
CREATE INDEX IF NOT EXISTS ix_fw_earn  ON factor_weekly(as_of, weeks_since_earn);

-- ══════════════════════════════════════════════════════════════════
-- VIEW — 판정. RAW를 건드리지 않고 여기만 갈아끼운다
-- ══════════════════════════════════════════════════════════════════
DROP VIEW IF EXISTS v_pick;
CREATE VIEW v_pick AS
SELECT
  as_of, sym, name, sector, close, dist_52w, earn_date, earn_react_w0,
  opm, opm_qoq, npm_qoq, rs_26w, psr, per, adv_20d, weeks_since_earn,

  -- V게이트: 마진 변곡 (OR)
  (COALESCE(npm_up2,0)=1 OR COALESCE(opm_up2,0)=1
   OR COALESCE(opm_qoq,-99)>=2 OR COALESCE(npm_qoq,-99)>=2
   OR COALESCE(gpm_qoq,-99)>=3 OR COALESCE(op_turn,0)=1)          AS gate_v,

  -- T게이트: 추세
  (COALESCE(close_gt_ma20,0)=1 AND COALESCE(ma10_gt_ma20,0)=1
   AND COALESCE(dist_52w,-99)>=-25 AND COALESCE(rs_26w,0)>=1.2
   AND COALESCE(above_ma20_52w,0)>=70)                            AS gate_t,

  -- 배제
  (COALESCE(rev_q_count,0)>=4 AND COALESCE(adv_20d,0)>=50000000
   AND COALESCE(marcap,0)>=2000000000)                            AS ok_base,

  -- P: 사이즈 배율
  CASE WHEN psr_pct5y IS NULL      THEN 0.7
       WHEN psr_pct5y <= 40        THEN 1.0
       WHEN psr_pct5y <= 70        THEN 0.7
       ELSE 0.5 END                                               AS size_mult,

  -- 점수 (두 손 = 곱)
  ROUND(
    (CASE WHEN COALESCE(npm_up2,0)=1 THEN 2 ELSE 0 END
   + CASE WHEN COALESCE(opm_up2,0)=1 THEN 2 ELSE 0 END
   + CASE WHEN COALESCE(opm_qoq,-99)>=2 THEN 1 ELSE 0 END
   + CASE WHEN COALESCE(op_turn,0)=1 THEN 1 ELSE 0 END)
  * (CASE WHEN COALESCE(dist_52w,-99)>=-10 THEN 3
          WHEN COALESCE(dist_52w,-99)>=-25 THEN 2 ELSE 0 END
   + CASE WHEN COALESCE(rs_26w,0)>=1.5 THEN 2
          WHEN COALESCE(rs_26w,0)>=1.2 THEN 1 ELSE 0 END)
  , 1)                                                            AS score,

  CASE
    WHEN COALESCE(earn_react_w0,-99)>=5 AND COALESCE(weeks_since_earn,99)<=1
      THEN 'BUY_1'                       -- E-signal 점등: 1차 매집
    WHEN COALESCE(hi_52w,0)=1
      THEN 'PYRAMID_2'                   -- 신고가 돌파: 2차
    WHEN COALESCE(weeks_since_earn,99)<=8
      THEN 'WATCH'                       -- 추적 (8주 카운트다운)
    ELSE 'DROP' END                                               AS action
FROM factor_weekly
WHERE factor_ver='v1';
