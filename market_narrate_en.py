"""English market wrap — same facts, same order as the Korean card news (2026-11-26 차니: "글로벌 확장을 처음부터 같이").

Phase 1 = the US close (global audience). Rule-written like market_narrate: no AI prose, numbers straight from facts.
The 'what moved markets' paragraph is the one grounded-AI piece (English headlines only, same checks).
"""
from market_narrate import _idx, _josa  # noqa: F401  (shared helpers)

US_ASSET_EN = {"달러인덱스": "Dollar index", "금": "Gold", "WTI 유가": "WTI crude", "구리": "Copper", "미국 10년물": "US 10Y",
               "비트코인": "Bitcoin", "장기국채 ETF": "TLT"}


def _p(v, d=1):
    if v is None:
        return "-"
    s = f"{v:+.{d}f}%"
    return s[1:] if s.lstrip("+-").strip("0.%") == "" else s


def _ud(v):
    return "🔺" if (v or 0) > 0 else "🔻" if (v or 0) < 0 else "▫️"


def _ind_en(ko):
    try:
        import market_internals as MI
        rev = {v: k for k, v in MI.IND_KO.items()}
        return rev.get(ko, ko)
    except Exception:
        return ko


def summary(f):
    S = []
    sp, nq, sox = _idx(f, "^GSPC"), _idx(f, "^IXIC"), _idx(f, "^SOX")
    if sp:
        S.append(f"S&P 500 {_p(sp['d1'])}" + (f", Nasdaq {_p(nq['d1'])}" if nq else "")
                 + (f", Philly Semis {_p(sox['d1'])}" if sox and abs(sox["d1"]) >= 2 else "") + ".")
    if nq and nq.get("lo_pct") is not None:
        if nq["d1"] - nq["lo_pct"] >= 1.5:
            S.append(f"The Nasdaq fell as much as {_p(nq['lo_pct'])} intraday before closing {_p(nq['d1'])} "
                     f"({nq['d1'] - nq['lo_pct']:.1f}pt off the low).")
        elif nq.get("hi_pct") is not None and nq["hi_pct"] - nq["d1"] >= 1.5:
            S.append(f"The Nasdaq was up as much as {_p(nq['hi_pct'])} intraday before closing {_p(nq['d1'])}.")
    bc = (f.get("ctx") or {}).get("breadth") or {}
    if bc:
        up = bc["today"] >= 50
        pct = bc["today"] if up else 100 - bc["today"]
        but = ""
        if sp and abs(sp["d1"]) >= 0.2 and (sp["d1"] > 0) != up:
            but = "Under the surface, "
        S.append(f"{but}{pct}% of large caps {'rose' if up else 'fell'} (30-day average share of gainers: {bc['avg']}%).")
    return " ".join(S)


def signal(f):
    x = _idx(f, "^GSPC") or {}
    pz, v = x.get("pulse") or {}, f.get("verdict") or {}
    st, gap = str(pz.get("state") or ""), v.get("core_gap_200d")
    above = gap is not None and gap >= 0
    ma = f" S&P 500 is {abs(gap):.1f}% {'above' if above else 'below'} its 200-day average." if gap is not None else ""
    if pz.get("ftd_date") and above:
        return "🟢", f"Confirmed uptrend — follow-through day on {pz['ftd_date'][5:]}." + ma
    if st.startswith("반등 시도"):
        n = pz.get("rally_day") or 0
        return "🟡", (f"Rally attempt, day {n}. O'Neil's method waits for a follow-through day (day 4+, +1.25% or more on higher volume)"
                      " before new buys" + (f" — earliest in {4 - n} session(s)." if n < 4 else ".") + ma)
    return "🔴", (f"Market in correction — {pz.get('dist_n', '-')} distribution days in the last 25 sessions." + ma
                  + " No new buys until a rally attempt starts.")


def breadth(f):
    u = (f.get("internals") or {}).get("US") or {}
    b, nh, nl = u.get("breadth_all"), u.get("new_high_52w") or {}, u.get("new_low_52w") or {}
    L = []
    if b:
        L.append(f"Advancers {b['up']:,} · Decliners {b['down']:,} ({u.get('universe', 0):,} stocks)")
    if nh.get("n") is not None:
        L.append(f"52-week highs today {nh['n']:,}" + (f" · lows {nl['n']:,}" if nl.get("n") is not None else ""))
    h = (f.get("ctx") or {}).get("hilo") or {}
    if h:
        L.append(f"This week: highs {h['nh']:,} · lows {h['nl']:,} (last week {h['prev_nh']:,} · {h['prev_nl']:,})")
    return "\n".join(L)


def flow_stocks(f):
    us, u = f.get("us") or {}, (f.get("internals") or {}).get("US") or {}
    L = []
    if us.get("assets"):
        L.append(" · ".join(f"{_ud(a['d1'])}{US_ASSET_EN.get(a['name'], a['name'])} {_p(a['d1'])}" for a in us["assets"][:4]))
    if u.get("top"):
        L.append(" · ".join(f"{_ud(x['ret'])}{x['name']} {_p(x['ret'])}" for x in u["top"][:3]))
    if u.get("bottom"):
        L.append(" · ".join(f"{_ud(x['ret'])}{x['name']} {_p(x['ret'])}" for x in u["bottom"][:3]))
    return "\n".join(L)


def sector(f):
    sc = ((f.get("internals") or {}).get("US") or {}).get("sectors") or []
    if not sc:
        return ""
    neg = [r for r in sc[::-1][:3] if r["ret"] < 0]
    return "\n".join([" · ".join(f"🔺{_ind_en(r['name'])} {_p(r['ret'])}" for r in sc[:3]),
                      " · ".join(f"🔻{_ind_en(r['name'])} {_p(r['ret'])}" for r in neg) or "No industry fell"])


def narrate(f):
    light, sig = signal(f)
    return dict(summary=summary(f), explain=f.get("explain_en") or "",
                why=[f"“{w['title']}” — {w['source']}" for w in (f.get("why_en") or [])],
                light=light, signal=sig, breadth=breadth(f), flow_stocks=flow_stocks(f), sector=sector(f))


def compose(f, n, date):
    L = [f"🇺🇸 US Market Close · {date}", "", "① Today", n["summary"]]
    if n["explain"] or n["why"]:
        L += ["", "📰 What moved markets"] + ([n["explain"]] if n["explain"] else []) + [f"· {w}" for w in n["why"][:2]]
    L += ["", f"② Market signal {n['light']}", n["signal"], "", "③ Breadth · 52-week highs/lows", n["breadth"],
          "", "④ Assets · Stocks", n["flow_stocks"], "", "⑤ Industries", n["sector"], "",
          "Rule-written from data · not investment advice"]
    return "\n".join(L)


BANNED_EN = ("amid", "sentiment", "momentum", "investors are", "appears", "likely", "suggest", "underscore", "navigat",
             "landscape", "robust", "!")
EXPLAIN_PROMPT_EN = """Using ONLY the headlines below, write exactly 2 sentences (max 260 characters) on why US stocks moved today.
Sentence 1 = the cause. Sentence 2 = how the market reacted, including the intraday swing if any.
No facts or numbers that are not in the headlines or [facts]. Plain wire-service style, past tense.
Do not use: amid, sentiment, momentum, appears, likely, suggests, underscores, robust.
If headlines disagree, use the cause mentioned most often.
[facts] {facts}
[headlines]
{heads}
Answer with the two sentences only."""


def explain_facts(f):
    x = _idx(f, "^IXIC") or {}
    return f"Nasdaq {_p(x.get('d1'))} (intraday low {_p(x.get('lo_pct'))}, high {_p(x.get('hi_pct'))})"


def check_explain(txt, heads, f):
    import re
    bad = []
    txt = (txt or "").strip()
    if not txt or len(txt) > 300:
        bad.append(f"length {len(txt)}")
    bad += [f"banned '{w}'" for w in BANNED_EN if w.lower() in txt.lower()]
    pool = " ".join(h["title"] for h in heads) + " " + explain_facts(f) + " " + summary(f)
    for num in re.findall(r"\d+(?:\.\d+)?", txt):
        if num not in pool:
            bad.append(f"unbacked number {num}")
    return bad
