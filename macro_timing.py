# -*- coding: utf-8 -*-
"""매크로 신호로 시장을 이겼나 (2026-11-08, 차니 "매크로 지표로 시장을 이기는 수익을 낼 수 있었는지 확인할 정보를")

같은 지수를 ① 그냥 들고 있기 ② 신호가 켜졌을 때만 들고 나머지는 현금 — 으로 비교한다.
  · 미국 = S&P500 배당 포함(SPXTR, 1988~), 현금 = 3개월 국채(TB3MS) · 한국 = 코스피(가격지수, 1997~), 현금 이자 0(보수적)
  · 신호: 지수 200일선(일봉, 다음 날 체결) · 주봉 5주선 · 주봉 10주선(다음 주 체결) · 4계절 v2(🌱☀️ 보유 · 🍂❄️ 현금, 월말 판정 → 다음 달)
  · 전환마다 비용 0.1%
판정 문구는 숫자로만: '수익도 낙폭도 이겼나'. 결론을 미리 정하지 않는다.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
PX = os.path.join(ROOT, "data", "research", "macro_long_px.parquet")
FRED = os.path.join(ROOT, "data", "research", "macro_long_fred.parquet")
COST = 0.001


def _stats(r: pd.Series, per_year: float):
    r = r.dropna()
    if len(r) < 10:
        return None
    eq = (1 + r).cumprod()
    yrs = len(r) / per_year
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    mdd = (eq / eq.cummax() - 1).min()
    vol = r.std() * np.sqrt(per_year)
    return dict(CAGR=round(cagr * 100, 2), MDD=round(mdd * 100, 2), Sharpe=round((r.mean() * per_year) / vol, 2) if vol else None,
                eq=eq)


def _cash_daily(idx):
    try:
        f = pd.read_parquet(FRED)
        tb = f[f.sid == "TB3MS"].set_index("date").v.astype(float)
        tb.index = pd.to_datetime(tb.index)
        return (tb.reindex(idx, method="ffill").fillna(0) / 100 / 252).values
    except Exception:
        return np.zeros(len(idx))


def _run(px: pd.Series, on: pd.Series, cash: np.ndarray, per_year: float):
    """on: 그 봉 종가 기준 신호(True = 보유) → 다음 봉 수익에 적용."""
    r = px.pct_change()
    pos = on.astype(bool).shift(1, fill_value=False)
    sw = pos.astype(int).diff().abs().fillna(0)
    sr = np.where(pos, r, cash) - sw * COST
    return pd.Series(sr, index=px.index).iloc[1:], float(pos.mean()), int(sw.sum())


def table(season_hist: pd.DataFrame | None = None, kr_season_hist: pd.DataFrame | None = None, start: str | None = None):
    P = pd.read_parquet(PX)
    rows = []
    for mk, col, cash_on in (("🇺🇸 S&P500(배당 포함)", "SPXTR", True), ("🇰🇷 코스피", "KOSPI", False)):
        px = P[col].dropna()
        if start:
            px = px[px.index >= start]
        cash = _cash_daily(px.index) if cash_on else np.zeros(len(px))
        bh = _stats(px.pct_change().iloc[1:], 252)
        base = dict(시장=mk, 전략="그냥 보유", **{k: bh[k] for k in ("CAGR", "MDD", "Sharpe")}, 노출=100.0, 전환=0,
                    기간=f"{px.index[0]:%Y-%m}~{px.index[-1]:%Y-%m}")
        rows.append(base)
        cands = []
        ma200 = px.rolling(200, min_periods=200).mean()
        cands.append(("200일선 위에서만 보유", _run(px, (px > ma200) & ma200.notna(), cash, 252), 252))
        w = px.resample("W-FRI").last().dropna()
        cw = (pd.Series(cash, index=px.index).resample("W-FRI").sum().reindex(w.index).fillna(0).values)
        for n in (5, 10):
            ma = w.rolling(n, min_periods=n).mean()
            cands.append((f"주봉 {n}주선 위에서만 보유", _run(w, (w > ma) & ma.notna(), cw, 52), 52))
        sh = season_hist if col == "SPXTR" else kr_season_hist
        if sh is not None and len(sh):
            m = px.resample("ME").last().dropna()
            cm = pd.Series(cash, index=px.index).resample("ME").sum().reindex(m.index).fillna(0).values
            ph = sh["phase"].reindex(m.index, method="ffill")
            on = ph.isin(["FIN", "EARN"]) & ph.notna()
            cands.append(("4계절: 🌱금융·☀️실적만 보유", _run(m, on, cm, 12), 12))
        for name, (sr, expo, nsw), py in cands:
            s = _stats(sr, py)
            # 그냥 보유도 같은 주기·같은 구간으로 다시 재서 비교(일·주·월 표본 차이 제거)
            ref = px.resample({252: "D", 52: "W-FRI", 12: "ME"}[py]).last().dropna() if py != 252 else px
            b2 = _stats(ref.pct_change().loc[sr.index[0]:], py)
            beat = (s["CAGR"] > b2["CAGR"], s["MDD"] > b2["MDD"])
            rows.append(dict(시장=mk, 전략=name, CAGR=s["CAGR"], MDD=s["MDD"], Sharpe=s["Sharpe"], 노출=round(expo * 100, 1), 전환=nsw,
                             기간=f"{sr.index[0]:%Y-%m}~{sr.index[-1]:%Y-%m}",
                             판정=("✅ 수익·낙폭 모두 이김" if all(beat) else "🟡 낙폭만 줄임" if beat[1] else "🟡 수익만 이김" if beat[0] else "❌ 둘 다 못 이김"),
                             **{"보유 대비 수익(%p)": round(s["CAGR"] - b2["CAGR"], 2), "보유 대비 낙폭(%p)": round(s["MDD"] - b2["MDD"], 2)}))
    return pd.DataFrame(rows)
