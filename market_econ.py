"""경제 지표 — 일정·예상치(ForexFactory 주간 JSON) + 실제치(FRED). 2026-11-26 차니:
"PCE 예상치 상회로 나스닥 -4%까지 갔다가 살아 돌아왔는데 그게 시황에 없다."

- 일정·예상·이전: https://nfs.faireconomy.media/ff_calendar_{thisweek,nextweek}.json (미국 '중요(High)'만)
- 실제치: FRED — 그 지표 시리즈가 **발표일 당일 갱신됐을 때만** 쓴다(옛 값을 실제치로 착각하지 않게).
- 못 구한 값은 비운다. 예상 대비 판정은 실제치·예상치가 둘 다 있을 때만.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

import requests

FF = "https://nfs.faireconomy.media/ff_calendar_{}.json"
KST = timezone(timedelta(hours=9))

# FF 제목 → (한글 이름, FRED 시리즈, 변환)
MAP = {
    "Core PCE Price Index m/m": ("근원 PCE 물가(전월비)", "PCEPILFE", "mm"),
    "PCE Price Index m/m": ("PCE 물가(전월비)", "PCEPI", "mm"),
    "Core CPI m/m": ("근원 CPI(전월비)", "CPILFESL", "mm"),
    "CPI m/m": ("CPI(전월비)", "CPIAUCSL", "mm"),
    "CPI y/y": ("CPI(전년비)", "CPIAUCSL", "yy"),
    "Non-Farm Employment Change": ("비농업 고용", "PAYEMS", "diff_k"),
    "Unemployment Rate": ("실업률", "UNRATE", "level"),
    "Unemployment Claims": ("신규 실업수당 청구", "ICSA", "level_k"),
    "Advance GDP q/q": ("GDP 속보치(연율)", "A191RL1Q225SBEA", "level"),
    "Prelim GDP q/q": ("GDP 잠정치(연율)", "A191RL1Q225SBEA", "level"),
    "Final GDP q/q": ("GDP 확정치(연율)", "A191RL1Q225SBEA", "level"),
    "Retail Sales m/m": ("소매판매(전월비)", "RSAFS", "mm"),
    "PPI m/m": ("PPI(전월비)", "PPIFIS", "mm"),
    "Federal Funds Rate": ("미국 기준금리", "DFEDTARU", "level"),
    "ISM Manufacturing PMI": ("ISM 제조업", None, None),
    "ISM Services PMI": ("ISM 서비스업", None, None),
    "FOMC Statement": ("FOMC 성명", None, None),
    "FOMC Meeting Minutes": ("FOMC 의사록", None, None),
    "Fed Chair Powell Speaks": ("파월 의장 발언", None, None),
}


def _num(s):
    m = re.search(r"-?\d+(?:\.\d+)?", str(s or ""))
    return float(m.group()) if m else None


def _ff():
    out = []
    for w in ("thisweek", "nextweek"):
        try:
            r = requests.get(FF.format(w), timeout=15, headers={"User-Agent": "Mozilla/5.0 (market-report)"})
            if r.ok:
                out += r.json()
        except Exception as e:
            print(f"  경제 일정({w}) 실패:", str(e)[:60])
    return out


def _fred(sid, how, release_et_date):
    key = os.environ.get("FRED_KEY")
    if not key or not sid:
        return None
    base = "https://api.stlouisfed.org/fred/"
    try:
        meta = requests.get(base + "series", params=dict(series_id=sid, api_key=key, file_type="json"), timeout=15).json()
        upd = (meta.get("seriess") or [{}])[0].get("last_updated", "")[:10]
        if upd != release_et_date:          # 발표일에 갱신되지 않았으면 옛 값 — 쓰지 않는다
            return None
        obs = requests.get(base + "series/observations", params=dict(series_id=sid, api_key=key, file_type="json",
                                                                       sort_order="desc", limit=14), timeout=15).json()
        v = [float(o["value"]) for o in obs.get("observations", []) if o.get("value") not in (".", None)]
    except Exception as e:
        print(f"  FRED {sid} 실패:", str(e)[:60])
        return None
    if len(v) < 2:
        return None
    if how == "mm":
        return f"{(v[0] / v[1] - 1) * 100:.1f}%"
    if how == "yy" and len(v) >= 13:
        return f"{(v[0] / v[12] - 1) * 100:.1f}%"
    if how == "diff_k":
        return f"{v[0] - v[1]:.0f}K"
    if how == "level_k":
        return f"{v[0] / 1000:.0f}K"
    if how == "level":
        return f"{v[0]:.1f}%" if sid != "DFEDTARU" else f"{v[0]:.2f}%"
    return None


def _verdict(actual, forecast):
    a, f = _num(actual), _num(forecast)
    if a is None or f is None:
        return None
    return "상회" if a > f else "하회" if a < f else "부합"


def facts(report_et_date: str, days_ahead: int = 7) -> dict:
    """report_et_date(미국 날짜) 에 나온 지표(실제치 포함) + 그 뒤 days_ahead 일 일정."""
    today, upcoming = [], []
    d0 = datetime.fromisoformat(report_et_date).date()
    for e in _ff():
        if e.get("country") != "USD" or e.get("impact") != "High":
            continue
        try:
            t_et = datetime.fromisoformat(e["date"])
        except Exception:
            continue
        name, sid, how = MAP.get(e.get("title"), (e.get("title"), None, None))
        row = dict(name=name, title=e.get("title"), et=t_et.strftime("%Y-%m-%d %H:%M"),
                   kst=t_et.astimezone(KST).strftime("%m-%d %H:%M"), kst_date=t_et.astimezone(KST).strftime("%Y-%m-%d"),
                   forecast=e.get("forecast") or None,
                   previous=e.get("previous") or None)
        if t_et.date() == d0:
            row["actual"] = _fred(sid, how, report_et_date)
            row["vs"] = _verdict(row["actual"], row["forecast"])
            today.append(row)
        elif d0 < t_et.date() <= d0 + timedelta(days=days_ahead):
            upcoming.append(row)
    return dict(today=today, upcoming=upcoming[:6])


def line_en(r: dict) -> str:
    if r.get("actual"):
        s = f"{r['title']} {r['actual']}" + (f" vs {r['forecast']} expected" if r.get("forecast") else "")
        return s + (f" (prior {r['previous']})" if r.get("previous") else "")
    return f"{r['title']}" + (f" (exp. {r['forecast']}, prior {r['previous']})" if r.get("forecast") else "")


def line(r: dict) -> str:
    """'근원 PCE 물가(전월비) 0.4% — 예상 0.3% 상회 (이전 0.3%)'"""
    if r.get("actual"):
        s = f"{r['name']} {r['actual']}"
        if r.get("forecast"):
            s += f" — 예상 {r['forecast']}" + (f" {r['vs']}" if r.get("vs") else "")
        return s + (f" (이전 {r['previous']})" if r.get("previous") else "")
    return f"{r['name']} 발표" + (f" (예상 {r['forecast']}, 이전 {r['previous']})" if r.get("forecast") else "")


if __name__ == "__main__":
    import sys
    print(json.dumps(facts(sys.argv[1] if len(sys.argv) > 1 else datetime.now(KST).strftime("%Y-%m-%d")), ensure_ascii=False, indent=1))
