# -*- coding: utf-8 -*-
"""
이익 가속 신호 — 매출과 영업이익의 **성장률이 동시에 빨라지는** 분기에 주가가 급등한 주.

왜 이 규칙인가 (2026-08-23)
  L/S 규칙(+20% 급등 · 거래량<1.5 · 재무)은 시대의 주도주를 못 잡았다.
  8년간 TSLA 0회 · NVDA 0회 · WDC 0회 · PLTR 1회 · MU 2회.
  대박 시작점을 역산해보니 원인이 나왔다 — 시작점은 '급등한 주'가 아니었다.
    TSLA 2019-08-26  주간 +6.7% · 고점대비 −38.3% · 거래량 20주평균비 0.59
    NVDA 2022-10-10  주간 −7.0% · 고점대비 −65.9%
    PLTR 2024-07-29  주간 −9.0% · 고점대비 −13.4%
  실적도 공통점이 없어 보였다 — TSLA 적자, NVDA 흑자지만 급락 중, AXTI 매출 역성장.

  공통점은 **수준이 아니라 기울기의 변화**에 있었다. 분기 궤적을 그리자 보였다:
    NVDA GPM  43.5 → 53.6 → 63.3 → 64.6 → 70.1   (매출은 그동안 −16.5/−20.8/−13.2% 역성장)
    AXTI GPM  −6.4 →  8.0 → 22.3 → 29.6 → 44.9
    TSLA OPM  −11.5 → −2.6 → 4.1 → 4.9          (ΔOPM −17.2 → +8.9, Δ² +26.1)
  매출이 아니라 마진·이익이 먼저 돌고, 매출은 나중에 따라온다.

  학술 근거: He & Narayanamoorthy (2020, Journal of Accounting and Economics)
    "Earnings Acceleration and Stock Returns" — 이익 가속(성장률의 분기 대비 변화)은
    월 1.8% 초과수익을 내며 book-to-market·PEAD·gross profitability 와 맞먹는다.
    시장이 '계절적 랜덤워크'를 가정해 가속의 함의(2~3분기 뒤 성장률)를 못 읽는 데서 온다.
  실무 근거: Minervini SEPA — 대박 종목의 90% 이상이 대상승 전·중에 이익 가속을 동반.
    단 그의 '매출 20%↑' 같은 **수준 조건은 여기서 독이다**(알파 −23.3%). NVDA 는
    대상승 시작 시점 매출 YoY 가 +3.0% 였고 이후 1년 내내 역성장했다.

정의
  매출 성장률   rv = rev_yoy                                  (전년 동기 대비, %)
  이익 성장률   oi = (영업익_t − 영업익_{t−4}) / |매출_t|        (적자에서도 정의되게 매출로 스케일)
  가속          Δrv = rv_t − rv_{t−1분기} ,  Δoi = oi_t − oi_{t−1분기}
  신호          Δrv > 0  AND  Δoi > 0  AND  주간 종가 상승 ≥ +10%
                AND 일평균 거래대금 $5M+  AND 시총 $0.3B+  AND 분기매출 $10M+
                AND |이익가속| ≤ 10 (지표가 무의미해지는 회사 제외)
  ⚠️ 문턱은 '> 0' 뿐이다. 얼마나 빨라졌는지는 안 본다.
  ⚠️ 재무는 그 주차에 공시로 알 수 있던 분기만 쓴다(look-ahead 차단).

측정 (2018-06~2026-08 · 최종 신호 7,551건 · 377주에 신호 · 이번 주 19종)
  ※ 아래 표는 매출하한·이익가속상한을 넣기 전(8,303건) 숫자다. 두 안전장치를 넣은 뒤는
    평균 32.2% · 알파평균 12.6% · 2배+ 13.5% · 4배+ 1.9% ·
    10배+ 0.24% 로 거의 변화가 없다(발산 종목만 빠졌다).
  ⚠️ 이 분포는 U자다. **중앙값으로 판정하면 안 된다** — 등가중으로 담으면 받는 건 평균이다.
                              표본     평균   알파평균  상위10%  상위1%   2배+   4배+  10배+
    기저(전체)             598,279   14.1%   −2.2%     67%    227%   5.1%  0.5%  0.03%
    가속 + 급등10%           6,461   31.8%  +12.5%    127%    462%  13.7%  2.1%  0.28%
      (대조) 급등10% 만      29,995   29.8%   +9.3%    123%    396%  13.4%  1.9%  0.16%
    가속 + 급등25%             810   59.9%  +36.8%    213%    745%  24.0%  5.1%  0.74%
      (대조) 급등25% 만       3,758   52.5%  +27.1%    188%    548%  23.7%  4.0%  0.37%
  가속 조건은 대조군을 전 항목에서 이긴다. 10배 확률은 정확히 2배씩 벌어진다.
  문턱을 조일수록 모든 지표가 좋아지지만(급등25% 알파평균 +36.8%) 주도주를 놓친다:
    급등 +10%  NVDA 13 · TSLA 21 · PLTR 10 · MU 22 · BE 15 · WDC 11 회
    급등 +20%  NVDA  1 · TSLA  8 · PLTR  4 · MU  3 · BE  7 · WDC  2 회
  **+10% 를 택한 이유는 포착이다** — 포트폴리오 운용은 사람이 하고, 이 화면의 일은
  주도주가 신호에 걸리게 하는 것이다(2026-08-23 사용자 결정).

불타기(신호 반복)에 대해 — 실측이 가설을 반만 지지한다 (2026-08-24)
  회차     표본    평균   알파   중앙값   2배+   10배+  (10배 실건수)
   1회    1,279   35.9%  +12.6%  +17.0%  13.4%  0.08%   1건
   2회    1,009   36.7%  +14.0%  +13.0%  14.3%  0.10%   1건
   3회      783   36.7%  +15.8%  +15.0%  14.7%  0.13%   1건
   4-5회  1,101   29.2%  +11.9%   +3.6%  12.2%  0.27%   3건
   6-9회  1,103   29.6%  +14.2%   −0.0%  14.1%  0.63%   7건
  10-19회   598   22.3%   +5.0%   −2.5%  12.5%  0.17%   1건
   20회+     35   13.8%   −4.7%   −1.8%  11.4%  0.00%   0건
  · **회차가 늘수록 평균이 좋아지지 않는다.** 오히려 10회부터 알파가 꺾이고
    20회+ 는 음수다. "계속 뜨니까 계속 담는다"를 성과가 그대로 지지하진 않는다.
  · 지지하는 건 하나뿐 — **10배 확률이 6-9회차에서 1회차의 8배**(0.08→0.63%)다.
    중앙값은 그 구간에서 0 으로 내려간다. 대부분 실패하고 가끔 초대박인 구조,
    즉 수익금 플레이에는 맞는 모양이다.
  · ⚠️ 그런데 그 0.63% 는 **7건**이다. 7건으로 판정하고 있다는 걸 잊으면 안 된다.
  · 종목 단위로 보면 신호가 많이 뜬 종목이 압도적이다
    (총 1회 종목 알파 −12.5% · 8-15회 +23.3% · 16회+ +34.3%, 2배+ 종목 2.6%→25.0%).
    **단 이건 사후 정보다** — 지금 이 종목이 앞으로 몇 번 신호를 낼지 모른다.
  · 실무 결론: 반복 신호를 계속 띄우되 **10회를 넘어가면 경고**한다. 상한을 코드로
    강제하진 않는다(비중은 사람이 준다). 화면에 회차를 찍는 이유가 이것이다.

⚠️ 알아야 할 한계
  · 이 규칙을 6칸·등가중 포트폴리오로 돌리면 CAGR 12.7% 로 SPY(15.1%)에 진다.
    평균 74종을 들게 되어 한 종목 비중이 1.4% 라, 802% 대박이 나도 전체엔 11% 기여다.
    **신호 목록이지 포트폴리오 규칙이 아니다.**
  · 상위 5% 거래가 전체 수익의 94% 를 만든다. 꼬리에 전적으로 의존한다.
  · 연도별 편차가 극심하다(2020 알파 +13.5% · 2023 −25.3% · 2024 −22.2%).
  · 유니버스에 상장폐지 종목이 없다 — 모든 숫자가 낙관 쪽으로 편향돼 있다.
  · 영업이익을 매출로 스케일한 것은 학술 논문(총자산 기준)과 다른 임의 선택이다.

CLI
  python leaders_accel.py            # 신호 발행
"""
import json
import os
import sqlite3
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "market.db")
OUT = os.path.join(BASE, "results", "leaders_accel.json")
VER = "v1"
SURGE = 10.0          # 주간 상승률 문턱 (%)
MIN_ADV = 5e6         # 일평균 거래대금 $5M
MIN_MC = 3e8          # 시총 $0.3B
MIN_QREV = 1e7        # 분기 매출 $10M — 이 아래는 이익가속이 발산한다(2026-08-23)
MAX_OIA = 10.0        # 이익가속 절대값 상한. 매출이 사업 규모를 대표 못 하는 회사
                      # (MSTR: 분기매출 $100M 인데 OPM −11,641% — 비트코인 손상차손)
                      # 에서 지표가 무의미해진다. 분포상 95%가 5.83 이라 상위 3% 만 잘린다.
                      # 측정: 상한을 걸어도 평균 32.6% · 알파 13.1% 로 변화 없다.


def load():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    d = pd.read_sql(f"""SELECT as_of,sym,name,close,marcap,adv_20d,ret_1w,dist_52w,
                               mdd_52w,rs_4w,rs_13w,vol_x_20w,per,psr,period_end,
                               revenue,op_income,gross_profit,rev_yoy,gpm,opm,opm_qoq
                        FROM factor_weekly WHERE factor_ver='{VER}'""", c)
    c.close()
    d["as_of"] = pd.to_datetime(d.as_of)

    # 분기 패널에서 가속을 만든다 — period_end 기준이라 그 주차에 알 수 있던 값만 쓴다
    q = (d.dropna(subset=["period_end"]).drop_duplicates(["sym", "period_end"])
           [["sym", "period_end", "revenue", "op_income", "gross_profit",
             "rev_yoy", "gpm", "opm"]].sort_values(["sym", "period_end"]))
    g = q.groupby("sym")
    # ⚠️ 매출로 나누므로 매출이 0에 가까우면 발산한다. 2026-08-23 최초 발행에서
    #    분기매출 $0M 종목(AMLX·JOBY 등)의 이익가속이 inf 로 나와 조건을 그냥 통과했다.
    #    분기매출 $10M 하한을 둔다 — 성과는 거의 그대로이고(평균 31.8→32.7%,
    #    알파 12.5→13.2%) 발산만 사라진다.
    q.loc[q.revenue.abs() < MIN_QREV, "revenue"] = np.nan
    q["oi_g"] = (q.op_income - g.op_income.shift(4)) / q.revenue.abs()
    q["oi_g"] = q.oi_g.replace([np.inf, -np.inf], np.nan)
    q["rv_g"] = q.rev_yoy
    q["oi_a"] = q.oi_g - g["oi_g"].shift(1)      # 이익 가속 (%p)
    q["rv_a"] = q.rv_g - g["rv_g"].shift(1)      # 매출 가속 (%p)
    q["dgpm"] = q.gpm - g.gpm.shift(1)
    q["dopm"] = q.opm - g.opm.shift(1)
    q["ACC"] = ((q.rv_a > 0) & (q.oi_a > 0) & (q.oi_a.abs() <= MAX_OIA)).astype(int)
    return d.merge(q[["sym", "period_end", "oi_a", "rv_a", "dgpm", "dopm", "ACC"]],
                   on=["sym", "period_end"], how="left")


def matrices(d, cols):
    px = d.pivot_table(index="as_of", columns="sym", values="close").sort_index()
    return {k: d.pivot_table(index="as_of", columns="sym", values=k)
                .reindex(index=px.index, columns=px.columns) for k in cols}


def gate_of(M):
    return ((M["adv_20d"] >= MIN_ADV) & (M["marcap"] >= MIN_MC)
            & (M["ACC"] == 1) & (M["ret_1w"] >= SURGE)).fillna(False)


def _r(v, n=2):
    if v is None or v != v:
        return None
    return round(float(v), n)


def build():
    d = load()
    COLS = ["close", "marcap", "adv_20d", "ret_1w", "dist_52w", "mdd_52w", "rs_4w",
            "rs_13w", "vol_x_20w", "per", "psr", "revenue", "op_income", "rev_yoy",
            "gpm", "opm", "oi_a", "rv_a", "dgpm", "dopm", "ACC"]
    M = matrices(d, COLS)
    px = M["close"]
    g = gate_of(M)
    ordn = g.cumsum().where(g)                    # 종목별 신호 회차
    fwd = {h: (px.shift(-h) / px - 1) for h in (1, 4, 13, 26, 52, 104)}

    spy_p = os.path.join(BASE, "data", "leaders_cache", "px_SPY.csv")
    spy = pd.read_csv(spy_p, index_col=0, parse_dates=True).Close.reindex(px.index).ffill()
    sfw = {h: (spy.shift(-h) / spy - 1) for h in (13, 52)}

    nm = d.drop_duplicates("sym").set_index("sym")["name"].to_dict()
    last = px.index.max()

    # ── 신호 성적표 (꼬리 기준. 중앙값은 참고로만) ──────────────────
    f52 = fwd[52].where(g).stack().dropna()
    a52 = (fwd[52].where(g).sub(sfw[52], axis=0)).stack().dropna()
    base_f = fwd[52].where((M["adv_20d"] >= MIN_ADV) & (M["marcap"] >= MIN_MC)).stack().dropna()
    perf = dict(
        n=int(g.sum().sum()), n_scored=int(len(f52)),
        mean=_r(f52.mean() * 100, 1), median=_r(f52.median() * 100, 1),
        alpha_mean=_r(a52.mean() * 100, 1), alpha_median=_r(a52.median() * 100, 1),
        p90=_r(f52.quantile(.90) * 100, 0), p99=_r(f52.quantile(.99) * 100, 0),
        mx=_r(f52.max() * 100, 0),
        w2=_r((f52 >= 1).mean() * 100, 1), w4=_r((f52 >= 3).mean() * 100, 1),
        w10=_r((f52 >= 9).mean() * 100, 2),
        base_mean=_r(base_f.mean() * 100, 1), base_w2=_r((base_f >= 1).mean() * 100, 1),
        base_w4=_r((base_f >= 3).mean() * 100, 1), base_w10=_r((base_f >= 9).mean() * 100, 2))
    by_year = {}
    t = pd.DataFrame({"f": f52, "a": a52}).dropna().reset_index()
    for y, gg in t.groupby(t["as_of"].dt.year):
        by_year[int(y)] = dict(n=len(gg), mean=_r(gg.f.mean() * 100, 1),
                               alpha=_r(gg.a.mean() * 100, 1),
                               w2=_r((gg.f >= 1).mean() * 100, 1),
                               w4=_r((gg.f >= 3).mean() * 100, 1))

    # ── 신호 회차별 성과 (불타기 판단 근거) ──────────────────────
    # ⚠️ 이 표가 말하는 건 "회차가 늘수록 좋다"가 **아니다**. 평균 알파는 오히려
    #    떨어진다. 올라가는 건 10배 확률뿐이고, 그 확률의 표본은 한 자릿수 건수다.
    st = pd.DataFrame({"k": ordn.stack(), "f": fwd[52].where(g).stack(),
                       "a": (fwd[52].where(g).sub(sfw[52], axis=0)).stack()}).dropna()
    by_step = []
    for lo, hi, lbl in [(1, 1, "1회"), (2, 2, "2회"), (3, 3, "3회"), (4, 5, "4-5회"),
                        (6, 9, "6-9회"), (10, 19, "10-19회"), (20, 999, "20회+")]:
        x = st[(st.k >= lo) & (st.k <= hi)]
        if len(x) < 30:
            continue
        by_step.append(dict(
            lbl=lbl, n=len(x), mean=_r(x.f.mean() * 100, 1),
            alpha=_r(x.a.mean() * 100, 1), median=_r(x.f.median() * 100, 1),
            w2=_r((x.f >= 1).mean() * 100, 1), w4=_r((x.f >= 3).mean() * 100, 1),
            w10=_r((x.f >= 9).mean() * 100, 2),
            n10=int((x.f >= 9).sum()), n4=int((x.f >= 3).sum())))

    # ── 주차별 신호 이력 ──────────────────────────────────────────
    weeks = {}
    for tt in g.index:
        hit = g.loc[tt]
        syms = list(hit[hit].index)
        if not syms:
            continue
        rows = []
        for s in syms:
            rows.append(dict(
                sym=s, name=(nm.get(s) or s)[:24], n=int(ordn.loc[tt].get(s) or 0),
                close=_r(px.loc[tt].get(s)), up=_r(M["ret_1w"].loc[tt].get(s), 1),
                mc=_r((M["marcap"].loc[tt].get(s) or np.nan) / 1e9, 2),
                dd=_r(M["dist_52w"].loc[tt].get(s), 1),
                rva=_r(M["rv_a"].loc[tt].get(s), 1),
                oia=_r((M["oi_a"].loc[tt].get(s) or np.nan) * 100, 2),
                revy=_r(M["rev_yoy"].loc[tt].get(s), 1),
                gpm=_r(M["gpm"].loc[tt].get(s), 1), opm=_r(M["opm"].loc[tt].get(s), 1),
                dgpm=_r(M["dgpm"].loc[tt].get(s), 1), dopm=_r(M["dopm"].loc[tt].get(s), 1),
                oi=_r((M["op_income"].loc[tt].get(s) or np.nan) / 1e6, 0),
                rs4=_r(M["rs_4w"].loc[tt].get(s)), rs13=_r(M["rs_13w"].loc[tt].get(s)),
                per=_r(M["per"].loc[tt].get(s), 1), psr=_r(M["psr"].loc[tt].get(s), 2),
                **{f"f{h}": _r((fwd[h].loc[tt].get(s) or np.nan) * 100, 1)
                   for h in (1, 4, 13, 26, 52, 104)}))
        rows.sort(key=lambda x: -(x["up"] or 0))
        weeks[str(tt.date())] = rows

    # ── 가격 곡선 (심층조회 차트용) ────────────────────────────────
    # 가격 곡선은 **여기서 만들지 않는다.** L/S 심층조회와 같은 곡선을 각자 저장해
    # 674종이 중복됐다(2026-08-25). 신호 구간만 싣고 곡선은 curves_build.py 가
    # results/price_curves.json 으로 합쳐 만든다.
    # ⚠️ curves_build.py 는 반드시 이 스크립트 **뒤에** 돌아야 한다.
    dt_ix = {t: i for i, t in enumerate(px.index)}
    spans = {}
    for tt in g.index:
        hit = g.loc[tt]
        for s in hit[hit].index:
            lo, hi = spans.get(s, (10**9, -1))
            spans[s] = (min(lo, dt_ix[tt]), max(hi, dt_ix[tt]))

    cands = weeks.get(str(last.date()), [])
    out = dict(generated=str(pd.Timestamp.today().date()),
               signal_week=str(last.date()),
               universe=int(px.loc[last].notna().sum()),
               rule=dict(surge=SURGE, min_adv=MIN_ADV, min_mc=MIN_MC,
                         text=f"매출·영업이익 성장률이 **동시에 빨라진** 분기 · "
                              f"그 주 종가 +{SURGE:g}%↑ · 거래대금 $5M+ · 시총 $0.3B+"),
               dates=[str(t.date()) for t in px.index], spans=spans,
               perf=perf, by_year=by_year, by_step=by_step,
               candidates=cands, weeks=weeks)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"신호 {perf['n']:,}건 · 주차 {len(weeks)} · 이번 주 {len(cands)}종")
    print(f"평균 {perf['mean']}% · 알파평균 {perf['alpha_mean']}% · "
          f"2배+ {perf['w2']}% · 4배+ {perf['w4']}% · 10배+ {perf['w10']}%")
    print(f"→ {OUT}  ({os.path.getsize(OUT)/1e6:.2f} MB · 신호구간 {len(spans)}종)")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    build()
