# -*- coding: utf-8 -*-
"""
주도주 탈출 타이밍 (4단계) — 청산 규칙 대결

진입은 현행 L/S 규칙으로 고정하고 **청산만** 바꿔 겨룬다. 두 층위로 잰다.
  · 트레이드 층위 (n=수백)  — 표본이 사는 곳. 승률·손익비·포착률
  · 포트폴리오 층위 (n=열몇) — 확인용. L 은 8년간 슬롯 경쟁이 16주뿐이라
                              여기서 고르면 열 몇 번의 판단에 과적합된다

워크포워드: 앞구간 2019-01~2021-12 에서 고르고 뒤구간 2022-01~ 에서 검증.
(2018 년은 재무 8분기 롤링이 안 차는 예열 구간이라 뺀다 — 2026-08-16 확인)

포착률(capture) = 실현수익 ÷ 그 트레이드가 도달했던 최대수익.
  트레일 -30% 는 정의상 고점의 70% 만 남기고 나온다. 이걸 안 재면
  "언제 팔았어야 했나"에 답할 수 없다.
"""
import os, sys, json
import numpy as np
import pandas as pd
import leaders_ab as AB
import leaders_uturn2 as U2

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.abspath(__file__))
pd.set_option("display.width", 280, "display.max_columns", 60)
FEE = 0.001
SEG = {"앞 2019~2021": ("2019-01-01", "2021-12-31"),
       "뒤 2022~2026": ("2022-01-01", "2026-12-31"),
       "전체 2019~":   ("2019-01-01", "2026-12-31")}


# ── 청산 규칙 ───────────────────────────────────────────────────────
# st: 포지션 상태 dict, ctx: 그 주의 시장·종목 값
def ex_trail(x):
    def f(v, st, c):
        return v <= st["peak"] * (1 - x)
    f.__doc__ = f"고점 대비 -{x:.0%} 고정 트레일"
    return f


def ex_ma(n, k=1):
    def f(v, st, c):
        m = c[f"ma{n}"]
        st["below"] = st.get("below", 0) + 1 if (m == m and v < m) else 0
        return st["below"] >= k
    f.__doc__ = f"{n}주선 종가 이탈 {k}주 연속"
    return f


def ex_both(x, n, k=1):
    a, b = ex_trail(x), ex_ma(n, k)
    f = lambda v, st, c: a(v, st, c) | b(v, st, c)
    f.__doc__ = f"트레일 -{x:.0%} 또는 {n}주선 이탈 {k}주"
    return f


def ex_regime(tight, wide, thr=-0.05):
    """시장이 멀쩡한데 혼자 빠지면 = 개별 U턴 → 타이트. 시장 조정이면 → 넓게.
       (3단계 반응곡선: SPY 신고가 부근의 -20% 는 이후 -11%, 시장조정 중이면 +18%)"""
    def f(v, st, c):
        x = tight if (c["spy_dd"] == c["spy_dd"] and c["spy_dd"] > thr) else wide
        return v <= st["peak"] * (1 - x)
    f.__doc__ = f"시장 조건부 트레일 (SPY>{thr:.0%}면 -{tight:.0%}, 아니면 -{wide:.0%})"
    return f


def ex_para(x, gap):
    """포물선 꼭지 청산 — 고점 대비 -x% 인데 아직 20주선보다 gap 이상 위면 하락 여지가 남았다."""
    def f(v, st, c):
        m = c["ma20"]
        if v <= st["peak"] * (1 - x) and m == m and v > m * (1 + gap):
            return True
        return v <= st["peak"] * (1 - 0.30)          # 안전망은 현행 유지
    f.__doc__ = f"고점 -{x:.0%} & 20주선 +{gap:.0%} 초과 → 청산 (안전망 -30%)"
    return f


def ex_time(w, x=0.30):
    def f(v, st, c):
        return st["wk"] >= w or v <= st["peak"] * (1 - x)
    f.__doc__ = f"{w}주 시간청산 (안전망 -{x:.0%})"
    return f


# ── 엔진 ────────────────────────────────────────────────────────────
def sim(M, gate, N, exit_fn, a, b, spy_dd):
    px = M["close"]
    dates = px.index[(px.index >= a) & (px.index <= b)]
    cash, pos, eq, trades = 1.0, {}, [], []
    W = 1.0 / N
    ctxcols = ["ma10", "ma20", "rs_13w", "ACC"]   # M 에 있는 것만 실림
    for t in dates:
        p = px.loc[t]
        rows = {c: M[c].loc[t] for c in ctxcols if c in M}
        sd = spy_dd.get(t, np.nan)
        for s in list(pos):
            v = p.get(s)
            if v is None or v != v:
                continue
            o = pos[s]
            o["peak"] = max(o["peak"], v)
            o["mx"] = max(o["mx"], v / o["entry"] - 1)
            o["wk"] += 1
            c = {k: rows[k].get(s, np.nan) for k in rows}
            c["spy_dd"] = sd
            if exit_fn(v, o, c):
                cash += o["sh"] * v * (1 - FEE)
                trades.append(dict(sym=s, ed=o["ed"], xd=str(t.date()), wk=o["wk"],
                                   ret=v / o["entry"] * (1 - FEE) ** 2 - 1, mx=o["mx"]))
                del pos[s]
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
                pos[s] = dict(sh=amt / p[s] * (1 - FEE), peak=p[s], last=p[s],
                              entry=float(p[s]), ed=str(t.date()), wk=0, mx=0.0)
        for s, o in pos.items():
            v = p.get(s)
            if v == v and v is not None:
                o["last"] = v
        eq.append((t, cash + sum(o["sh"] * o["last"] for o in pos.values())))
    e = pd.Series(dict(eq))
    for s, o in pos.items():                       # 미청산분도 트레이드로 계상
        trades.append(dict(sym=s, ed=o["ed"], xd="열림", wk=o["wk"],
                           ret=o["last"] / o["entry"] - 1, mx=o["mx"]))
    return e, pd.DataFrame(trades)


def stat(e, T, yrs):
    mult = e.iloc[-1] / e.iloc[0]
    mdd = (e / e.cummax() - 1).min()
    cagr = mult ** (1 / yrs) - 1
    if len(T):
        win = (T.ret > 0).mean()
        pl = (T[T.ret > 0].ret.mean() / abs(T[T.ret <= 0].ret.mean())
              if (T.ret <= 0).any() and (T.ret > 0).any() else np.nan)
        cap = (T.ret / T.mx.replace(0, np.nan)).clip(-3, 3).median()
    else:
        win = pl = cap = np.nan
    return dict(배수=mult, CAGR=cagr, MDD=mdd, 회복=cagr / abs(mdd) if mdd else np.nan,
                n=len(T), 승률=win, 손익비=pl, 포착률=cap, 보유주=T.wk.median() if len(T) else np.nan)


def main():
    M, spy = U2.panel()
    spy_dd = spy / spy.rolling(52, min_periods=8).max() - 1
    key = sys.argv[1] if len(sys.argv) > 1 else "L"
    N = AB.RULES[key]["slots"]
    gate = AB.gate_of(M, key)
    rules = [("현행 트레일 -30%" if key == "L" else "현행 트레일 -40%",
              ex_trail(AB.RULES[key]["trail"]))]
    rules += [(f"트레일 -{x:.0%}", ex_trail(x)) for x in (0.15, 0.20, 0.25, 0.35, 0.40)]
    rules += [("20주선 이탈", ex_ma(20)), ("20주선 이탈 2주", ex_ma(20, 2)),
              ("10주선 이탈 2주", ex_ma(10, 2)),
              ("트레일-25% or 20주선", ex_both(0.25, 20)),
              ("트레일-30% or 20주선2주", ex_both(0.30, 20, 2)),
              ("시장조건부 20/40", ex_regime(0.20, 0.40)),
              ("시장조건부 15/35", ex_regime(0.15, 0.35)),
              ("포물선꼭지 -20%/+25%", ex_para(0.20, 0.25)),
              ("포물선꼭지 -15%/+20%", ex_para(0.15, 0.20)),
              ("26주 시간청산", ex_time(26)), ("52주 시간청산", ex_time(52))]

    for seg, (a, b) in SEG.items():
        yrs = (pd.Timestamp(min(b, "2026-08-24")) - pd.Timestamp(a)).days / 365.25
        print(f"\n═══ 규칙 {key} · {seg} ═══")
        print(f"{'청산규칙':<24}{'배수':>7}{'CAGR':>8}{'MDD':>8}{'회복':>7}"
              f"{'n':>5}{'승률':>7}{'손익비':>7}{'포착률':>7}{'보유주':>7}")
        for nm, fn in rules:
            e, T = sim(M, gate, N, fn, a, b, spy_dd)
            s = stat(e, T, yrs)
            print(f"{nm:<24}{s['배수']:>7.2f}{s['CAGR']:>8.1%}{s['MDD']:>8.1%}"
                  f"{s['회복']:>7.2f}{s['n']:>5.0f}{s['승률']:>7.0%}"
                  f"{s['손익비']:>7.1f}{s['포착률']:>7.0%}{s['보유주']:>7.0f}")


if __name__ == "__main__":
    main()
