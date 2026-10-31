# -*- coding: utf-8 -*-
"""종목별 익절 래칫 백테스트 — 최근 5년 상승률 TOP 100(미국·한국) + 무작위 대조 100 (2026-10-31, 차니 요청)

질문: '종목이 오를수록 익절선을 끌어올리는' 규칙이 대박주의 상승을 얼마나 지키나(포착률), 그리고 같은 규칙이
      평범한 종목(대조군)에서는 손실을 얼마나 줄이나. 승자만 보면 '오래 쥐는 규칙'이 무조건 이긴다 — 그래서 대조군을 같이 잰다.

⚠️ 승자 100은 **결과를 보고 고른 표본**이다(미래 정보). 수익률 자체는 기대 수익이 아니다. 비교할 것은 규칙 간 차이뿐.
창: 최근 260주(5년). 앞 52주는 52주 고가·30주선 계산용. 시작 주 유동성: 미국 주가 $3+·일 거래대금 $5M+ /
    한국 시총 1,000억+·일 거래대금 10억+. 상폐 종목은 마지막 가격(승자에 거의 안 듦, 대조군에는 들 수 있음).
엔진: stock_rules.py (화면 🪜 익절 래칫과 공용) · 주봉 종가 판정 · 다음 주 종가 체결 · 편도 0.3%
결과: results/stock_ratchet_px.parquet(종목별 주봉 — 화면이 이걸로 사용자 규칙을 다시 돌린다) · results/stock_ratchet.json
"""
import os, sys, json, glob, subprocess, sqlite3
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import stock_rules as R

WIN, PRE, TOP = 260, 52, 100
OUT_PX = os.path.join(ROOT, "results", "stock_ratchet_px.parquet")
OUT = os.path.join(ROOT, "results", "stock_ratchet.json")


def pick(px, elig, names, market):
    """px: 주봉 종가(행 날짜·열 종목). 창 마지막 WIN 주 + 앞 PRE 주. 승자 TOP + 대조 TOP."""
    px = px.iloc[-(WIN + PRE):]
    s0 = PRE
    start = px.iloc[s0]
    ok = elig & start.notna()
    tot = px.iloc[s0:].apply(lambda s: s.dropna().iloc[-1] if s.notna().any() else np.nan) / start
    tot = tot[ok[ok].index].dropna()
    win = tot.sort_values(ascending=False).index[:TOP]
    rest = tot.index.difference(win)
    ctl = pd.Index(np.random.default_rng(0).choice(rest, size=min(TOP, len(rest)), replace=False))
    rows = []
    for grp, syms in (("승자100", win), ("대조100", ctl)):
        for s in syms:
            v = px[s]
            rows.append(pd.DataFrame(dict(market=market, grp=grp, sym=s, name=names.get(s, s), date=px.index, close=v.values)))
    info = dict(window=[str(px.index[s0].date()), str(px.index[-1].date())], eligible=int(len(tot)),
                winner_med=float(tot[win].median()), control_med=float(tot[ctl].median()), all_med=float(tot.median()))
    return pd.concat(rows), info


def us():
    c = sqlite3.connect(os.path.join(ROOT, "data", "market.db"))
    d = pd.read_sql("SELECT sym, date, close, volume FROM prices WHERE market='US' AND date >= date('now','-7 years')", c)
    d["date"] = pd.to_datetime(d.date)
    mc = pd.read_csv(os.path.join(ROOT, "data", "us_marketcap.csv"))
    names = dict(zip(mc.Symbol.astype(str), mc.Name.astype(str)))
    d = d[d.sym.isin(set(mc.Symbol.astype(str)) | set(pd.read_csv(os.path.join(ROOT, "data", "universe_ever.csv")).iloc[:, 0].astype(str)))]
    C = d.pivot_table(index="date", columns="sym", values="close")
    V = d.pivot_table(index="date", columns="sym", values="volume")
    C = C.resample("W-FRI").last(); V = V.resample("W-FRI").sum(min_count=1)
    dv = (C * V / 5).rolling(8, min_periods=6).mean()
    i = C.index[-(WIN)]  # 창 첫 주
    elig = (C.loc[i] >= 3) & (dv.loc[i] >= 5e6)
    return pick(C, elig.fillna(False), names, "US")


def kr():
    dd = os.path.join(ROOT, "data", "research", "marcap")
    os.makedirs(dd, exist_ok=True)
    yr = pd.Timestamp.today().year
    for y in range(yr - 7, yr + 1):
        f = os.path.join(dd, f"marcap-{y}.parquet")
        if not os.path.exists(f):
            subprocess.run(["curl", "-sSfL", "-o", f,
                            f"https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{y}.parquet"], check=False)
    parts = []
    for f in sorted(glob.glob(os.path.join(dd, "marcap-*.parquet")))[-8:]:
        x = pd.read_parquet(f)
        parts.append(x[[k for k in ("Code", "Name", "Date", "Close", "Amount", "Marcap", "Stocks", "Market", "MarketId") if k in x.columns]])
    d = pd.concat(parts)
    if "MarketId" in d.columns:
        d = d[d.MarketId.isin(["STK", "KSQ"])]
    d["Date"] = pd.to_datetime(d.Date); d["Code"] = d.Code.astype(str).str.zfill(6)
    d = d[d.Close > 0].drop_duplicates(["Code", "Date"], keep="last")
    names = d.sort_values("Date").groupby("Code").Name.last().to_dict()
    C = d.pivot(index="Date", columns="Code", values="Close")
    # 2026-10-31: marcap 은 수정주가가 아니다 — 액면분할일이 −80% 폭락으로 보여 손절이 가짜로 걸렸다.
    #   상장주식수가 1.5배+ 늘고(병합은 0.67배−) 가격이 그 역수 근처로 움직인 날을 분할로 보고 과거 가격을 보정.
    if "Stocks" in d.columns:
        St = d.pivot(index="Date", columns="Code", values="Stocks").reindex_like(C)
        sr, pr = St / St.shift(1), C / C.shift(1)
        x = pr * sr
        sp = (((sr >= 1.5) | (sr <= 0.67)) & (x >= 0.7) & (x <= 1.3)).fillna(False)
        step = sr.where(sp, 1.0).fillna(1.0)
        fac = step[::-1].cumprod()[::-1].shift(-1).fillna(1.0)       # 그날 이후 분할 비율의 곱
        C = C / fac
    Am = d.pivot(index="Date", columns="Code", values="Amount").rolling(20, min_periods=15).mean()
    Mc = d.pivot(index="Date", columns="Code", values="Marcap")
    last = C.apply(lambda s: s.last_valid_index())
    W = lambda z: z.resample("W-FRI").last()
    px, adv, mc = W(C), W(Am), W(Mc)
    for col in px.columns:                         # 상폐 뒤는 비운다(ffill 금지)
        lv = last.get(col)
        if lv is not None:
            px.loc[px.index > lv + pd.Timedelta(days=6), col] = np.nan
    i = px.index[-WIN]
    elig = ((mc.loc[i] >= 1e11) & (adv.loc[i] >= 1e9)).fillna(False)
    return pick(px, elig, names, "KR")


def evaluate(P):
    out = {}
    for (mkt, grp), g in P.groupby(["market", "grp"], sort=False):
        series = [s.sort_values("date").close.values for _, s in g.groupby("sym")]
        for ent in ("start", "nh52"):
            res = {}
            for name, p in R.PRESETS.items():
                res[name] = R.aggregate([R.summarize(c, PRE, dict(p, entry=ent)) for c in series])
            out[f"{mkt}|{grp}|{ent}"] = res
    return out


def main():
    parts, info = [], {}
    for mkt, fn in (("US", us), ("KR", kr)):
        try:
            P, inf = fn()
            parts.append(P); info[mkt] = inf
            print(f"[{mkt}] 창 {inf['window']} · 대상 {inf['eligible']}종 · 승자 중앙 ×{inf['winner_med']:.1f} · 대조 중앙 ×{inf['control_med']:.2f}")
        except Exception as e:
            info[mkt] = dict(error=f"{type(e).__name__}: {e}")
            print(f"[{mkt}] 실패: {e}")
    if not parts:
        raise SystemExit("두 시장 모두 실패")
    P = pd.concat(parts)
    P.to_parquet(OUT_PX, index=False)
    res = evaluate(P)
    json.dump(dict(asof=str(pd.Timestamp.today().date()), info=info, presets=list(R.PRESETS), default=R.DEFAULT,
                   results=res, note="승자100 = 결과를 보고 고른 표본(미래 정보) — 규칙 간 차이만 본다. 대조100 = 같은 유동성 조건 무작위."),
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for k, v in res.items():
        print(k)
        for n, a in v.items():
            print(f"   {n:28s} 중앙 ×{a['mult_med']:.2f} 기하 ×{a['mult_geo']:.2f} 포착 {a['capture_med']:.2f} 보유보다 나음 {a['beat_bh']:.0%} MDD {a['mdd_med']:.0%}")


if __name__ == "__main__":
    main()
