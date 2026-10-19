# -*- coding: utf-8 -*-
"""
매크로 장기 시계열 수집 — 욕심 조절(리스크 온/오프) 백테스트용 (2026-10-20)

왜 따로 받는가
  data/macro_hist.parquet 는 2015년부터라 하락장이 2020·2022 두 번뿐이다.
  '언제 욕심을 줄여야 하나'를 검증하려면 1990·2000·2008 같은 큰 하락장이 들어가야 한다.

산출물 (원값 그대로 — 발표 시차는 백테스트 쪽에서 적용)
  data/research/macro_long_fred.parquet   FRED 계열, 각자 원래 주기(일·주·월)
  data/research/macro_long_px.parquet     자산 일간 종가(Yahoo)

CLI
  FRED_KEY=... python tools/fetch_macro_long.py
"""
import os
import sys
import time

import pandas as pd
import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTD = os.path.join(BASE, "data", "research")

FRED = [
    # 금리
    "DGS10", "DGS2", "TB3MS", "DTB3", "FEDFUNDS", "T10Y2Y", "T10Y3M", "DFII10", "T10YIE",
    # 신용·금융여건 (ICE 하이일드는 FRED 가 최근 3년만 준다 → 장기는 Baa 스프레드·NFCI)
    "BAA10Y", "BAMLH0A0HYM2", "NFCI", "NFCICREDIT", "VIXCLS", "VXVCLS",
    # 성장
    "ICSA", "UNRATE", "PAYEMS", "INDPRO", "CFNAI", "NEWORDER", "GDPNOW", "USREC",
    # 물가
    "CPIAUCSL", "CPILFESL", "PCEPILFE",
    # 유동성
    "M2SL", "WALCL", "WTREGEN", "RRPONTSYD", "DTWEXBGS",
    # 한국
    "DEXKOUS", "IRLTLT01KRM156N", "XTEXVA01KRM667S",
]

PX = {  # 이름: Yahoo 심볼
    "SPX": "^GSPC", "SPXTR": "^SP500TR", "NDX": "^IXIC", "KOSPI": "^KS11",
    "TLT": "TLT", "IEF": "IEF", "GLD": "GLD", "GOLD_F": "GC=F", "COPPER_F": "HG=F", "WTI_F": "CL=F",
    "DXY": "DX-Y.NYB", "BTC": "BTC-USD", "VIX": "^VIX", "VIX3M": "^VIX3M", "HYG": "HYG",
    "USDKRW": "KRW=X",
}


def pull_fred(sid, key):
    url = "https://api.stlouisfed.org/fred/series/observations"
    p = dict(series_id=sid, api_key=key, file_type="json", observation_start="1950-01-01")
    for i in range(3):
        try:
            r = requests.get(url, params=p, timeout=30)
            r.raise_for_status()
            rows = [(o["date"], float(o["value"])) for o in r.json()["observations"] if o["value"] != "."]
            if rows:
                return pd.Series({pd.Timestamp(d): v for d, v in rows}, name=sid).sort_index()
        except Exception as e:
            print(f"  {sid} 재시도 {i+1}: {str(e)[:80]}", flush=True)
            time.sleep(3)
    return None


def main():
    os.makedirs(OUTD, exist_ok=True)
    key = os.environ.get("FRED_KEY", "")
    if not key:
        print("::error::FRED_KEY 없음")
        return 1
    fred, fail = {}, []
    for sid in FRED:
        s = pull_fred(sid, key)
        if s is None or s.empty:
            fail.append(sid)
            continue
        fred[sid] = s
        print(f"  FRED {sid:<18}{len(s):>7}  {s.index[0].date()} ~ {s.index[-1].date()}", flush=True)
    long = pd.concat([s.rename("v").to_frame().assign(sid=k) for k, s in fred.items()])
    long.index.name = "date"
    long.reset_index().to_parquet(os.path.join(OUTD, "macro_long_fred.parquet"), index=False)

    import yfinance as yf
    px = {}
    for name, sym in PX.items():
        try:
            d = yf.Ticker(sym).history(period="max", auto_adjust=True)
            if d is not None and len(d) > 100:
                c = d["Close"]
                c.index = pd.to_datetime(c.index).tz_localize(None).normalize()
                px[name] = c[~c.index.duplicated(keep="last")]
                print(f"  PX   {name:<10}{len(c):>7}  {c.index[0].date()} ~ {c.index[-1].date()}", flush=True)
            else:
                fail.append(name)
        except Exception as e:
            print(f"  PX {name} 실패: {str(e)[:80]}", flush=True)
            fail.append(name)
    pd.DataFrame(px).sort_index().to_parquet(os.path.join(OUTD, "macro_long_px.parquet"))
    print(f"\n완료 FRED {len(fred)}/{len(FRED)} · PX {len(px)}/{len(PX)} · 실패 {fail}")
    return 0 if len(fred) >= len(FRED) * 0.8 and len(px) >= len(PX) * 0.8 else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
