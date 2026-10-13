# -*- coding: utf-8 -*-
"""KRX 상장 종목 목록 — fdr.StockListing('KRX') 의 고장에 견디는 단일 진입점.

왜 만들었나 (2026-10-14)
  2026-10-12 부터 CI 에서 fdr.StockListing('KRX') 가 실패했다. FDR 0.9.202 는
  ① data.krx.co.kr 에 '최신 영업일'을 묻고 ② 그 날짜의 CSV 를 GitHub 캐시
  (FinanceData/fdr_krx_data_cache)에서 받는다. ①이 막히면(해외 IP 차단·KRX 로그인
  변경·FDR 이슈 #286/#288/#292) ②의 멀쩡한 데이터까지 못 받는다.
  이 함수 하나에 9개 파일이 매달려 있었고, 실패는 continue-on-error 로 '성공' 처리됐다.
  → 결과: 🔥상승상위·주봉스크리너의 KR 종목 692→0, CANSLIM KR·가치발굴 정지.

순서
  1) fdr.StockListing(market)                — 정상일 때
  2) GitHub 캐시 CSV 를 날짜를 거슬러 직접 받기 — ①을 건너뛴다. 공휴일 파일은 가격이 '-' 라 검증에서 걸러진다
  3) data/krx_listing_last.csv (마지막 정상본) — 1·2 가 성공할 때마다 갱신, 커밋된다
  셋 다 실패하면 예외를 던진다. **빈 목록을 조용히 돌려주지 않는다.**

반환 DataFrame 의 attrs['source'] / attrs['asof'] 로 어디서 왔는지 남긴다.
"""
import io
import os
from datetime import date, timedelta

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(BASE, "data", "krx_listing_last.csv")
CACHE_URL = ("https://raw.githubusercontent.com/FinanceData/fdr_krx_data_cache/"
             "refs/heads/master/data/listing/{kind}/{d}.csv")
_MKT = {"KRX": None, "KRX-MARCAP": None, "KOSPI": "STK", "KOSDAQ": "KSQ", "KONEX": "KNX"}
_memo = {}


def _valid(df) -> bool:
    """정상 목록인가 — 종목 2,000개 이상, 시총이 90% 이상 숫자, 코스피·코스닥 둘 다 존재."""
    if df is None or len(df) < 2000 or "Marcap" not in df or "Code" not in df:
        return False
    mc = pd.to_numeric(df["Marcap"], errors="coerce")
    if mc.notna().mean() < 0.9 or (mc >= 3e11).sum() < 300:
        return False
    if "MarketId" in df:
        ids = set(df["MarketId"].astype(str))
        if not {"STK", "KSQ"} <= ids:
            return False
    return True


def _clean(df):
    df = df.copy()
    df["Code"] = df["Code"].astype(str).str.zfill(6)
    for c in ("Marcap", "Close", "Stocks", "Amount", "Volume"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["Marcap"])
    df["Marcap"] = df["Marcap"].astype("int64")
    return df.reset_index(drop=True)


def _from_cache(days_back=14):
    import requests
    for k in range(days_back):
        d = (date.today() - timedelta(days=k)).isoformat()
        try:
            r = requests.get(CACHE_URL.format(kind="krx", d=d), timeout=20)
            if r.status_code != 200:
                continue
            df = pd.read_csv(io.StringIO(r.text), index_col=0,
                             dtype={"Code": str, "MarketId": str, "Dept": str, "ChangeCode": str})
            if _valid(df):
                return df, d
        except Exception:
            continue
    return None, None


def _filter(df, market):
    mkt = _MKT.get(market)
    if mkt and "MarketId" in df:
        df = df[df["MarketId"].astype(str) == mkt].reset_index(drop=True)
    return df


def _tradable(df):
    """스크리너 유니버스용 — 코넥스와 그날 거래가 없던 종목(거래정지 등)을 뺀다.

    2026-10-14 — CANSLIM KR 후보에 '본시스템즈'(코넥스, 고가 0원·거래 0)가 끼어 있었다.
    가격이 없는 종목은 52주 고가·RS 계산이 무의미하고, 코넥스는 개인 매매 제약이 있다."""
    if "MarketId" in df:
        df = df[df["MarketId"].astype(str) != "KNX"]
    if "Volume" in df:
        v = pd.to_numeric(df["Volume"], errors="coerce")
        df = df[v.fillna(0) > 0]
    return df.reset_index(drop=True)


def stock_listing(market: str = "KRX", verbose: bool = True, tradable: bool = False) -> pd.DataFrame:
    """fdr.StockListing('KRX'|'KOSPI'|'KOSDAQ'|'KONEX') 대체. 실패하면 예외.
    tradable=True 면 코넥스·당일 거래 없는 종목을 뺀다(스크리너 유니버스용)."""
    if tradable:
        return _tradable(stock_listing(market, verbose=verbose))
    if market not in _MKT:
        raise ValueError(f"market={market} 는 지원하지 않는다 (KRX/KOSPI/KOSDAQ/KONEX)")
    if "ALL" in _memo:
        return _filter(_memo["ALL"], market)

    df, src, asof, errs = None, None, None, []
    try:
        import FinanceDataReader as fdr
        live = fdr.StockListing("KRX")
        if _valid(live):
            df, src, asof = live, "fdr", date.today().isoformat()
        else:
            errs.append(f"fdr: 검증 실패({len(live)}행)")
    except Exception as e:
        errs.append(f"fdr: {str(e)[:120]}")

    if df is None:
        df, asof = _from_cache()
        if df is not None:
            src = "fdr_krx_data_cache"
        else:
            errs.append("github cache: 14일 내 유효 파일 없음")

    if df is None and os.path.exists(SNAP):
        snap = pd.read_csv(SNAP, dtype={"Code": str, "MarketId": str})
        if _valid(snap):
            df, src = snap, "snapshot"
            asof = str(snap.attrs.get("asof") or "") or _snap_date()

    if df is None:
        raise RuntimeError("KRX 종목 목록을 어디서도 받지 못했다 — " + " | ".join(errs))

    df = _clean(df)
    if src != "snapshot":
        try:
            keep = [c for c in ("Code", "Name", "Market", "MarketId", "Close", "Marcap",
                                "Stocks", "Amount", "Volume") if c in df]
            df[keep].to_csv(SNAP, index=False, encoding="utf-8")
            with open(SNAP + ".asof", "w") as f:
                f.write(asof or "")
        except Exception:
            pass
    df.attrs = {"source": src, "asof": asof, "errors": errs}
    if verbose and src != "fdr":
        print(f"  [krx_listing] fdr 실패 → {src} ({asof}) 사용 · {' | '.join(errs)}", flush=True)
    _memo["ALL"] = df
    return _filter(df, market)


def desc_listing() -> pd.DataFrame:
    """fdr.StockListing('KRX-DESC') 대체 — 업종(Sector)·산업. 캐시 CSV 를 직접 받는다.
    2026-10-14: KRX-DESC 도 같은 이유로 실패해 data/sectors.json 의 KR 섹터가 0종이었다."""
    try:
        import FinanceDataReader as fdr
        d = fdr.StockListing("KRX-DESC")
        if d is not None and len(d) > 2000:
            d.attrs = {"source": "fdr"}
            return d
    except Exception:
        pass
    import requests
    for k in range(14):
        dd = (date.today() - timedelta(days=k)).isoformat()
        try:
            r = requests.get(CACHE_URL.format(kind="desc", d=dd), timeout=20)
            if r.status_code != 200:
                continue
            d = pd.read_csv(io.StringIO(r.text), index_col=0, dtype={"Code": str})
            if len(d) > 2000 and "Sector" in d:
                d["Code"] = d["Code"].astype(str).str.zfill(6)
                d.attrs = {"source": "fdr_krx_data_cache", "asof": dd}
                return d.reset_index(drop=True)
        except Exception:
            continue
    raise RuntimeError("KRX-DESC 를 받지 못했다")


def _snap_date():
    try:
        return open(SNAP + ".asof").read().strip()
    except Exception:
        return ""


def kr_pairs(min_marcap: int = 300_000_000_000):
    """(code, name, marcap) 시총 큰 순 — 여러 스크립트에 흩어져 있던 같은 코드의 공용판."""
    krx = stock_listing("KRX")
    f = krx[krx["Marcap"] >= min_marcap].sort_values("Marcap", ascending=False)
    return list(zip(f["Code"], f["Name"].astype(str), f["Marcap"].astype(int)))


if __name__ == "__main__":
    d = stock_listing("KRX")
    print(d.attrs, len(d), "3000억+", (d.Marcap >= 3e11).sum())
