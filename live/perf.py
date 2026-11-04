# -*- coding: utf-8 -*-
"""실전 원장 성과 — 원화 TSR·MDD vs 같은 날 같은 돈을 KODEX 200 에 넣은 가상 계좌.

입력은 봇이 남기는 것만 쓴다(사람이 따로 적지 않는다):
  - live/ledger.json  : 입금 [날짜, 원]
  - live/trades.jsonl : 체결 {day, sym, side, qty, px, fee}
  - 일봉 종가          : 보유했던 종목 + 069500(KODEX 200)

수익률은 '시간가중(TWR)' — 입금 시점·크기와 무관하게 운용 실력만 잰다(GIPS 표준).
손익(원)은 평가액 − 누적 입금. 연환산은 기록이 1년 넘을 때만 낸다(짧은 기간 연환산은 숫자 장난).

quantstats 를 쓰지 않는 이유: 배포 앱은 메모리 상한(약 1GB)에 이미 두 번 걸렸다. quantstats 는
matplotlib·seaborn·yfinance 를 함께 끌고 온다. 여기서 쓰는 지표 5개는 정의가 단순해 직접 계산하고,
tests/test_live_perf.py 에서 손으로 푼 정답과 맞춘다.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

LIVE = Path(__file__).resolve().parent
BENCH = "069500"   # KODEX 200


def load(sleeve: str = "KR"):
    L = json.loads((LIVE / "ledger.json").read_text(encoding="utf-8"))
    dep = [(str(d)[:10], float(a)) for d, a in L.get(sleeve, {}).get("deposits", [])]
    tr = []
    p = LIVE / "trades.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                tr.append(json.loads(line))
    return dep, tr


def syms_needed(trades) -> list[str]:
    return sorted({t["sym"] for t in trades})


def build(deposits, trades, px: pd.DataFrame, bench: pd.Series) -> pd.DataFrame:
    """일별 평가액. px: 날짜 × 종목 종가, bench: 069500 종가(같은 날짜 축).

    가정: 입금·체결은 그날 장중에 일어나고 평가는 그날 종가. 지수 계좌는 입금일 종가로 산다(소수 단위).
    """
    if not deposits:
        return pd.DataFrame()
    start = min(d for d, _ in deposits)
    idx = bench.index[bench.index >= pd.Timestamp(start)]
    px = px.reindex(idx).ffill()
    bench = bench.reindex(idx).ffill()
    dep_by = {}
    for d, a in deposits:
        dep_by[pd.Timestamp(d)] = dep_by.get(pd.Timestamp(d), 0.0) + a
    tr_by: dict = {}
    for t in trades:
        tr_by.setdefault(pd.Timestamp(t["day"]), []).append(t)

    def _snap(dt):   # 휴장일 입금·체결은 다음 거래일로
        j = idx.searchsorted(dt)
        return idx[min(j, len(idx) - 1)]
    dep_d, tr_d = {}, {}
    for k, v in dep_by.items():
        dep_d[_snap(k)] = dep_d.get(_snap(k), 0.0) + v
    for k, v in tr_by.items():
        tr_d.setdefault(_snap(k), []).extend(v)

    cash, sh, units, invested = 0.0, {}, 0.0, 0.0
    rows = []
    for dt in idx:
        f = dep_d.get(dt, 0.0)
        cash += f
        invested += f
        if f:
            units += f / bench[dt]
        for t in tr_d.get(dt, []):
            q, p, fee = float(t["qty"]), float(t["px"]), float(t.get("fee") or 0)
            if t["side"] == "BUY":
                sh[t["sym"]] = sh.get(t["sym"], 0.0) + q
                cash -= q * p + fee
            else:
                sh[t["sym"]] = sh.get(t["sym"], 0.0) - q
                cash += q * p - fee
        stock = 0.0
        for s, q in sh.items():
            if q:
                c = px[s][dt] if s in px.columns else np.nan
                if np.isnan(c):   # 가격을 못 받은 날은 마지막 체결가로(있는 척 0 으로 두지 않는다)
                    c = next((float(t["px"]) for t in reversed(trades) if t["sym"] == s and pd.Timestamp(t["day"]) <= dt), 0.0)
                stock += q * c
        rows.append(dict(date=dt, flow=f, invested=invested, cash=cash, stock=stock,
                         nav=cash + stock, bench_nav=units * bench[dt]))
    return pd.DataFrame(rows).set_index("date")


def twr_index(nav: pd.Series, flow: pd.Series) -> pd.Series:
    """시간가중 수익 지수(시작 1). 그날 입금은 장 시작 전에 들어왔다고 본다."""
    out, lvl, prev = [], 1.0, None
    for v, f in zip(nav.values, flow.values):
        base = (prev or 0.0) + f
        if prev is not None and base > 0:
            lvl *= v / base
        out.append(lvl)
        prev = v
    return pd.Series(out, index=nav.index)


def mdd(idx: pd.Series) -> float:
    if idx.empty:
        return 0.0
    return float((idx / idx.cummax() - 1).min())


def summary(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}, pd.Series(dtype=float), pd.Series(dtype=float)
    me =twr_index(df["nav"], df["flow"])
    bm = twr_index(df["bench_nav"], df["flow"])
    days = (df.index[-1] - df.index[0]).days
    out = dict(
        start=str(df.index[0].date()), end=str(df.index[-1].date()), days=days,
        invested=float(df["invested"].iloc[-1]), nav=float(df["nav"].iloc[-1]),
        bench_nav=float(df["bench_nav"].iloc[-1]),
        pnl=float(df["nav"].iloc[-1] - df["invested"].iloc[-1]),
        bench_pnl=float(df["bench_nav"].iloc[-1] - df["invested"].iloc[-1]),
        twr=float(me.iloc[-1] - 1), bench_twr=float(bm.iloc[-1] - 1),
        mdd=mdd(me), bench_mdd=mdd(bm),
        cash_share=float(df["cash"].iloc[-1] / df["nav"].iloc[-1]) if df["nav"].iloc[-1] else 1.0,
    )
    out["excess"] = out["twr"] - out["bench_twr"]
    if days >= 365:
        y = days / 365.25
        out["cagr"] = (1 + out["twr"]) ** (1 / y) - 1
        out["bench_cagr"] = (1 + out["bench_twr"]) ** (1 / y) - 1
    return out, me, bm
