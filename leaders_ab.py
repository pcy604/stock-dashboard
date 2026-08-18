# -*- coding: utf-8 -*-
"""
leaders_ab.py — 주도주 규칙 L(대형) · S(소형) 발행

왜 규칙⑥을 대체하는가 (2026-08-18):
  시총 데이터를 고치고(us_marketcap.csv 27개월 방치 → SEC 공시 주식수) 유니버스를
  재구축한 뒤 규칙⑥을 다시 재니 **2022년 이후 CAGR 3.8%** 였다(SPY 13.2%).
  앞 구간 33.8% 로 좋아 보였던 건 look-ahead 오염과 국면 운이었다.

  규칙⑥이 놓치는 것이 구조적이었다. `시총 $2B+ & OPM>0` 조건은
  NVDA(2022-10) · TSLA(2019-08) · CVNA(2023-05) · AXTI(2025-05) 의 **대시세 출발
  시점을 전부 탈락**시킨다. 그 시점 시총은 $0.07B~$282B 로 4천 배 차이였고
  8종목 중 7종목이 그때 재무가 최악이었다(NVDA OPM 38.9%→7.4%, AXTI −53.1%).
  하나의 필터로 둘 다 잡을 수 없어 **대형/소형으로 쪼갠다.**

무엇이 실제로 작동했나 (637,269 주차-종목, 기저 +100%/1년 = 5.17%):
    주간 +20% 급등 & 거래량 **전주 대비** < 1.5배   → 27.4% (5.3배)  ← 최강
    52주 고점대비 −60~−90%                        → 19.5% (3.8배)
    RS13 > 1.5 (규칙⑥)                          → 16.1% (3.1배)
  ⚠️ 거래량은 20주 평균이 아니라 **전주 대비**로 봐야 보인다. 20주 평균으로 보면
     대시세 출발점의 거래량이 0.86배(조용함)로 나와 아무 신호도 안 잡힌다.
     그리고 방향이 직관과 반대다 — 거래량이 **터질 때가 아니라 안 터질 때**가 좋다.
     같은 급등에서 거래량 3배+ 는 13.4%, 거래량 감소는 30.4% 였다.

재무 조건을 왜 대형에만 거는가:
  흑자전환·OPM급개선은 **평균**은 크게 올리지만 중앙값·승률은 기저 이하다(꼬리형).
  영업익 8분기 신고점은 반대로 **중앙값·승률**이 전 구간 꾸준히 우위다(안정형).
  대형은 안정형 축(8Q신고점 or OPM개선)을 얹어 승률을 사고, 소형은 재무 조건 없이
  꼬리만 산다 — 소형 대시세는 출발 시점에 전부 적자였기 때문이다.

측정 (2018-06~2026-08, 편도 0.1%, 진입가 = 신호 주차 종가):
    L 단독 6칸  : 앞 26.4% / 뒤 28.4% / 전체 25.4%
    S 단독 10칸 : 앞 39.1% / 뒤 22.4% / 전체 23.5%
    L+S 50:50  : 앞 33.1% / 뒤 25.5% / **전체 24.5%**  MDD −38.0%
    SPY        : 앞 18.3% / 뒤 13.2% /     15.1%       MDD −31.8%
  진입을 1주 늦춰도 22.9%, 2주 늦춰도 18.8% — 금요일 종가 체결에만 성립하는
  미시구조 착시가 아니다.

⚠️ 남은 한계 (화면에도 같이 띄운다)
  · 생존 편향 — 유니버스가 '오늘 상장된 종목'이라 상장폐지 회사가 없다. 낙관적이다.
  · L 은 평균 3.5종만 보유한다. 6칸→7칸에서 뒤 구간이 28.4%→11.0% 로 꺾인다.
    한두 종목이 결과를 좌우한다는 뜻이고, 실전 재현성이 낮을 수 있다.
  · MDD −38% 는 SPY(−31.8%)보다 크다.

CLI
  python leaders_ab.py            # 백테스트 + 발행
  python leaders_ab.py publish    # 같음
"""
import os, sys, json, sqlite3
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "market.db")
VOL = os.path.join(BASE, "data", "_volwk.parquet")
OUT = os.path.join(BASE, "results", "leaders_ab.json")
VER = "v1"
FEE = 0.001

# ── 규칙 ────────────────────────────────────────────────────────────
SURGE_RET, SURGE_VOL = 20.0, 1.5
RULES = {
    "L": dict(name="대형 주도주",
              slots=6, trail=0.30, mc_lo=2e9, mc_hi=None, fund=True,
              text="시총 $2B+ · 주간 +20%↑ · 거래량 전주비 <1.5배 · "
                   "(영업익 8분기 신고점 OR OPM 전분기比 +5%p↑)",
              exit="진입 후 주봉 종가 고점 대비 −30% → 그 주 종가 전량. 재신호 시 재진입"),
    "S": dict(name="소형 대시세",
              slots=10, trail=0.40, mc_lo=None, mc_hi=2e9, fund=False,
              text="시총 $2B 미만 · 주간 +20%↑ · 거래량 전주비 <1.5배 · 재무 조건 없음",
              exit="진입 후 주봉 종가 고점 대비 −40% → 그 주 종가 전량. 재신호 시 재진입"),
}
MIN_ADV = 5e6            # 일평균 거래대금 $5M — 못 사는 신호는 백테스트에 넣지 않는다
SEGMENTS = [("앞 구간 2018-06~2021-12", "2018-06-01", "2021-12-31"),
            ("뒤 구간 2022-01~2026-08", "2022-01-01", "2026-12-31"),
            ("전체", "2018-06-01", "2026-12-31")]


# ── 데이터 ──────────────────────────────────────────────────────────
def load():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    d = pd.read_sql(f"""SELECT as_of,sym,name,close,ret_1w,adv_20d,marcap,period_end,
                               op_income,opm,rs_13w,rs_26w,dist_52w,per,psr,rev_yoy
                        FROM factor_weekly WHERE factor_ver='{VER}'""", c)
    c.close()
    d["as_of"] = pd.to_datetime(d.as_of)

    # 재무 플래그는 분기 패널에서 만든다(period_end 기준 = 그 주차에 알 수 있던 값)
    q = (d.dropna(subset=["period_end"]).drop_duplicates(["sym", "period_end"])
           [["sym", "period_end", "op_income", "opm"]]
           .sort_values(["sym", "period_end"]))
    g = q.groupby("sym")
    hi8 = g.op_income.transform(lambda s: s.shift(1).rolling(8, min_periods=4).max())
    q["F_HI8"] = ((q.op_income > 0) & (q.op_income > hi8)).astype(int)
    q["F_OPM"] = ((q.opm - g.opm.shift(1)) >= 5).astype(int)
    d = d.merge(q[["sym", "period_end", "F_HI8", "F_OPM"]],
                on=["sym", "period_end"], how="left")

    # 거래량 전주 대비. ⚠️ 20주 평균(vol_x_20w)이 아니다 — 그걸로는 안 보인다.
    v = pd.read_parquet(VOL)
    v["as_of"] = pd.to_datetime(v.as_of)
    v = v.sort_values(["sym", "as_of"])
    v["vw"] = v.groupby("sym").vol_wk.transform(lambda s: s / s.shift(1))
    return d.merge(v[["as_of", "sym", "vw"]], on=["as_of", "sym"], how="left")


def matrices(d, cols):
    return {k: d.pivot_table(index="as_of", columns="sym", values=k).sort_index()
            for k in cols}


def gate_of(M, key):
    r = RULES[key]
    g = ((M["ret_1w"] >= SURGE_RET) & (M["vw"] < SURGE_VOL) & (M["adv_20d"] >= MIN_ADV))
    if r["mc_lo"]:
        g &= M["marcap"] >= r["mc_lo"]
    if r["mc_hi"]:
        g &= M["marcap"] < r["mc_hi"]
    if r["fund"]:
        g &= (M["F_HI8"] == 1) | (M["F_OPM"] == 1)
    return g.fillna(False)


# ── 시뮬레이션 ──────────────────────────────────────────────────────
def sim(M, gate, N, trail, a, b):
    """주 1회 빈 슬롯만 채우고, 진입 후 주봉 종가 고점 대비 −trail 에서 그 주 종가 청산."""
    px = M["close"]
    dates = px.index[(px.index >= a) & (px.index <= b)]
    cash, pos, eq, nh = 1.0, {}, [], []
    W = 1.0 / N
    for t in dates:
        p = px.loc[t]
        for s in list(pos):
            v = p.get(s)
            if v is None or v != v:
                continue
            pos[s]["peak"] = max(pos[s]["peak"], v)
            if v <= pos[s]["peak"] * (1 - trail):
                cash += pos[s]["sh"] * v * (1 - FEE)
                del pos[s]
        # ⚠️ p.get(s, 기본값)은 키가 없을 때만 기본값을 쓴다. 상장폐지로 값이 NaN 이면
        #    NaN 이 그대로 나와 그 뒤 자산곡선 전체가 NaN 이 된다(2026-08-18 SKYT).
        val = cash + sum(o["sh"] * (v if (v := p.get(s)) == v and v is not None
                                    else o["last"]) for s, o in pos.items())
        if len(pos) < N:
            gg = gate.loc[t]
            rk = M["ret_1w"].loc[t]
            cand = [s for s in gg[gg].index
                    if s not in pos and p.get(s) == p.get(s) and (p.get(s) or 0) > 0]
            cand.sort(key=lambda s: -(rk.get(s) if rk.get(s) == rk.get(s) else -9e9))
            for s in cand[:N - len(pos)]:
                amt = min(val * W, cash)
                if amt <= 0:
                    break
                cash -= amt
                pos[s] = dict(sh=amt / p[s] * (1 - FEE), peak=p[s], last=p[s])
        for s, o in pos.items():
            v = p.get(s)
            if v == v and v is not None:
                o["last"] = v
        eq.append((t, cash + sum(o["sh"] * o["last"] for o in pos.values())))
        nh.append(len(pos))
    e = pd.Series(dict(eq))
    return e, float(np.mean(nh))


def stat(e):
    y = (e.index[-1] - e.index[0]).days / 365.25
    mdd = (e / e.cummax() - 1).min() * 100
    cagr = (e.iloc[-1] ** (1 / y) - 1) * 100
    return dict(cagr=round(float(cagr), 1), mdd=round(float(mdd), 1),
                total=round(float((e.iloc[-1] - 1) * 100), 0),
                recover=round(float(cagr / abs(mdd)), 2) if mdd else None)


def spy_stat(a, b):
    p = os.path.join(BASE, "data", "leaders_cache", "px_SPY.csv")
    s = pd.read_csv(p, index_col=0, parse_dates=True).Close
    s = s[(s.index >= a) & (s.index <= b)]
    return stat(s / s.iloc[0])


# ── 발행 ────────────────────────────────────────────────────────────
def build():
    d = load()
    M = matrices(d, ["close", "ret_1w", "adv_20d", "marcap", "vw", "F_HI8", "F_OPM"])
    gates = {k: gate_of(M, k) for k in RULES}

    print("백테스트 —", flush=True)
    bt, eq = {}, {}
    for k, r in RULES.items():
        bt[k] = {}
        for lab, a, b in SEGMENTS:
            e, held = sim(M, gates[k], r["slots"], r["trail"], a, b)
            eq[(k, lab)] = e
            bt[k][lab] = {**stat(e), "held": round(held, 1), "slots": r["slots"]}
            print(f"  {k} {lab:<22} CAGR {bt[k][lab]['cagr']:>6.1f}% "
                  f"MDD {bt[k][lab]['mdd']:>6.1f}%  보유 {held:.1f}/{r['slots']}", flush=True)
    bt["MIX"] = {}
    for lab, a, b in SEGMENTS:
        e = 0.5 * eq[("L", lab)] + 0.5 * eq[("S", lab)]
        bt["MIX"][lab] = stat(e)
        print(f"  L+S 50:50 {lab:<16} CAGR {bt['MIX'][lab]['cagr']:>6.1f}% "
              f"MDD {bt['MIX'][lab]['mdd']:>6.1f}%", flush=True)
    bt["SPY"] = {lab: spy_stat(a, b) for lab, a, b in SEGMENTS}

    # ── 주차별 신호 이력 (대시보드 주차별 조회용) ──
    last = M["close"].index.max()
    nm = d.drop_duplicates("sym").set_index("sym")["name"].to_dict()
    weeks, cands = {}, {}
    fwd = {h: (M["close"].shift(-h) / M["close"] - 1) for h in (1, 4, 13, 26, 52)}
    for k in RULES:
        g = gates[k]
        for t in g.index:
            hit = g.loc[t]
            syms = list(hit[hit].index)
            if not syms:
                continue
            rows = []
            for s in syms:
                rows.append(dict(
                    r=k, sym=s, name=(nm.get(s) or s)[:24],
                    close=_r(M["close"].loc[t].get(s)),
                    up=_r(M["ret_1w"].loc[t].get(s), 1),
                    vw=_r(M["vw"].loc[t].get(s), 2),
                    mc=_r((M["marcap"].loc[t].get(s) or np.nan) / 1e9, 2),
                    **{f"f{h}": _r((fwd[h].loc[t].get(s) or np.nan) * 100, 1)
                       for h in (1, 4, 13, 26, 52)}))
            rows.sort(key=lambda x: -(x["up"] or 0))
            weeks.setdefault(str(t.date()), []).extend(rows)
        hit = g.loc[last]
        cands[k] = [x for x in weeks.get(str(last.date()), []) if x["r"] == k]

    out = dict(
        generated=str(pd.Timestamp.today().date()),
        signal_week=str(last.date()),
        universe=int(M["close"].loc[last].notna().sum()),
        rules={k: {"name": v["name"], "text": v["text"], "exit": v["exit"],
                   "slots": v["slots"], "trail": int(v["trail"] * 100)}
               for k, v in RULES.items()},
        backtest=bt, candidates=cands, weeks=weeks,
        caveats=[
            "생존 편향 — 유니버스가 '오늘 상장된 종목'이라 상장폐지 회사가 빠져 있다. 실제는 더 나쁘다.",
            "L은 평균 3.5종만 보유한다. 칸을 6→7로 늘리면 뒤 구간이 28.4%→11.0%로 꺾인다 — 한두 종목이 결과를 좌우한다.",
            "MDD −38%는 SPY(−31.8%)보다 크다. 수익 +9.4%p를 낙폭 6%p로 사는 거래다.",
            "여러 조합 중 고른 결과다. 칸 수·진입 지연에서 고원을 확인했지만 선택 편향은 남는다.",
        ])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"→ {OUT}  ({os.path.getsize(OUT)/1e6:.2f} MB · 주차 {len(weeks)} · "
          f"이번 주 L {len(cands['L'])}종 / S {len(cands['S'])}종)")


def _r(v, n=2):
    try:
        return None if v is None or v != v else round(float(v), n)
    except Exception:
        return None


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    build()
