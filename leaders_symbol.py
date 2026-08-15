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

RULES = {
    "A": ("이익폭증 & PER<20 & RS13>1.5",
          lambda d: (d.b_any == 1) & (d.per > 0) & (d.per < 20) & (d.rs_13w > 1.5) &
                    (d.adv_20d >= 1e6)),
    "B": ("(흑자전환 OR 이익폭증) & RS13>1.7",
          lambda d: ((d.op_turn == 1) | (d.b_any == 1)) & (d.rs_13w > 1.7) &
                    (d.adv_20d >= 1e6)),
    "R6": ("RS13>1.5 & (흑자전환 OR 이익폭증) & OPM>0 · $2B+",
           lambda d: (d.rs_13w > 1.5) & (d.opm > 0) &
                     ((d.op_turn == 1) | (d.b_any == 1)) &
                     (d.marcap >= 2e9) & (d.adv_20d >= 5e6)),
}
BO = {"b_ophigh": "영업익신고점", "b_nihigh": "순익신고점",
      "b_opjump": "영업익QoQ50", "b_opmjump": "OPM_QoQ3"}


def load():
    import leaders_boost as B
    d = B.build()
    d["as_of"] = pd.to_datetime(d.as_of)
    c = sqlite3.connect(os.path.join(BASE, "data", "market.db"))
    ex = pd.read_sql("SELECT as_of,sym,name,rs_26w,mdd_52w,vol_x_20w "
                     "FROM factor_weekly WHERE factor_ver='v1'", c)
    c.close()
    ex["as_of"] = pd.to_datetime(ex.as_of)
    return d.merge(ex, on=["as_of", "sym"], how="left")


def simulate(sig, close):
    """신호 → 진입, 주봉 종가 고점 대비 −20% → 청산. 청산 뒤 재신호면 재진입."""
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
                if close[j] <= peak * (1 - TRAIL):
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
    d = d[d.as_of <= "2026-08-10"]
    # 전방 수익률 — "그 주에 걸린 신호가 이후 어떻게 됐나"를 주차별 조회에서 보려면 필요하다.
    px = d.pivot(index="as_of", columns="sym", values="close").sort_index()
    for h in (13, 26, 52):
        f = (px.shift(-h) / px - 1).stack().rename(f"f{h}").reset_index()
        d = d.merge(f, on=["as_of", "sym"], how="left")
    dates = sorted(d.as_of.unique())
    di = {t: k for k, t in enumerate(dates)}
    flags = {k: fn(d) for k, (_, fn) in RULES.items()}
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
        for k, (_, fn) in RULES.items():
            m = fn(g).fillna(False).values
            if not m.any():
                continue
            rec["sig"][k] = [int(idx[p]) for p in np.where(m)[0]]
            tr = []
            for t in simulate(m, close):
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
            rec["rows"].append(dict(
                d=str(pd.Timestamp(r.as_of).date()),
                r=[k for k in RULES if k in rec["sig"] and di[r.as_of] in rec["sig"][k]],
                close=round(float(r.close), 2),
                rs13=_r(r.rs_13w), rs26=_r(r.rs_26w), opm=_r(r.opm), opmq=_r(r.opm_qoq),
                per=_r(r.per), psr=_r(r.psr), dist=_r(r.dist_52w), mdd=_r(r.mdd_52w),
                vol=_r(r.vol_x_20w), rev=_r(r.rev_yoy),
                mc=_r(r.marcap / 1e9, 2), adv=_r(r.adv_20d / 1e6, 0),
                f13=_r(r.f13 * 100, 1), f26=_r(r.f26 * 100, 1), f52=_r(r.f52 * 100, 1),
                trg=" ".join((["흑자전환"] if r.op_turn == 1 else []) +
                             [v for kk, v in BO.items() if r.get(kk) == 1]) or "-"))
        syms[s] = rec

    out = dict(generated=str(pd.Timestamp.today().date()),
               dates=[str(pd.Timestamp(t).date()) for t in dates],
               rules={k: v[0] for k, v in RULES.items()},
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
    COL = {"A": "#17415c", "B": "#a03028", "R6": "#8a6a12"}
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
