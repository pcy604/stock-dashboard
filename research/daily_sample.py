# -*- coding: utf-8 -*-
"""일봉 표본 — 🎮 매매 실험실(trade_rules.py)용 (2026-10-31)

종목: 🪜 래칫과 같은 표본(results/stock_ratchet_px.parquet 의 승자100·대조100, 미국·한국).
  · 한국: FinanceData/marcap 일봉 OHLC(상폐 포함). 액면분할·병합은 상장주식수 변화로 찾아 과거 가격을 수정한다
          (marcap 은 수정주가가 아니다 — 분할일이 −80% 폭락처럼 보여 손절이 가짜로 걸린다).
  · 미국: yfinance 일봉(수정주가). 상폐 종목은 못 받는다 → 받지 못한 수를 info 에 남긴다.
지수: SPX·NDX·RUT(미국) · KOSPI·KOSDAQ(한국) — yfinance, 실패 시 data/research/macro_long_px.parquet(SPX·NDX·KOSPI).
결과: results/trade_px.parquet · results/trade_idx.parquet · results/trade_px_info.json
"""
import os, sys, json, glob
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PX = os.path.join(ROOT, "results", "trade_px.parquet")
OUT_IX = os.path.join(ROOT, "results", "trade_idx.parquet")
OUT_INFO = os.path.join(ROOT, "results", "trade_px_info.json")
DAYS = 6 * 252 + 30          # 5년 창 + 앞 1년(52주 고가·이평 계산용)


def kr_daily(codes):
    parts = []
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "research", "marcap", "marcap-*.parquet")))[-8:]:
        x = pd.read_parquet(f, columns=["Code", "Date", "Open", "High", "Low", "Close", "Stocks"])
        x["Code"] = x.Code.astype(str).str.zfill(6)
        parts.append(x[x.Code.isin(codes)])
    d = pd.concat(parts)
    d["Date"] = pd.to_datetime(d.Date)
    d = d[d.Close > 0].drop_duplicates(["Code", "Date"], keep="last").sort_values(["Code", "Date"])
    out, nsplit = [], 0
    for c, g in d.groupby("Code"):
        g = g.tail(DAYS).copy()
        sr = g.Stocks / g.Stocks.shift(1)
        pr = g.Close / g.Close.shift(1)
        # 주식수가 1.5배 이상 늘고 가격이 그 역수 근처(±30%)로 빠진 날 = 분할. 병합은 반대.
        split = ((sr >= 1.5) & ((pr * sr).between(0.7, 1.3))) | ((sr <= 0.67) & ((pr * sr).between(0.7, 1.3)))
        adj = pd.Series(1.0, index=g.index)
        for i in np.where(split.values)[0]:
            adj.iloc[:i] *= 1 / sr.iloc[i]
            nsplit += 1
        for k in ("Open", "High", "Low", "Close"):
            g[k] = g[k] * adj
        g = g[(g.Open > 0) & (g.High > 0) & (g.Low > 0)]
        out.append(pd.DataFrame(dict(sym=c, date=g.Date.values, o=g.Open.values, h=g.High.values, l=g.Low.values, c=g.Close.values)))
    return pd.concat(out), nsplit


def us_daily(syms):
    import yfinance as yf
    out, miss = [], []
    for i in range(0, len(syms), 50):
        chunk = syms[i:i + 50]
        try:
            x = yf.download(chunk, period="7y", interval="1d", auto_adjust=True, progress=False, group_by="ticker", threads=True)
        except Exception as e:
            print(f"[US] 묶음 실패 {e}"); miss += chunk; continue
        for s in chunk:
            try:
                g = (x[s] if len(chunk) > 1 else x).dropna(subset=["Close"]).tail(DAYS)
                if len(g) < 300:
                    miss.append(s); continue
                out.append(pd.DataFrame(dict(sym=s, date=g.index.values, o=g.Open.values, h=g.High.values, l=g.Low.values, c=g.Close.values)))
            except Exception:
                miss.append(s)
    return (pd.concat(out) if out else pd.DataFrame()), miss


def indices():
    want = {"SPX": "^GSPC", "NDX": "^NDX", "RUT": "^RUT", "KOSPI": "^KS11", "KOSDAQ": "^KQ11"}
    got = {}
    try:
        import yfinance as yf
        x = yf.download(list(want.values()), period="7y", interval="1d", auto_adjust=True, progress=False)["Close"]
        for k, t in want.items():
            if t in x and x[t].notna().sum() > 500:
                got[k] = x[t]
    except Exception as e:
        print(f"[지수] yfinance 실패 {e}")
    lp = os.path.join(ROOT, "data", "research", "macro_long_px.parquet")
    if os.path.exists(lp):
        m = pd.read_parquet(lp)
        for k in ("SPX", "NDX", "KOSPI"):
            if k not in got and k in m:
                got[k] = m[k].dropna()
    I = pd.DataFrame(got)
    I.index = pd.to_datetime(I.index).tz_localize(None) if getattr(I.index, "tz", None) else pd.to_datetime(I.index)
    return I.sort_index().iloc[-DAYS:]


def main(markets=("KR", "US")):
    S = pd.read_parquet(os.path.join(ROOT, "results", "stock_ratchet_px.parquet"))[["market", "grp", "sym", "name"]].drop_duplicates(["market", "sym", "grp"])
    parts, info = [], {}
    if "KR" in markets:
        k = S[S.market == "KR"]
        d, ns = kr_daily(set(k.sym))
        parts.append(d.merge(k, on="sym"))
        info["KR"] = dict(n=int(d.sym.nunique()), want=int(k.sym.nunique()), splits_fixed=int(ns), source="marcap(분할 보정)")
    if "US" in markets:
        u = S[S.market == "US"]
        d, miss = us_daily(sorted(set(u.sym)))
        if len(d):
            parts.append(d.merge(u, on="sym"))
        info["US"] = dict(n=int(d.sym.nunique()) if len(d) else 0, want=int(u.sym.nunique()), missing=miss[:50], source="yfinance(수정주가)")
    P = pd.concat(parts)
    for k in ("o", "h", "l", "c"):
        P[k] = P[k].astype("float32")
    P.to_parquet(OUT_PX, index=False)
    I = indices()
    I.astype("float32").to_parquet(OUT_IX)
    info["indices"] = {k: [str(I[k].first_valid_index().date()), str(I[k].last_valid_index().date())] for k in I}
    info["asof"] = str(pd.Timestamp.today().date())
    json.dump(info, open(OUT_INFO, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(info)


if __name__ == "__main__":
    main(tuple(sys.argv[1:]) or ("KR", "US"))
