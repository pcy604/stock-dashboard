# -*- coding: utf-8 -*-
"""KR 산출물 원천 대조 — 앱이 낸 숫자를 **다른 소스**로 다시 계산해 맞는지 본다.

왜 (2026-10-14)
  계약 검사(output_contracts.py)는 '비었나·낡았나'를 본다. 숫자가 **틀린** 것은 못 본다.
  10-13 점검의 '52주 신고가 0/1,065' 는 비어 있지도 낡지도 않았다 — 그냥 틀렸다.
  그래서 하루 한 번, 앱과 독립된 원천으로 같은 값을 계산해 대조한다.

원천(앱과 다른 경로)
  · FinanceData/marcap 일괄 데이터셋(GitHub, 전 종목 일봉)  — 앱은 종목별 FDR(네이버) 시세
  · fdr_krx_data_cache 당일 목록(krx_listing)                — marcap 이 하루 늦을 때 보충

대조 항목
  ① perf_latest   KR 현재가          vs 원천 종가            (1% 이내 비율 ≥ 90%)
  ② perf_latest   52주 신고가 신호    vs 원천 신고가 -3% 이내  (일치율 ≥ 90%)
  ③ canslim KR    N 거리(%)          vs 원천                  (1.5%p 이내 ≥ 90%)
  ④ canslim KR    RS 퍼센타일        vs 원천                  (±10 이내 ≥ 85%)
  ⑤ 커버리지      perf KR 종목 수     vs 원천 시총 3,000억+    (≥ 80%)
  앱의 기준일은 '현재가가 원천 종가와 일치하는 날'로 역산한다(앱은 날짜를 저장하지 않는다).

  장중 실행(KST 평일 09:00~15:40)이면 ①③은 비교하지 않는다(2026-10-14 첫 실행에서 발견).
    daily-refresh 는 09:00 KST 전후에 돈다 → 앱 현재가는 장 시작 몇십 분의 값이고, 원천은
    전일 종가(또는 다른 시각의 장중 스냅샷)다. 둘이 어긋나는 건 오류가 아니라 시각 차이다.
    그날 ①은 66%, ③은 42% 로 '실패'가 떴고 진짜 고장과 구별할 수 없었다.
    ②④⑤와 신고가 개수는 하루 움직임에 둔감해 장중에도 그대로 본다.

  python tools/reconcile_kr.py            결과 출력 + results/reconcile_kr.json, 미달이면 종료코드 1
"""
import io, json, os, sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
import requests

MARCAP = "https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{y}.parquet"
OUT = ROOT / "results" / "reconcile_kr.json"


def _src():
    y = date.today().year
    parts = []
    for yy in (y - 1, y):
        r = requests.get(MARCAP.format(y=yy), timeout=120)
        r.raise_for_status()
        parts.append(pd.read_parquet(io.BytesIO(r.content),
                                     columns=["Code", "Name", "Date", "Open", "High", "Low", "Close", "Volume", "Marcap"]))
    d = pd.concat(parts)
    d["Date"] = pd.to_datetime(d.Date); d["Code"] = d.Code.astype(str).str.zfill(6)
    try:                                   # marcap 이 하루 늦으면 KRX 캐시 당일분으로 보충
        import krx_listing
        l = krx_listing.stock_listing("KRX", verbose=False)
        asof = pd.Timestamp(l.attrs.get("asof") or date.today())
        if asof > d.Date.max():
            l = l.assign(Date=asof)
            for c in ("Open", "High", "Low", "Close", "Volume"):
                l[c] = pd.to_numeric(l.get(c), errors="coerce")
            d = pd.concat([d, l[["Code", "Name", "Date", "Open", "High", "Low", "Close", "Volume", "Marcap"]]])
    except Exception as e:
        print("  (당일 보충 생략:", str(e)[:80], ")")
    d = d[(d.Close > 0) & (d.High > 0)].drop_duplicates(["Code", "Date"], keep="last")
    return d.sort_values(["Code", "Date"])


def _metrics(d, asof):
    d = d[(d.Date <= asof) & (d.Date > asof - pd.Timedelta(days=366))]
    rows = {}
    for code, g in d.groupby("Code"):
        if len(g) < 200 or g.Date.iloc[-1] != asof:
            continue
        hi = g.High.iloc[:-1].max(); c = g.Close.iloc[-1]
        rows[code] = dict(close=c, dist=(c / hi - 1) * 100, ret12=(c / g.Close.iloc[0] - 1) * 100,
                          marcap=g.Marcap.iloc[-1])
    m = pd.DataFrame(rows).T
    big = m[m.marcap >= 3e11].copy()
    big["rs"] = big.ret12.rank(pct=True) * 100
    return m, big


def _asof(d, prices):
    """앱 현재가와 원천 종가가 일치하는 날짜의 최빈값."""
    last = d[d.Date >= d.Date.max() - pd.Timedelta(days=10)]
    hits = []
    for code, p in prices.items():
        g = last[last.Code == code]
        m = g[(g.Close - p).abs() <= p * 0.001]
        if len(m):
            hits.append(m.Date.iloc[-1])
    return pd.Series(hits).mode().iloc[0] if hits else d.Date.max()


def _intraday(now=None) -> bool:
    """KR 정규장(+동시호가 여유) 중인가 — KST 평일 09:00~15:40."""
    k = (now or datetime.now(timezone.utc)) + timedelta(hours=9)
    return k.weekday() < 5 and (9 * 60) <= k.hour * 60 + k.minute < (15 * 60 + 40)


def main():
    d = _src()
    perf = json.load(open("results/perf_latest.json", encoding="utf-8"))
    kr = [s for s in perf.get("stocks", []) if s.get("market") == "KR"]
    can = json.load(open("results/canslim_latest.json", encoding="utf-8")).get("stocks", [])
    prices = {s["sym"]: s.get("curr_price") for s in kr if s.get("curr_price")}
    sample = dict(list(prices.items())[:120]) or {s["sym"]: None for s in can}
    asof = _asof(d, {k: v for k, v in sample.items() if v}) if any(sample.values()) else d.Date.max()
    m, big = _metrics(d, asof)
    intraday = _intraday()
    res = {"generated": date.today().isoformat(), "asof": str(asof.date()), "intraday": intraday, "checks": {}}

    def put(k, n, ok, th, note, skip=False):
        rate = ok / n if n else None
        res["checks"][k] = dict(n=int(n), ok=int(ok), rate=None if rate is None else round(rate, 3),
                                threshold=th, pass_=None if skip else bool(n and rate >= th),
                                note=note + (" · 장중 실행이라 판정 생략(참고값)" if skip else ""))

    # ① 가격
    pr = [(s["sym"], s["curr_price"]) for s in kr if s.get("curr_price") and s["sym"] in m.index]
    # 3%: 앱 시세(네이버)는 넥스트레이드 애프터마켓 가격이 섞여 KRX 종가와 1~2% 어긋난다(10-08 실측
    #     119/684종, 어느 날 종가와도 불일치). 그건 오류가 아니다. 3% 를 넘으면 다른 날 가격이다.
    put("perf_price", len(pr), sum(abs(m.at[c, "close"] / p - 1) <= 0.03 for c, p in pr), 0.9, "현재가 3% 이내", skip=intraday)
    # ② 52주 신호
    sg = [(s["sym"], bool(s.get("now_sig_52w"))) for s in kr if s["sym"] in m.index]
    put("perf_52w", len(sg), sum((m.at[c, "dist"] >= -3) == v for c, v in sg), 0.9, "52주 신고가 -3% 판정 일치")
    # ③④ CANSLIM
    cn = [s for s in can if s["sym"] in big.index and s.get("n_dist_pct") is not None]
    put("canslim_N", len(cn), sum(abs(big.at[s["sym"], "dist"] - s["n_dist_pct"]) <= 1.5 for s in cn), 0.9, "N 거리 1.5%p 이내", skip=intraday)
    put("canslim_RS", len(cn), sum(abs(big.at[s["sym"], "rs"] - (s.get("rs_pct") or 0)) <= 10 for s in cn), 0.85, "RS ±10 이내")
    # ⑤ 커버리지
    cov = len(set(s["sym"] for s in kr) & set(big.index))
    res["checks"]["coverage"] = dict(n=len(big), ok=cov, rate=round(cov / len(big), 3) if len(big) else None,
                                     threshold=0.8, pass_=bool(len(big) and cov / len(big) >= 0.8),
                                     note="원천 시총 3,000억+ 중 perf 에 있는 비율")
    res["source_52w_near"] = int((big.dist >= -3).sum())
    res["app_52w_near"] = int(sum(1 for s in kr if s.get("now_sig_52w")))
    # 신고가 근접은 희소하다(수 %). '전부 False' 여도 일치율 ②는 97% 가 나온다 — 10-13 의
    # 0/1,065 버그가 정확히 그 모양이었다. 그래서 **개수**를 따로 비교한다.
    sn, an = res["source_52w_near"], res["app_52w_near"]
    if sn >= 5:
        r = an / sn
        res["checks"]["perf_52w_count"] = dict(n=sn, ok=an, rate=round(r, 2), threshold=0.3,
                                              pass_=bool(0.3 <= r <= 3.0),
                                              note="앱/원천 신고가 근접 종목 수 비 (0.3~3배 · 주봉 vs 일봉 차 허용)")
    bad = [k for k, v in res["checks"].items() if v["n"] and v["pass_"] is False]
    empty = [k for k, v in res["checks"].items() if not v["n"]]
    res["ok"] = not bad and not empty
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    for k, v in res["checks"].items():
        mark = "✅" if v["pass_"] else ("⚪" if not v["n"] or v["pass_"] is None else "❌")
        print(f"{mark} {k:11s} {v['ok']}/{v['n']} ({v['rate']}) 기준 {v['threshold']} — {v['note']}")
    print(f"기준일 {res['asof']} · 원천 52주 신고가 근접 {res['source_52w_near']}종 / 앱 {res['app_52w_near']}종")
    if not res["ok"]:
        msg = (f"🔎 [screener] KR 원천 대조 불일치 ({res['asof']})\n"
               + "\n".join(f"· {k}: {res['checks'][k]['rate']} < {res['checks'][k]['threshold']} ({res['checks'][k]['note']})" for k in bad)
               + ("\n· 대조 불가(앱 데이터 없음): " + ", ".join(empty) if empty else ""))
        try:
            import config
            from telegram_notifier import send_message
            if config.TELEGRAM_ENABLED:
                send_message(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, msg)
        except Exception as e:
            print("텔레그램 실패:", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
