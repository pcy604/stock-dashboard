"""시황의 '왜' — 그날 가장 큰 움직임에 붙일 뉴스 제목과 출처(2026-11-24 차니: "이유 붙이면 당연히 좋죠").

원칙
- **요약하지 않는다.** 뉴스 제목을 그대로, 언론사 이름과 함께 붙인다. 지어낼 여지를 없앤다.
- 리포트 날짜 기준 36시간 안에 나온 기사만. 못 찾으면 비운다(빈칸이 틀린 이유보다 낫다).
- 출처: Google News RSS(한국어). 해외 서버(GitHub Actions)에서 닿는다.
"""
import html
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import requests

_JUNK = re.compile(r"\[포토\]|\[사진\]|\[영상\]|광고|이벤트|무료|리딩방|급등주 추천|특징주 TOP|오늘의 운세|\[공시\]|코인|비트코인 시세")
_UA = {"User-Agent": "Mozilla/5.0 (market-report)"}


def _rss(q: str, hours=36, timeout=12) -> list:
    url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(q + " when:2d")
           + "&hl=ko&gl=KR&ceid=KR:ko")
    r = requests.get(url, headers=_UA, timeout=timeout)
    r.raise_for_status()
    now = datetime.now(timezone.utc)
    out = []
    for it in ET.fromstring(r.content).iter("item"):
        t = html.unescape(it.findtext("title") or "").strip()
        src = (it.findtext("source") or "").strip()
        if src and t.endswith(" - " + src):
            t = t[: -len(" - " + src)].strip()
        try:
            dt = parsedate_to_datetime(it.findtext("pubDate"))
        except Exception:
            continue
        if now - dt > timedelta(hours=hours) or _JUNK.search(t) or len(t) < 12:
            continue
        out.append(dict(title=t, source=src or "-", url=it.findtext("link"), date=dt.astimezone(timezone(timedelta(hours=9))).strftime("%m-%d %H:%M")))
    return out


def _pick(items, must=()):
    """제목에 must 단어 중 하나가 들어간 첫 기사. 같은 제목 반복은 하나로."""
    for it in items:
        if not must or any(m in it["title"] for m in must):
            return it
    return None


def find(targets: list) -> list:
    """targets = [(라벨, 검색어, 제목에 있어야 할 단어들)] → [{label, title, source, url, date}] (못 찾은 건 빠짐)."""
    out = []
    for label, q, must in targets:
        try:
            it = _pick(_rss(q), must)
        except Exception as e:
            print(f"  이유 뉴스 실패({q}):", str(e)[:80])
            it = None
        if it:
            out.append(dict(label=label, **it))
        time.sleep(0.5)
    return out


def targets_for(f: dict) -> list:
    """리포트 사실에서 '이유를 붙일 대상'을 고른다 — 지수 하나 + 가장 큰 움직임 1~2개."""
    kind = f.get("kind")
    T = []
    if kind == "kr":
        ks = next((x for x in f.get("indices") or [] if x.get("sym") == "^KS11"), {})
        if ks.get("d1") is not None:
            T.append(("코스피", "코스피 마감", ("코스피",)))
        kr = (f.get("stocks") or {}).get("KR") or {}
        th = (kr.get("themes_top") or [{}])[0]
        if th.get("name") and abs(th.get("ret") or 0) >= 3:
            lead = (th.get("lead") or [{}])[0].get("name")
            T.append((f"{th['name']} 테마", f"{lead or th['name']} 주가", tuple(x for x in (lead, th["name"].split("/")[0]) if x)))
    else:
        T.append(("뉴욕증시", "뉴욕증시 마감", ("뉴욕증시", "다우", "나스닥", "S&P")))
        mc = (f.get("us") or {}).get("megacaps") or []
        big = max(mc, key=lambda r: abs(r.get("d1") or 0), default=None)
        if big and abs(big.get("d1") or 0) >= 5:
            T.append((big["name"], f"{big['name']} 주가", (big["name"],)))
    return T


if __name__ == "__main__":
    import json, sys
    f = json.load(open("results/market_report.json", encoding="utf-8"))[f"latest_{sys.argv[1] if len(sys.argv) > 1 else 'kr'}"]["facts"]
    print(json.dumps(find(targets_for(f)), ensure_ascii=False, indent=1))
