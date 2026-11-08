# -*- coding: utf-8 -*-
"""🧮 퀀트 백테스트용 주봉 패널 — 미국·한국을 같은 열 이름으로 (2026-11-01, 차니 요구 7)

열(공통): sym, name, market, date(주 월요일), open, high, low, close, volume, marcap,
          per, pbr, psr, rev_yoy, op_yoy, op_turn(0/1), acc(이익가속 0/1, 미국만), sector
  · 재무는 그 주에 **알 수 있던 값만**: 미국 = SEC 공시일 기준(factor_weekly), 한국 = 분기말 +45일(4분기 +90일).
  · 기술 지표(이평·RSI·MACD·RS·신고가·캔들)는 엔진(quant_engine.py)이 OHLCV 로 계산한다 — 여기서 굳히지 않는다.
  · 종목 수: 그 주 시총 미국 $0.2B+ / 한국 500억+ 인 행만(보유 중 종목이 이 밑으로 떨어지면 가격이 끊긴다 → 엔진이 마지막 가격으로 정리).
결과: results/quant_panel_US.parquet · quant_panel_KR.parquet (git 이 아니라 GitHub Release 'quant-panel' 에 올린다 — 수십 MB)
"""
import os, sys, glob, json, sqlite3, subprocess
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "results")
COLS = ["sym", "name", "market", "date", "open", "high", "low", "close", "volume", "marcap",
        "per", "pbr", "psr", "rev_yoy", "op_yoy", "op_turn", "acc", "sector",
        "opm", "gpm", "rev_qoq", "roe", "debt"]       # 2026-11-01 확장 — 시장에 없는 열은 빈 값


def _f32(d):
    for c in ("open", "high", "low", "close", "volume", "marcap", "per", "pbr", "psr", "rev_yoy", "op_yoy",
              "opm", "gpm", "rev_qoq", "roe", "debt"):
        if c not in d:
            d[c] = np.nan
        d[c] = pd.to_numeric(d[c], errors="coerce").astype("float32")
    for c in ("op_turn", "acc"):
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0).astype("int8")
    return d[COLS]


def us():
    ver = os.environ.get("FACTOR_VER", "v1")
    os.environ["FACTOR_VER"] = ver
    import leaders_accel as A
    d = A.load()                                         # ACC 계산 포함
    c = sqlite3.connect(os.path.join(ROOT, "data", "market.db"))
    extra = pd.read_sql(f"SELECT as_of, sym, sector, pbr, op_turn, op_income, rev_qoq FROM factor_weekly WHERE factor_ver='{ver}'", c)
    extra["as_of"] = pd.to_datetime(extra.as_of)
    d = d.merge(extra, on=["as_of", "sym"], how="left", suffixes=("", "_x"))
    px = pd.read_sql("SELECT sym, date, open, high, low, volume FROM prices WHERE market='US'", c)
    px["date"] = pd.to_datetime(px.date)
    d = d.rename(columns={"as_of": "date"}).merge(px, on=["sym", "date"], how="left")
    d = d[d.marcap >= 2e8].copy()
    # 영업이익 YoY: 같은 종목 4분기 전 값(분기 패널에서)
    q = d.dropna(subset=["period_end"]).drop_duplicates(["sym", "period_end"])[["sym", "period_end", "op_income"]].sort_values(["sym", "period_end"])
    q["op4"] = q.groupby("sym").op_income.shift(4)
    q["op_yoy"] = np.where(q.op4 > 0, (q.op_income / q.op4 - 1) * 100, np.nan)
    d = d.merge(q[["sym", "period_end", "op_yoy"]], on=["sym", "period_end"], how="left")
    d["market"] = "US"
    d["acc"] = d["ACC"]
    for k in ("open", "high", "low"):
        d[k] = d[k].fillna(d["close"])
    # 2026-11-01 가격 정합 — 역분할 보정이 깨진 초소형주(MLMC·BQST·COSG 등)가 주간 ×20~×3,000 으로 튀어
    #   '시총 상위'로 잡히고 할로윈 예시가 ×3,061 이 됐다. ① $1 미만 행 제외 ② 주간 ×5 초과·÷5 미만 급변 행은
    #   그 종목을 통째로 뺀다.
    d = d[d.close >= 1].sort_values(["sym", "date"]).copy()
    r = d.groupby("sym").close.transform(lambda s: s / s.shift(1))
    bad = (r > 5) | (r < 0.2)
    #   급변 행만 비우면 앞뒤 가격 수준 차이(보정 실패)가 그대로 수익으로 잡힌다 → 그런 종목은 통째로 뺀다(수 종목, 영향 미미).
    bad_syms = sorted(d.loc[bad, "sym"].unique())
    d = d[~d.sym.isin(bad_syms)]
    print(f"[US] 주간 ×5↑·÷5↓ 급변 {int(bad.sum())}칸 → {len(bad_syms)}종 제외 {bad_syms[:20]} · $1 미만 행 제외")
    print(f"[US] {ver} {d.date.min().date()}~{d.date.max().date()} · {d.sym.nunique():,}종 · {len(d):,}행")
    return _f32(d)


def kr():
    dd = os.path.join(ROOT, "data", "research", "marcap")
    os.makedirs(dd, exist_ok=True)
    yr = pd.Timestamp.today().year
    for y in range(2014, yr + 1):
        f = os.path.join(dd, f"marcap-{y}.parquet")
        if not os.path.exists(f):
            subprocess.run(["curl", "-sSfL", "-o", f,
                            f"https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{y}.parquet"], check=False)
    parts = []
    for f in sorted(glob.glob(os.path.join(dd, "marcap-*.parquet"))):
        x = pd.read_parquet(f, columns=["Code", "Name", "Date", "Open", "High", "Low", "Close", "Volume", "Marcap", "Stocks", "MarketId"])
        parts.append(x[x.MarketId.isin(["STK", "KSQ"])])
    d = pd.concat(parts)
    d["Date"] = pd.to_datetime(d.Date); d["Code"] = d.Code.astype(str).str.zfill(6)
    d = d[d.Close > 0].drop_duplicates(["Code", "Date"], keep="last").sort_values(["Code", "Date"])
    # 액면분할·병합 보정(marcap 은 수정주가가 아님 — 2026-10-31 발견). 그날 이후 분할 비율의 곱으로 과거 가격을 나눈다.
    sr = d.groupby("Code").Stocks.transform(lambda s: s / s.shift(1))
    pr = d.groupby("Code").Close.transform(lambda s: s / s.shift(1))
    x = pr * sr
    sp = ((sr >= 1.5) | (sr <= 0.67)) & (x >= 0.7) & (x <= 1.3)
    step = sr.where(sp, 1.0).fillna(1.0)
    d["_f"] = step.groupby(d.Code).transform(lambda s: s[::-1].cumprod()[::-1].shift(-1).fillna(1.0))
    for k in ("Open", "High", "Low", "Close"):
        d[k] = d[k] / d["_f"]
    d["Volume"] = d["Volume"] * d["_f"]
    d["week"] = d.Date - pd.to_timedelta(d.Date.dt.weekday, unit="D")      # 월요일 라벨
    w = d.groupby(["Code", "week"]).agg(name=("Name", "last"), open=("Open", "first"), high=("High", "max"), low=("Low", "min"),
                                        close=("Close", "last"), volume=("Volume", "sum"), marcap=("Marcap", "last"),
                                        mid=("MarketId", "last"), last_day=("Date", "last")).reset_index()
    w = w.rename(columns={"Code": "sym", "week": "date"})
    w = w[w.marcap >= 5e10]
    # 재무: 공시일 없음 → 분기말 + 45일(4분기 90일)에 알게 된 것으로
    q = pd.read_parquet(os.path.join(ROOT, "data", "kr_fundamentals_q.parquet"))
    q["sym"] = q.sym.astype(str).str.zfill(6)
    q["end"] = pd.to_datetime(q.year.astype(int).astype(str) + "-" + (q.q.astype(int) * 3).astype(str) + "-01") + pd.offsets.MonthEnd(0)
    # 2026-11-05: 실제 DART 제출일(다음 날)부터 — 없으면 분기말 +45일(4분기 90일) 가정
    from tools.kr_filing_dates import known as _known
    q["known"], _real = _known(q.sym, q.year, q.q)
    print(f"[KR] 재무 공시일: 실제 제출일 {_real.mean():.0%} · 가정 {1 - _real.mean():.0%}", flush=True)
    q = q.sort_values(["sym", "end"])
    g = q.groupby("sym")
    for k in ("revenue", "op_income", "net_income"):
        q[f"ttm_{k}"] = g[k].transform(lambda s: s.rolling(4, min_periods=4).sum())
    q["rev_yoy"] = np.where(g.revenue.shift(4) > 0, (q.revenue / g.revenue.shift(4) - 1) * 100, np.nan)
    o4 = g.op_income.shift(4)
    q["op_yoy"] = np.where(o4 > 0, (q.op_income / o4 - 1) * 100, np.nan)
    q["op_turn"] = ((q.op_income > 0) & (o4 <= 0)).astype(int)
    q["acc"] = kr_acc(q)                       # 2026-11-07: 한국도 이익가속(대시보드 leaders_accel 과 같은 정의)
    q["oi_g"] = kr_oi_g(q)                     # 2026-11-08: 이익 개선폭(%p of 매출) — 적자 축소·흑자전환·급증
    q["opm"] = (q.ttm_op_income / q.ttm_revenue * 100).where(q.ttm_revenue > 0)
    q["debt"] = (q.liabilities / q.equity * 100).where(q.equity > 0)
    q = q[["sym", "known", "ttm_revenue", "ttm_net_income", "equity", "rev_yoy", "op_yoy", "op_turn", "acc", "oi_g", "opm", "debt"]].sort_values("known")
    w = w.sort_values("date")
    w = pd.merge_asof(w, q, left_on="date", right_on="known", by="sym", direction="backward")
    w["per"] = (w.marcap / w.ttm_net_income).where(w.ttm_net_income > 0)
    w["pbr"] = (w.marcap / w.equity).where(w.equity > 0)
    w["psr"] = (w.marcap / w.ttm_revenue).where(w.ttm_revenue > 0)
    w["roe"] = (w.ttm_net_income / w.equity * 100).where(w.equity > 0)
    # 2026-11-05: 'KR' 대신 그 주의 소속 시장 — 퀀트 엔진 지수 게이트를 실전 규칙처럼 소속 시장별로(코스닥 종목 = 코스닥 5주선)
    w["market"] = w.pop("mid").map({"STK": "KOSPI", "KSQ": "KOSDAQ"}).fillna("KR")
    w["acc"] = w["acc"].fillna(0).astype(int)
    try:
        sec = json.load(open(os.path.join(ROOT, "data", "sectors.json"), encoding="utf-8"))
    except Exception:
        sec = {}
    w["sector"] = w.sym.map(sec)
    print(f"[KR] {w.date.min().date()}~{w.date.max().date()} · {w.sym.nunique():,}종 · {len(w):,}행")
    return _f32(w)


KR_MIN_QREV = 1e10     # 분기 매출 100억원 — 이 아래는 이익가속이 발산(미국 $10M 과 같은 취지)
MAX_OIA = 10.0


def kr_oi_g(q: pd.DataFrame) -> pd.Series:
    """이익 개선폭(%p) = (영업익 − 전년 같은 분기 영업익) ÷ |매출| × 100. 적자 축소·흑자전환·이익 증가가 모두 + 로 같은 자로 잰다
    (차니 2026-11-08: '적자 대폭 감소 · 이익 폭증 · 흑자전환' 셋 다 이익 개선). 분기 매출 100억원 미만은 빈값."""
    o4 = q.groupby("sym").op_income.shift(4)
    rev = q.revenue.where(q.revenue.abs() >= KR_MIN_QREV)
    return ((q.op_income - o4) / rev.abs() * 100).replace([np.inf, -np.inf], np.nan)


def kr_acc(q: pd.DataFrame) -> pd.Series:
    """한국 이익가속(0/1) — leaders_accel.py 와 같은 정의(2026-11-07, 실전 v1.8 후보 '이익가속 OR 흑자전환' 검증용).
    q: sym·분기 순으로 정렬된 분기표(revenue, op_income). 매출 성장률·이익 성장률(영업익 증가 ÷ |매출|)이 직전 분기보다 둘 다 빨라짐."""
    g = q.groupby("sym")
    r4, o4 = g.revenue.shift(4), g.op_income.shift(4)
    rv = pd.Series(np.where(r4 > 0, (q.revenue / r4 - 1) * 100, np.nan), index=q.index)
    rev = q.revenue.where(q.revenue.abs() >= KR_MIN_QREV)
    oi = ((q.op_income - o4) / rev.abs()).replace([np.inf, -np.inf], np.nan)
    rv_a = rv - rv.groupby(q.sym).shift(1)
    oi_a = oi - oi.groupby(q.sym).shift(1)
    return ((rv_a > 0) & (oi_a > 0) & (oi_a.abs() <= MAX_OIA)).astype(int)


def main(markets=("US", "KR")):
    info = {}
    for m, fn in (("US", us), ("KR", kr)):
        if m not in markets:
            continue
        try:
            d = fn()
            d.to_parquet(os.path.join(OUT, f"quant_panel_{m}.parquet"), index=False, compression="zstd")
            info[m] = dict(rows=int(len(d)), syms=int(d.sym.nunique()), start=str(d.date.min().date()), end=str(d.date.max().date()))
        except Exception as e:
            info[m] = dict(error=f"{type(e).__name__}: {e}")
            print(f"[{m}] 실패: {e}")
    info["asof"] = str(pd.Timestamp.today().date())
    json.dump(info, open(os.path.join(OUT, "quant_panel_info.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(info)


if __name__ == "__main__":
    main(tuple(sys.argv[1:]) or ("US", "KR"))
