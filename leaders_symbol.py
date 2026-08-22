# -*- coding: utf-8 -*-
"""
종목별 심층 데이터 — 주봉 + 규칙별 신호·진입·청산·재진입

대시보드는 Streamlit Cloud에서 도는데 market.db(400MB)가 저장소에 없다.
그래서 여기서 미리 계산해 results/leaders_symbol_detail.json 으로 떨궈두고,
대시보드는 그 JSON만 읽어 그린다.

  · 대상: 규칙 A/B/R6 중 하나라도 신호가 한 번이라도 걸린 종목 전부
  · 주봉 종가 전체 + 신호 주차 인덱스 + 거래(진입·청산·재진입) + 신호주 지표표
  · 청산은 백테스트와 동일: 진입 후 주봉 종가 고점 대비 −20%, 그 종가에 전량

CLI
  python leaders_symbol.py build          # JSON 생성
  python leaders_symbol.py chart NVDA     # 연구용 PNG 저장
"""
import os, sys, json, sqlite3, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
BASE = os.path.dirname(os.path.abspath(__file__))
OUT_JSON = os.path.join(BASE, "results", "leaders_symbol_detail.json")
TRAIL = 0.20

# 2026-08-18: L·S 추가. 규칙 A/B/R6 은 **기록 보존용으로 남긴다** —
# 화면에서 지우면 "무엇이 왜 실패했는지"의 이력이 사라진다. 신규 발행은 L/S 로만 한다.
# 청산폭이 규칙마다 다르므로 (설명, 조건, 트레일링) 3튜플로 바꿨다.
RULES = {
    "L": ("[신규] 대형 주도주 — 시총$2B+ · 주간+20%↑ · 거래량전주비<1.5 · (영업익8Q신고점 or OPM+5%p)",
          lambda d: (d.ret_1w >= 20) & (d.vw < 1.5) & (d.marcap >= 2e9) &
                    (d.adv_20d >= 5e6) & ((d.F_HI8 == 1) | (d.F_OPM == 1)), 0.30),
    "S": ("[신규] 소형 대시세 — 시총$2B미만 · 주간+20%↑ · 거래량전주비<1.5 · 재무조건 없음",
          lambda d: (d.ret_1w >= 20) & (d.vw < 1.5) & (d.marcap < 2e9) &
                    (d.adv_20d >= 5e6), 0.40),
}
# 2026-08-22: 구 규칙 A/B/R6 을 여기서 뺐다.
#   A/B/R6 이 12,144 행 중 9,707 행(80%)을 차지해 주차별 조회를 열면 **폐기된 규칙이
#   화면을 뒤덮고** 정작 현행 L/S 가 묻혔다. 규칙⑥은 2026-08-18 에 종료됐고
#   (2022년 이후 CAGR 3.8% · SPY 13.2%), A/B 는 애초에 페이퍼 원장용이었다.
#   이력은 지우지 않는다 — 규칙⑥의 신호·퍼널·페이퍼 원장은 results/leaders_signal.json
#   과 화면의 📕 구 규칙⑥ 기록 확장패널에 그대로 남아 있고, HISTORY.md 4~5기가
#   왜 실패했는지 기록한다. 여기서 빼는 것은 '현재 판단에 쓰는 표'에서 빼는 것이다.
BO = {"b_ophigh": "영업익신고점", "b_nihigh": "순익신고점",
      "b_opjump": "영업익QoQ50", "b_opmjump": "OPM_QoQ3"}


def load():
    import leaders_boost as B
    d = B.build()
    d["as_of"] = pd.to_datetime(d.as_of)
    c = sqlite3.connect(os.path.join(BASE, "data", "market.db"))
    # rs_4w 추가(2026-08-17) — leaders_boost.build()가 안 싣는 컬럼이라 여기서 같이 끌어온다
    ex = pd.read_sql("SELECT as_of,sym,name,rs_4w,rs_26w,mdd_52w,vol_x_20w,ret_1w,"
                     "period_end,op_income,opm AS opm2 "
                     "FROM factor_weekly WHERE factor_ver='v1'", c)
    c.close()
    ex["as_of"] = pd.to_datetime(ex.as_of)
    # 2026-08-18: L/S 규칙에 필요한 재료. 거래량은 **전주 대비**(vol_x_20w 아님) —
    # 20주 평균으로 보면 대시세 출발점이 0.86배(조용함)로 나와 아무것도 안 잡힌다.
    q = (ex.dropna(subset=["period_end"]).drop_duplicates(["sym", "period_end"])
           [["sym", "period_end", "op_income", "opm2"]].sort_values(["sym", "period_end"]))
    g = q.groupby("sym")
    hi8 = g.op_income.transform(lambda s: s.shift(1).rolling(8, min_periods=4).max())
    q["F_HI8"] = ((q.op_income > 0) & (q.op_income > hi8)).astype(int)
    q["F_OPM"] = ((q.opm2 - g.opm2.shift(1)) >= 5).astype(int)
    ex = ex.merge(q[["sym", "period_end", "F_HI8", "F_OPM"]],
                  on=["sym", "period_end"], how="left").drop(columns=["op_income", "opm2"])
    v = pd.read_parquet(os.path.join(BASE, "data", "_volwk.parquet"))
    v["as_of"] = pd.to_datetime(v.as_of)
    v = v.sort_values(["sym", "as_of"])
    v["vw"] = v.groupby("sym").vol_wk.transform(lambda s: s / s.shift(1))
    ex = ex.merge(v[["as_of", "sym", "vw"]], on=["as_of", "sym"], how="left")
    return d.merge(ex, on=["as_of", "sym"], how="left")


def simulate(sig, close, trail=TRAIL):
    """신호 → 진입, 주봉 종가 고점 대비 −trail → 청산. 청산 뒤 재신호면 재진입."""
    out, i, n = [], 0, len(close)
    while i < n:
        if not sig[i] or not np.isfinite(close[i]):
            i += 1
            continue
        e, peak = i, close[i]
        j = i + 1
        while j < n:
            if np.isfinite(close[j]):
                peak = max(peak, close[j])
                if close[j] <= peak * (1 - trail):
                    break
            j += 1
        closed = j < n
        x = min(j, n - 1)
        out.append(dict(e=e, x=x, closed=closed,
                        ret=round((close[x] / close[e] - 1) * 100, 1),
                        peak=round(float(peak), 2),
                        wk=int(x - e)))
        i = x + 1
    return out


def cmd_build():
    d = load()
    # ⚠️ 2026-08-16 에 `d = d[d.as_of <= "2026-08-10"]` 이 하드코딩돼 있었다(7bf1c11).
    #    그 탓에 심층조회·주차별 조회가 08-10 에 **영구히 묶여** 새 주차가 안 붙었고,
    #    08-10 주차의 '이후1주'도 None 이었다(08-17 을 잘라내니 계산할 수가 없다).
    #    조용히 낡아가는 종류의 버그다 — 화면은 정상으로 보이고 날짜만 안 움직인다.
    #    2026-08-22 제거. 잘라야 할 이유가 생기면 리터럴이 아니라 상대 기준으로 써라.
    # 전방 수익률 — "그 주에 걸린 신호가 이후 어떻게 됐나"를 주차별 조회에서 보려면 필요하다.
    px = d.pivot(index="as_of", columns="sym", values="close").sort_index()
    # 1·4주 추가(2026-08-17): 13주는 이미 한 분기라 "신호 직후에 뭘 했나"가 안 보인다.
    # 짧은 창은 노이즈가 크지만, 진입 타이밍 판단에는 짧은 쪽이 실제로 쓰인다.
    for h in (1, 4, 13, 26, 52):
        f = (px.shift(-h) / px - 1).stack().rename(f"f{h}").reset_index()
        d = d.merge(f, on=["as_of", "sym"], how="left")
    dates = sorted(d.as_of.unique())
    di = {t: k for k, t in enumerate(dates)}
    flags = {k: fn(d) for k, (_, fn, _t) in RULES.items()}
    hit = set()
    for k, f in flags.items():
        hit |= set(d.loc[f.fillna(False), "sym"])
    print(f"신호 이력 종목 {len(hit)}개 · 주차 {len(dates)}")

    syms = {}
    for s, g in d[d.sym.isin(hit)].groupby("sym"):
        g = g.sort_values("as_of")
        idx = g.as_of.map(di).values
        close = g.close.values.astype(float)
        rec = dict(name=(g.name.dropna().iloc[0] if g.name.notna().any() else s),
                   i=[int(v) for v in idx],
                   c=[round(float(v), 3) if v == v else None for v in close],
                   sig={}, trades={}, rows=[])
        for k, (_, fn, _tr) in RULES.items():
            m = fn(g).fillna(False).values
            if not m.any():
                continue
            rec["sig"][k] = [int(idx[p]) for p in np.where(m)[0]]
            tr = []
            for t in simulate(m, close, _tr):
                # 진입 시점부터 신호가 몇 주 연속으로 계속 떴는가.
                # 매수 판단 시점에 이미 알 수 있는 정보다 — "며칠째 뜨고 있나".
                sk, q = 0, t["e"]
                while q < len(m) and m[q]:
                    sk += 1; q += 1
                tr.append(dict(e=int(idx[t["e"]]), x=int(idx[t["x"]]),
                               ep=round(float(close[t["e"]]), 2),
                               xp=round(float(close[t["x"]]), 2),
                               ret=t["ret"], wk=t["wk"], closed=t["closed"], sk=sk))
            rec["trades"][k] = tr
        # 신호주 지표표 (어느 규칙이든 걸린 주차)
        any_m = np.zeros(len(g), bool)
        for k in rec["sig"]:
            any_m |= RULES[k][1](g).fillna(False).values
        for p in np.where(any_m)[0]:
            r = g.iloc[p]
            _rs = [k for k in RULES if k in rec["sig"] and di[r.as_of] in rec["sig"][k]]
            # 이 종목이 그 규칙에서 몇 번째로 낸 신호인가. 연속일 필요 없고,
            # 보유 중 재신호도 센다. 규칙에는 안 쓰고 판단 재료로만 띄운다
            # (2026-08-22 측정: S 3번째+ 는 통계 검증을 통과했지만 임계 격자가
            #  1:27.8 2:27.4 3:37.3 4:27.0 5:35.3 으로 지그재그였다).
            _n = (rec["sig"][_rs[0]].index(di[r.as_of]) + 1) if _rs else 0
            rec["rows"].append(dict(
                d=str(pd.Timestamp(r.as_of).date()), r=_rs, n=_n,
                close=round(float(r.close), 2),
                # rs4 추가(2026-08-17): 주간으로 후보를 받는데 13/26주만 보면 '최근 가속'이
                # 안 보인다는 지적. 짧은 창은 노이즈가 크지만 판단 재료로는 있어야 한다.
                rs4=_r(r.rs_4w), rs13=_r(r.rs_13w), rs26=_r(r.rs_26w),
                opm=_r(r.opm), opmq=_r(r.opm_qoq),
                per=_r(r.per), psr=_r(r.psr), dist=_r(r.dist_52w), mdd=_r(r.mdd_52w),
                # 2026-08-16: 화면 요청으로 매출 YoY → QoQ 로 교체(직전 분기 대비 가속을 본다).
                # rev(YoY)는 기존 JSON 호환을 위해 남겨 두고 revq 를 추가한다.
                vol=_r(r.vol_x_20w), rev=_r(r.rev_yoy), revq=_r(r.rev_qoq),
                # 2026-08-18: 거래량은 20주 평균이 아니라 **전주 대비**가 신호다.
                # 20주 평균으로 보면 대시세 출발점이 0.86배(조용함)로 나와 아무것도 안 잡힌다.
                vwk=_r(r.vw, 2), up=_r(r.ret_1w, 1),
                mc=_r(r.marcap / 1e9, 2), adv=_r(r.adv_20d / 1e6, 0),
                f1=_r(r.f1 * 100, 1), f4=_r(r.f4 * 100, 1),
                f13=_r(r.f13 * 100, 1), f26=_r(r.f26 * 100, 1), f52=_r(r.f52 * 100, 1),
                trg=" ".join((["흑자전환"] if r.op_turn == 1 else []) +
                             [v for kk, v in BO.items() if r.get(kk) == 1]) or "-"))
        syms[s] = rec

    out = dict(generated=str(pd.Timestamp.today().date()),
               dates=[str(pd.Timestamp(t).date()) for t in dates],
               rules={k: v[0] for k, v in RULES.items()},
               trails={k: v[2] for k, v in RULES.items()},
               symbols=syms)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"→ {OUT_JSON}  ({os.path.getsize(OUT_JSON)/1e6:.1f} MB · {len(syms)}종)")


def _r(v, n=2):
    try:
        return None if v != v else round(float(v), n)
    except Exception:
        return None


def cmd_chart(sym):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    j = json.load(open(OUT_JSON, encoding="utf-8"))
    if sym not in j["symbols"]:
        print(f"{sym}: 신호 이력 없음"); return
    r = j["symbols"][sym]
    dt = pd.to_datetime([j["dates"][i] for i in r["i"]])
    c = pd.Series(r["c"], index=dt).astype(float)
    COL = {"L": "#1f6b45", "S": "#7a3fa0"}
    fig, ax = plt.subplots(figsize=(11.5, 4.2), dpi=110)
    fig.patch.set_facecolor("white"); ax.set_facecolor("white")
    ax.plot(c.index, c.values, color="#12161b", lw=1.15, zorder=3)
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.grid(True, which="major", color="#dde3ea", lw=.7)
    ax.grid(True, which="minor", color="#dde3ea", lw=.35, alpha=.6)
    for sp in ("top", "right"): ax.spines[sp].set_visible(False)
    D = pd.to_datetime(j["dates"])
    for k, tr in r["trades"].items():
        for t in tr:
            a, b = D[t["e"]], D[t["x"]]
            ax.axvspan(a, b, color=COL[k], alpha=.07, zorder=1)
            ax.plot([a], [c.get(a, np.nan)], marker="^", ms=8, color=COL[k],
                    markeredgecolor="white", markeredgewidth=.8, zorder=5)
            if t["closed"]:
                ax.plot([b], [c.get(b, np.nan)], marker="v", ms=8,
                        color="#1f6b45" if t["ret"] >= 0 else "#a03028",
                        markeredgecolor="white", markeredgewidth=.8, zorder=5)
            ax.annotate(f"{k} {t['ret']:+.0f}%", (a, c.get(a, np.nan)),
                        textcoords="offset points", xytext=(0, -15), ha="center",
                        fontsize=8, fontweight="bold", color=COL[k], zorder=6)
    ax.set_title(f"{sym} · {r['name']}   ▲ 진입 / ▼ 청산(고점 −20%)   "
                 f"A={COL['A']} B={COL['B']} R6={COL['R6']}",
                 fontsize=10.5, loc="left", pad=8)
    fig.tight_layout()
    p = os.path.join(BASE, "results", "cases", f"sym_{sym}.png")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fig.savefig(p, facecolor="white"); plt.close(fig)
    print(f"→ {p}")
    t = pd.DataFrame(r["rows"])
    print(f"\n{sym} 신호 주차 {len(t)}건")
    print(t.to_string(index=False))


if __name__ == "__main__":
    a = sys.argv[1:] or ["build"]
    if a[0] == "build":
        cmd_build()
    else:
        cmd_chart(a[1].upper())
