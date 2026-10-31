# -*- coding: utf-8 -*-
"""관점 합의 가중 배분 — 사전 등록 research/consensus_alloc_prereg_2026-10-31.md 그대로 (2026-10-31, 차니 설계)

네 관점(투자회수·섹터 대장·모멘텀·주도주)이 각자 상위 N 을 뽑고, 여러 관점이 함께 뽑은 종목에 비중을 더 싣는다(C·C2).
같은 종목을 동일 가중(E)으로 담는 것보다 나은지, 그리고 '표 수가 많을수록 이후 수익이 높은지'를 잰다.
결과: results/consensus_alloc.json
"""
import os, sys, json, time
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
os.environ.setdefault("FACTOR_VER", "v13y")
import portfolio_rules_sim as S
import rs_accel_bt as B

A = S.A
OUT = os.path.join(ROOT, "results", "consensus_alloc.json")
EVERY, COST = 4, 0.003
LENSES = ["투자회수", "섹터 대장", "모멘텀", "주도주"]


def rs_rank(px, liq):
    r = {k: px / px.shift(k) - 1 for k in (13, 26, 39, 52)}
    sc = (0.4 * r[13] + 0.2 * r[26] + 0.2 * r[39] + 0.2 * r[52]).where(liq)
    return sc.rank(axis=1, pct=True) * 99


def build():
    d = A.load()
    M = A.matrices(d, ["close", "marcap", "adv_20d", "per", "opm", "ACC"])
    px = M["close"]
    liq = ((M["adv_20d"] >= A.MIN_ADV) & (M["marcap"] >= A.MIN_MC)).fillna(False)
    rs = rs_rank(px, liq)
    acc13 = (M["ACC"] == 1).fillna(False).astype(float).rolling(13, min_periods=1).max() > 0
    ta13 = B.turnaround(d, px).astype(float).rolling(13, min_periods=1).max() > 0
    ey = (1 / M["per"]).where((M["per"] > 0) & (M["opm"] > 0) & liq)
    dom = pd.read_csv(os.path.join(ROOT, "data", "us_domicile.csv"))
    sic2 = (dom.set_index("sym").sic // 100).reindex(px.columns)
    spy = S.load_spy(px.index)
    return px, liq, rs, acc13 | ta13, ey, sic2, spy


def picks_at(t, N, rs, lead, ey, sic2, liq):
    r = rs.loc[t].dropna()
    out = {}
    out["투자회수"] = list(ey.loc[t].dropna().sort_values(ascending=False).index[:N])
    g = pd.DataFrame(dict(rs=r, sec=sic2.reindex(r.index))).dropna()
    big = g.groupby("sec").rs.transform("size") >= 10
    top = g[big & (g.rs >= 50)].sort_values("rs", ascending=False).groupby("sec").head(1)
    out["섹터 대장"] = list(top.index[:N])
    out["모멘텀"] = list(r.sort_values(ascending=False).index[:N])
    ld = r[(r >= 80) & lead.loc[t].reindex(r.index).fillna(False)]
    out["주도주"] = list(ld.sort_values(ascending=False).index[:N])
    return out


def cap_w(raw, cap):
    w = raw / raw.sum()
    for _ in range(50):
        over = w > cap + 1e-12
        if not over.any():
            break
        ex = (w[over] - cap).sum()
        w[over] = cap
        free = ~over & (w < cap)
        if not free.any():
            break
        w[free] += ex * w[free] / w[free].sum()
    return w / w.sum()


def target(pk, mode, cap, lenses=LENSES):
    votes = {}
    for L in lenses:
        for s in pk[L]:
            votes[s] = votes.get(s, 0) + 1
    if not votes:
        return pd.Series(dtype=float)
    v = pd.Series(votes, dtype=float)
    if mode == "E":
        return v * 0 + 1 / len(v)
    raw = v if mode == "C" else v ** 2
    return cap_w(raw, cap) if len(v) * cap >= 1 else raw / raw.sum()


def simulate(px, tw, shock=0.0):
    """tw: {리밸런싱 신호 주 인덱스: 목표 비중 Series}. 다음 주 종가 체결. 상폐 뒤 수익 0."""
    R = px.pct_change(fill_method=None).fillna(0.0).values
    cols = {s: i for i, s in enumerate(px.columns)}
    w = np.zeros(px.shape[1]); v = 1.0
    start = min(tw)
    vals, idx = [], []
    pend = None
    for i in range(start, len(px)):
        w = w * (1 + R[i]); g = w.sum()
        v *= g if g > 0 else 1.0
        if g > 0:
            w = w / g
        if pend is not None:                 # 지난주 신호 → 이번 주 종가 체결
            new = np.zeros_like(w)
            for s, x in pend.items():
                new[cols[s]] = x
            v *= 1 - np.abs(new - w).sum() * COST
            w = new; pend = None
        if (i - 0) in tw:
            pend = tw[i]
        if shock:
            v *= (1 - shock) ** (1 / 52)
        vals.append(v); idx.append(px.index[i])
    return pd.Series(vals, index=idx)


def summary(v, spy):
    st, _ = S.stats(v, spy)
    sub = v[(v.index >= "2014-01-01") & (v.index < "2020-01-01")]
    st["y14_19"] = S.stats(sub)[0]["CAGR"] if len(sub) > 52 else None
    return st


def main():
    t0 = time.time()
    px, liq, rs, lead, ey, sic2, spy = build()
    # 첫 신호 가능 주(네 관점 모두 종목이 나오는 첫 주)부터, 4주 간격
    first = None
    for i in range(len(px)):
        pk = picks_at(px.index[i], 20, rs, lead, ey, sic2, liq)
        if all(len(pk[L]) >= 5 for L in LENSES):
            first = i; break
    reb = list(range(first, len(px) - 1, EVERY))
    print(f"[데이터] {px.shape} · 평가 시작 {px.index[first].date()} · 리밸런싱 {len(reb)}회 · {time.time()-t0:.0f}s")
    PK = {N: {i: picks_at(px.index[i], N, rs, lead, ey, sic2, liq) for i in reb} for N in (10, 20, 30)}
    print(f"[관점] 계산 {time.time()-t0:.0f}s")

    # 1) 겹침 + 표 수별 이후 13주
    jac, fw = [], []
    for i in reb:
        pk = PK[20][i]
        for a in range(4):
            for b in range(a + 1, 4):
                x, y = set(pk[LENSES[a]]), set(pk[LENSES[b]])
                if x | y:
                    jac.append(dict(pair=f"{LENSES[a]}×{LENSES[b]}", j=len(x & y) / len(x | y)))
        if i + 14 < len(px):
            votes = {}
            for L in LENSES:
                for s in pk[L]:
                    votes[s] = votes.get(s, 0) + 1
            for s, n in votes.items():
                seg = px[s].iloc[i + 1:i + 15].dropna()          # 상폐면 마지막 가격
                if len(seg) and seg.iloc[0] > 0:
                    fw.append(dict(votes=min(n, 3), r=seg.iloc[-1] / seg.iloc[0] - 1))
    J = pd.DataFrame(jac).groupby("pair").j.mean().round(3).to_dict()
    F = pd.DataFrame(fw).groupby("votes").r.agg(["mean", "median", "count"])
    F = {int(k): dict(mean=round(r["mean"] * 100, 2), median=round(r["median"] * 100, 2), n=int(r["count"])) for k, r in F.iterrows()}
    vote_share = {k: v["n"] for k, v in F.items()}
    print("[겹침]", J); print("[표 수별 13주]", F)

    # 2) 변형
    res, curves = {}, {}
    for N in (10, 20, 30):
        for mode, caps in (("E", [None]), ("C", [0.08, 0.10, 0.15]), ("C2", [0.08, 0.10, 0.15])):
            for cap in caps:
                tw = {i: target(PK[N][i], mode, cap or 1.0) for i in reb}
                v = simulate(px, tw)
                key = f"{mode}|N{N}|cap{int(cap*100) if cap else '-'}"
                res[key] = summary(v, spy)
                if N == 20 and cap in (None, 0.10):
                    res[key + "|shock1"] = summary(simulate(px, tw, shock=0.01), spy)
                    curves[mode] = v
    for L in LENSES:
        tw = {i: target(PK[20][i], "E", 1.0, lenses=[L]) for i in reb}
        res[f"단독|{L}"] = summary(simulate(px, tw), spy)
    sp = spy.reindex(curves["E"].index).ffill()
    res["SPY"] = summary(sp / sp.iloc[0], None)
    print(f"[변형] {time.time()-t0:.0f}s")

    # 3) 판정(사전 등록 4조건)
    verdict = {}
    for mode in ("C", "C2"):
        c, e = res[f"{mode}|N20|cap10"], res["E|N20|cap-"]
        c1 = c["CAGR"] > e["CAGR"] and c["Sharpe"] >= e["Sharpe"]
        c2 = (c["y14_19"] or -99) >= (e["y14_19"] or -99)
        wins = sum(res[f"{mode}|N{N}|cap{k}"]["CAGR"] > res[f"E|N{N}|cap-"]["CAGR"] for N in (10, 20, 30) for k in (8, 10, 15))
        c3 = wins >= 5
        m = [F.get(k, {}).get("mean") for k in (1, 2, 3)]
        c4 = all(x is not None for x in m) and m[0] < m[1] < m[2]
        verdict[mode] = dict(c1_cagr_sharpe=c1, c2_2014_19=c2, c3_neighbors=f"{wins}/9", c3=c3, c4_votes_monotonic=c4,
                             passed=bool(c1 and c2 and c3 and c4))
    print("[판정]", verdict)
    every = 4
    eq = {k: [[str(t.date()), round(float(x), 4)] for t, x in s.iloc[::every].items()] for k, s in curves.items()}
    eq["SPY"] = [[str(t.date()), round(float(x), 4)] for t, x in (sp / sp.iloc[0]).iloc[::every].items()]
    json.dump(dict(asof=str(pd.Timestamp.today().date()), window=[str(px.index[first].date()), str(px.index[-1].date())],
                   prereg="research/consensus_alloc_prereg_2026-10-31.md", overlap_jaccard=J, votes_fwd13=F,
                   results=res, verdict=verdict, curves=eq,
                   note="미국 v13y · 4주 리밸런싱 · 1주 지연 · 편도 0.3% · 상폐 뒤 수익 0(충격 1% 버전 별도)"),
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1,
              default=lambda o: o.item() if hasattr(o, "item") else str(o))   # numpy bool 이 JSON 을 중간에 끊었다(10-31 1차)
    print(f"끝 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
