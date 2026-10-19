# -*- coding: utf-8 -*-
"""
욕심 조절 신호 백테스트 — 매크로 리스크 온/오프 (2026-10-20)

사전 등록: research/macro_regime_prereg_2026-10-20.md (결과 보기 전에 커밋 391c6e0 · 리베이스 전 b410f71)
데이터:    data/research/macro_long_{fred,px}.parquet  (tools/fetch_macro_long.py)

무엇을 재나
  S&P500 총수익(^SP500TR) 주봉에 노출 비중(0~1)을 곱하고 나머지는 3개월 국채 이자.
  B0 매수보유 · B1 200일선 스위치 · 후보 신호 C1~C9 를 (a) 단독 (b) B1 위에 덧씌워 비교한다.

시차 처리 (미래를 보지 않기 위해)
  · 신호는 금요일 종가에 판정 → **다음 주** 수익률에 적용(1주 지연)
  · 일간 지표: 그 금요일까지 값 · 주간 지표(ICSA·NFCI): 7일 뒤부터 사용
  · 월간 지표: 월초 날짜 + 1개월 + 15일 뒤부터 사용
    (사전 등록 '1개월'보다 보수적 — 월초 날짜 표기라 +1개월만 밀면 실업률은 약 1주, 산업생산은 약 2주 미리 보게 된다)

CLI
  python research/macro_regime_bt.py            → 표 출력 + research/macro_regime_bt_2026-10-20.csv
"""
import os
import sys

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RD = os.path.join(BASE, "data", "research")
COST = 0.001
START, END = "1988-01-01", "2026-09-30"
PERIODS = {"A 1988-2007": ("1988-01-01", "2007-12-31"),
           "B 2008-2019": ("2008-01-01", "2019-12-31"),
           "C 2020-2026": ("2020-01-01", END)}


# ── 데이터 ───────────────────────────────────────────────────────────
def load():
    f = pd.read_parquet(os.path.join(RD, "macro_long_fred.parquet"))
    fred = {k: g.set_index("date")["v"].sort_index() for k, g in f.groupby("sid")}
    px = pd.read_parquet(os.path.join(RD, "macro_long_px.parquet"))
    return fred, px


def weekly_index(px):
    d = px["SPX"].dropna()
    return d.resample("W-FRI").last().dropna().index


def asof(s, idx, lag_days=0, lag_months=0):
    """s 의 값을 '알 수 있게 된 날' 기준으로 idx(금요일)에 맞춘다."""
    s = s.dropna().copy()
    if lag_months:
        s.index = s.index + pd.DateOffset(months=lag_months)
    if lag_days:
        s.index = s.index + pd.Timedelta(days=lag_days)
    s = s[~s.index.duplicated(keep="last")]
    return s.reindex(s.index.union(idx)).ffill().reindex(idx)


def monthly(s, idx):
    return asof(s, idx, lag_days=15, lag_months=1)


def pct_rank_trailing(s, win):
    """직전 win 개 관측 대비 현재 값의 백분위(0~100). 미래를 쓰지 않는다."""
    return s.rolling(win, min_periods=win // 2).apply(lambda a: (a <= a[-1]).mean() * 100, raw=True)


# ── 신호 ─────────────────────────────────────────────────────────────
def build(fred, px):
    idx = weekly_index(px)
    spx_d = px["SPX"].dropna()
    ma200 = spx_d.rolling(200).mean()
    spx_w = spx_d.reindex(spx_d.index.union(idx)).ffill().reindex(idx)
    ma200_w = ma200.reindex(ma200.index.union(idx)).ffill().reindex(idx)
    ma40w = spx_w.rolling(40).mean()
    tr = px["SPXTR"].dropna()
    tr_w = tr.reindex(tr.index.union(idx)).ffill().reindex(idx)

    D = pd.DataFrame(index=idx)
    D["ret"] = tr_w.pct_change()
    # SPXTR 이전(1988 이전)은 쓰지 않는다 — 기간 시작이 1988
    D["cash"] = asof(fred["DTB3"], idx) / 100 / 52
    D["above200"] = (spx_w > ma200_w).astype(float)
    D["above40w"] = (spx_w > ma40w).astype(float)
    D["mom12"] = spx_w / spx_w.shift(52) - 1
    hi52, lo52 = spx_w.rolling(52).max(), spx_w.rolling(52).min()
    D["pos52"] = (spx_w - lo52) / (hi52 - lo52) * 100

    # 원재료
    baa = asof(fred["BAA10Y"], idx)
    nfci = asof(fred["NFCI"], idx, lag_days=7)
    icsa = fred["ICSA"].rolling(4).mean()
    icsa_w = asof(icsa, idx, lag_days=7)
    ur = fred["UNRATE"]; ur3 = ur.rolling(3).mean()
    sahm_m = ur3 - ur3.shift(1).rolling(12).min()
    sahm = monthly(sahm_m, idx)
    t10y3m = asof(fred["T10Y3M"], idx)
    ff = fred["FEDFUNDS"]; fed6 = monthly(ff - ff.shift(6), idx)
    ip = fred["INDPRO"]; ipy = monthly((ip / ip.shift(12) - 1) * 100, idx)
    vix = asof(fred["VIXCLS"], idx)
    dxy_d = px["DXY"].dropna()
    dxy = dxy_d.reindex(dxy_d.index.union(idx)).ffill().reindex(idx)
    dxy200 = dxy_d.rolling(200).mean(); dxy200 = dxy200.reindex(dxy200.index.union(idx)).ffill().reindex(idx)

    R = dict(baa=baa, nfci=nfci, icsa=icsa_w, sahm=sahm, t10y3m=t10y3m, fed6=fed6, ipy=ipy, vix=vix,
             dxy=dxy, dxy200=dxy200)
    return D, R


def sig_C1(R, thr=0.30, win=13):
    return (R["baa"] - R["baa"].shift(win) >= thr).astype(float)

def sig_C2(R, thr=0.0):
    return (R["nfci"] > thr).astype(float)

def sig_C3(R, thr=0.15):
    lo = R["icsa"].rolling(52, min_periods=26).min()
    return (R["icsa"] / lo - 1 >= thr).astype(float)

def sig_C4(R, thr=0.5):
    return (R["sahm"] >= thr).astype(float)

def sig_C5(R):
    return (R["t10y3m"] < 0).astype(float)

def uragami(D, R):
    """대시보드 macro_regime() 과 같은 규칙을 주봉으로 재현."""
    fed6, ip, sahm = R["fed6"], R["ipy"], R["sahm"]
    rate = np.where(fed6 <= -0.25, "하락", np.where(fed6 >= 0.25, "상승", "횡보"))
    growth = np.where(ip >= 1.0, "개선", np.where(ip <= -1.0, "악화", "횡보"))
    growth = np.where(sahm >= 0.5, "악화", growth)
    up = (D["above200"] > 0) & (D["mom12"] > 0)
    px = np.where(up, "상승", "하락")
    sc = pd.DataFrame(index=D.index)
    sc["FIN"] = (rate == "하락") * 2 + np.isin(growth, ["악화", "횡보"]) * 1 + (px == "상승") * 2
    sc["EARN"] = np.isin(rate, ["횡보", "상승"]) * 1 + (growth == "개선") * 2 + (px == "상승") * 2
    sc["RFIN"] = (rate == "상승") * 2 + np.isin(growth, ["개선", "횡보"]) * 1 + (px == "하락") * 2
    sc["RERN"] = (growth == "악화") * 2 + (px == "하락") * 2 + (rate == "하락") * 1
    return sc.idxmax(axis=1)

def sig_C6(D, R):
    ph = uragami(D, R)
    return ph.isin(["RFIN", "RERN"]).astype(float)

def pendulum(D, R):
    parts = pd.concat([100 - pct_rank_trailing(R["baa"], 520),     # 하이일드 장기 대용: Baa 스프레드(10년 창)
                       100 - pct_rank_trailing(R["vix"], 520),
                       D["pos52"]], axis=1)
    return parts.mean(axis=1, skipna=True)

def sig_C7(D, R, thr=80):
    return (pendulum(D, R) >= thr).astype(float)

def sig_C8(R):
    return ((R["dxy"] > R["dxy200"]) & (R["dxy"] - R["dxy"].shift(13) > 0)).astype(float)


# ── 시뮬레이션 ───────────────────────────────────────────────────────
def run(D, expo):
    """expo[t] = t 주 금요일 판정 노출 → t+1 주 수익률에 적용."""
    e = expo.shift(1).fillna(1.0).clip(0, 1)
    r = e * D["ret"] + (1 - e) * D["cash"] - COST * e.diff().abs().fillna(0)
    return r, e

def stats(r, e):
    r = r.dropna()
    if len(r) < 52:
        return {}
    eq = (1 + r).cumprod()
    yrs = len(r) / 52.18
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    mdd = (eq / eq.cummax() - 1).min()
    vol = r.std() * np.sqrt(52)
    return dict(CAGR=round(cagr * 100, 2), MDD=round(mdd * 100, 1),
                Calmar=round(cagr / abs(mdd), 3) if mdd < 0 else np.nan,
                Sharpe=round((r.mean() * 52) / vol, 2) if vol else np.nan,
                노출=round(e.reindex(r.index).mean() * 100), 변경_연=round((e.reindex(r.index).diff().abs() > 0).sum() / yrs, 1))

def evaluate(D, expo, label):
    rows = []
    for pname, (a, b) in [("전체", (START, END))] + list(PERIODS.items()):
        sl = D.loc[a:b]
        r, e = run(sl, expo.loc[a:b])
        rows.append(dict(신호=label, 구간=pname, **stats(r, e)))
    return rows


def main():
    fred, px = load()
    D, R = build(fred, px)
    D = D.loc[START:END]
    R = {k: v.loc[START:END] for k, v in R.items()}
    one = pd.Series(1.0, index=D.index)
    B1 = D["above200"]

    signals = {
        "C1 신용 13주 +0.30": sig_C1(R), "C1 주변 +0.20": sig_C1(R, 0.20), "C1 주변 +0.40": sig_C1(R, 0.40),
        "C1 주변 8주": sig_C1(R, 0.30, 8), "C1 주변 26주": sig_C1(R, 0.30, 26),
        "C2 NFCI>0": sig_C2(R), "C2 주변 −0.2": sig_C2(R, -0.2), "C2 주변 +0.2": sig_C2(R, 0.2),
        "C3 실업수당 +15%": sig_C3(R), "C3 주변 +10%": sig_C3(R, 0.10), "C3 주변 +20%": sig_C3(R, 0.20),
        "C4 삼 0.5": sig_C4(R), "C4 주변 0.4": sig_C4(R, 0.4), "C4 주변 0.6": sig_C4(R, 0.6),
        "C5 10Y−3M 역전": sig_C5(R),
        "C6 우라가미 역국면": sig_C6(D, R),
        "C7 시계추 ≥80": sig_C7(D, R), "C7 주변 70": sig_C7(D, R, 70), "C7 주변 90": sig_C7(D, R, 90),
        "C8 강달러": sig_C8(R),
    }
    rows = []
    rows += evaluate(D, one, "B0 매수보유")
    rows += evaluate(D, B1, "B1 200일선")
    rows += evaluate(D, D["above40w"], "참고 40주선")
    for k, s in signals.items():
        s = s.reindex(D.index).fillna(0)
        rows += evaluate(D, 1 - 0.5 * s, f"(a) {k}")
        rows += evaluate(D, B1 * (1 - 0.5 * s), f"(b) {k}")
    k4 = sum(signals[n].reindex(D.index).fillna(0) for n in ["C1 신용 13주 +0.30", "C2 NFCI>0", "C3 실업수당 +15%", "C4 삼 0.5"])
    rows += evaluate(D, (1 - 0.25 * k4).clip(0, 1), "(a) C9 합성")
    rows += evaluate(D, B1 * (1 - 0.25 * k4).clip(0, 1), "(b) C9 합성")
    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(BASE, "research", "macro_regime_bt_2026-10-20.csv"), index=False, encoding="utf-8-sig")
    # 지금 값(화면용)
    last = {k: float(v.reindex(D.index).fillna(0).iloc[-1]) for k, v in signals.items() if "주변" not in k}
    last["C9 경고 수"] = float(k4.iloc[-1])
    last["우라가미 국면"] = uragami(D, R).iloc[-1]
    last["시계추"] = round(float(pendulum(D, R).iloc[-1]), 1)
    pd.set_option("display.width", 220); pd.set_option("display.max_rows", 400)
    full = out[out["구간"] == "전체"].set_index("신호")[["CAGR", "MDD", "Calmar", "Sharpe", "노출", "변경_연"]]
    print(full.to_string())
    print("\n지금:", last)
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
