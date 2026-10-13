"""시세 — P1 은 Yahoo v8 chart(무료, 레포의 다른 스크립트와 같은 경로). P2 에서 토스 시세로 교체."""
import json, urllib.request


def _weekly(sym, weeks=60):
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}?range=2y&interval=1wk"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    r = json.loads(urllib.request.urlopen(req, timeout=30).read())["chart"]["result"][0]
    c = [x for x in r["indicators"]["quote"][0]["close"] if x]
    return c[-weeks:]


def weekly_close(syms, core_sym, ma_weeks=40):
    px, above = {}, None
    for s in syms:
        try:
            c = _weekly(s)
            if c:
                px[s] = c[-1]
                if s == core_sym and ma_weeks and len(c) >= ma_weeks:
                    above = c[-1] > sum(c[-ma_weeks:]) / ma_weeks
        except Exception:
            pass
    return px, above
