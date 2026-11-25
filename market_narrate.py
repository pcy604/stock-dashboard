"""시황 문장 — AI 없이 사실에서 직접 쓴다(2026-11-25 차니: "AI체 없애자").

왜 규칙인가
- 11-24 AI 가 +14% 오른 반도체를 '약세를 이끌었다', +6.3% 오른 날을 '약세 흐름을 이어갔다'고 썼다.
  숫자에서 곧바로 만든 문장은 방향을 틀릴 수 없다.
- 문체: 증권사 마감 시황처럼 짧은 평서문 + 숫자. '견조한·모멘텀·투자심리·~로 보인다·주목된다' 같은 말은 쓰지 않는다.
- 이유는 뉴스 제목 그대로 + 언론사(market_why). 요약·해석하지 않는다.
"""


def _p(v, d=1):
    if v is None:
        return "-"
    s = f"{v:+.{d}f}%"
    return s[1:] if s.lstrip("+-").strip("0.%") == "" else s   # -0.0% → 0.0%


def _eok(v):
    if v is None:
        return "-"
    return f"{v / 1e4:+,.1f}조" if abs(v) >= 1e4 else f"{v:+,.0f}억"


def _idx(f, sym):
    return next((x for x in f.get("indices") or [] if x.get("sym") == sym and x.get("d1") is not None), None)


def _josa(word, a, b):
    """받침 있으면 a, 없으면 b (을/를, 이/가, 은/는)."""
    ch = (word or " ")[-1]
    if "가" <= ch <= "힣":
        return a if (ord(ch) - 0xAC00) % 28 else b
    return a if ch.isdigit() and ch in "0136789" else b


def summary(f):
    kind, ctx = f["kind"], f.get("ctx") or {}
    bc = ctx.get("breadth") or {}
    S = []
    if kind == "kr":
        ks, kq = _idx(f, "^KS11"), _idx(f, "^KQ11")
        if ks:
            S.append(f"코스피 {_p(ks['d1'])}({ks['close']:,.0f})" + (f", 코스닥 {_p(kq['d1'])}" if kq else "") + ".")
    else:
        sp, nq, sox = _idx(f, "^GSPC"), _idx(f, "^IXIC"), _idx(f, "^SOX")
        if sp:
            S.append(f"S&P500 {_p(sp['d1'])}" + (f", 나스닥 {_p(nq['d1'])}" if nq else "")
                     + (f", 필라델피아 반도체 {_p(sox['d1'])}" if sox and abs(sox["d1"]) >= 2 else "") + ".")
        mc = (f.get("us") or {}).get("megacaps") or []
        big = max(mc, key=lambda r: abs(r.get("d1") or 0), default=None)
        if big and sp and abs(big["d1"] or 0) >= 5 and (big["d1"] > 0) == (sp["d1"] > 0):
            S.append(f"{big['name']} {_p(big['d1'])}{_josa(big['name'], '이', '가')} {'상승' if big['d1'] > 0 else '하락'}을 이끌었다.")
    if bc:
        up = bc["today"] >= 50
        pct = bc["today"] if up else 100 - bc["today"]
        tail = (f"최근 {bc['n']}거래일 중 가장 넓은 {'상승' if up else '하락'}이었다" if bc["rank"] == (1 if up else bc["n"])
                else f"최근 {bc['n']}거래일 평균은 {bc['avg']}%다")
        lead = _idx(f, "^KS11" if kind == "kr" else "^GSPC")
        but = "지수는 " + ("올랐지만" if lead["d1"] > 0 else "내렸지만") + " " if lead and abs(lead["d1"]) >= 0.2 and (lead["d1"] > 0) != up else ""
        S.append(f"{but}대형주 {pct}%가 {'올랐고' if up else '내렸고'}, {tail}.")
    fl = ((ctx.get("flow") or {}).get("today") or {}).get("KOSPI") if kind == "kr" else None
    if fl and fl.get("외국인") is not None and fl.get("기관") is not None:
        a, b = fl["외국인"], fl["기관"]
        if (a > 0) == (b > 0):
            S.append(f"외국인·기관이 코스피에서 {_eok(abs(a + b))[1:]}를 {'순매수' if a > 0 else '순매도'}했다.")
        else:
            S.append(f"코스피에서 외국인 {_eok(a)}, 기관 {_eok(b)}.")
    return " ".join(S)


def direction(f):
    kind = f["kind"]
    S = []
    # 2026-11-26 차니: "종목 각 시장에 맞게" — 미국판엔 한국 5주선 대신 미국 코어(S&P500 200일선)
    if kind != "kr":
        v = f.get("verdict") or {}
        if v.get("core_gap_200d") is not None:
            S.append(f"S&P500은 200일선보다 {abs(v['core_gap_200d']):.1f}% {'위' if v['core_gap_200d'] >= 0 else '아래'}다.")
    syms = ("^KS11", "^KQ11") if kind == "kr" else ()
    g = [(_idx(f, s) or {}) for s in syms]
    g = [x for x in g if (x.get("gate5w") or {}).get("on") is not None]
    if g:
        below = [x for x in g if not x["gate5w"]["on"]]
        if below:
            parts = []
            for x in below:
                lg = x["gate5w"].get("live_gap")
                parts.append(f"{x['name']} {abs(lg):.1f}% 아래" if lg is not None and lg < 0 else f"{x['name']} 오늘은 위({_p(lg)})")
            S.append("실전 규칙: 지난 금요일 종가가 주봉 5주선 아래라 신규 매수는 중지 상태다(오늘 기준 " + ", ".join(parts) + ").")
        else:
            S.append("실전 규칙: 코스피·코스닥 모두 주봉 5주선 위라 신규 매수가 가능하다.")
    for s in (("^KS11",) if kind == "kr" else ("^GSPC",)):
        x = _idx(f, s) or {}
        pz = x.get("pulse") or {}
        st = pz.get("state") or ""
        if not st:
            continue
        if pz.get("ftd_date"):
            S.append(f"오닐 기준 {x['name']}{_josa(x['name'], '은', '는')} {pz['ftd_date'][5:]} 팔로스루로 상승 확인 국면이다.")
        elif st.startswith("반등 시도"):
            n = pz.get("rally_day") or 0
            S.append(f"오닐 기준 {x['name']}{_josa(x['name'], '은', '는')} {st}다. 4거래일째부터 +1.25% 이상 상승·거래량 증가가 나오면 상승 확인으로 본다"
                     + (f"(앞으로 {4 - n}거래일)." if n < 4 else "."))
        else:
            S.append(f"오닐 기준 {x['name']}{_josa(x['name'], '은', '는')} '{st}' 단계, 최근 25거래일 분배일 {pz.get('dist_n', '-')}개.")
    return " ".join(S)


def breadth(f):
    kind = f["kind"]
    if kind == "kr":
        kr = (f.get("stocks") or {}).get("KR") or {}
        b, t = kr.get("breadth_all"), kr.get("turnover_tn") or {}
        nh = kr.get("new_high_52w") or {}
    else:
        u = (f.get("internals") or {}).get("US") or {}
        b, t, nh = u.get("breadth_all"), {}, u.get("new_high_52w") or {}
    S = []
    if b:
        S.append(f"상승 {b['up']:,}종, 하락 {b['down']:,}종" + (f", 상한가 {b['limit_up']}·하한가 {b['limit_down']}" if b.get("limit_up") is not None else "") + ".")
    if t:
        S.append("거래대금 " + ", ".join(f"{k} {v:,.1f}조" for k, v in t.items()) + ".")
    if nh.get("n") is not None:
        S.append(f"52주 신고가 {nh['n']}종.")
    return " ".join(S)


def flow(f):
    ctx = f.get("ctx") or {}
    fl = ctx.get("flow") or {}
    S = []
    for mk, nm in (("KOSPI", "코스피"), ("KOSDAQ", "코스닥")):
        tdy = (fl.get("today") or {}).get(mk)
        if tdy:
            S.append(f"{nm} 외국인 {_eok(tdy.get('외국인'))}, 기관 {_eok(tdy.get('기관'))}, 개인 {_eok(tdy.get('개인'))}.")
    cum = (fl.get("foreign_cum") or {}).get("KOSPI") or {}
    if cum.get("d20") is not None:
        same = None
        tdy = (fl.get("today") or {}).get("KOSPI") or {}
        if tdy.get("외국인") is not None:
            same = (tdy["외국인"] > 0) == (cum["d20"] > 0)
        S.append(f"외국인 코스피 20일 누적은 {_eok(cum['d20'])}" + ("." if same is None else ("로 오늘과 같은 방향이다." if same else "로 오늘과 반대 방향이다.")))
    cr = fl.get("credit")
    if cr:
        S.append(f"신용잔고 {cr['tn']:,}조({str(cr['date'])[5:]}), 고점({str(cr.get('peak_date'))[5:]})보다 {abs(cr['from_peak']):.1f}% {'적다' if cr['from_peak'] < 0 else '많다'}.")
    us = f.get("us") or {}
    if f["kind"] != "kr" and us.get("assets"):
        S.append(", ".join(f"{a['name']} {_p(a['d1'])}" for a in us["assets"][:4]) + ".")
    hy = f.get("hy") or {}
    if f["kind"] != "kr" and hy.get("close") is not None:
        S.append(f"하이일드 스프레드 {hy['close']}%({str(hy.get('date'))[5:]}).")
    return " ".join(S)


def sector(f):
    S = []
    if f["kind"] == "kr":
        kr = (f.get("stocks") or {}).get("KR") or {}
        sc = kr.get("sectors") or []
        if sc:
            S.append("강한 업종은 " + ", ".join(f"{r['name']} {_p(r['ret'])}" for r in sc[:3]) + ".")
            neg = [r for r in sc[::-1][:3] if r["ret"] < 0]
            S.append(("약한 업종은 " + ", ".join(f"{r['name']} {_p(r['ret'])}" for r in neg) + ".") if neg else "내린 업종은 없었다.")
        th = kr.get("themes_top") or []
        if th:
            S.append("테마는 " + ", ".join(f"{t['name']} {_p(t['ret'])}" for t in th[:2]) + ".")
    else:
        sc = ((f.get("internals") or {}).get("US") or {}).get("sectors") or []
        if sc:
            S.append("강한 업종은 " + ", ".join(f"{r['name']} {_p(r['ret'])}" for r in sc[:3]) + ".")
            neg = [r for r in sc[::-1][:3] if r["ret"] < 0]
            S.append(("약한 업종은 " + ", ".join(f"{r['name']} {_p(r['ret'])}" for r in neg) + ".") if neg else "내린 업종은 없었다.")
    return " ".join(S)


def stocks(f):
    S = []
    if f["kind"] == "kr":
        kr = (f.get("stocks") or {}).get("KR") or {}
        if kr.get("top"):
            S.append("시총 1조 이상에서 " + ", ".join(f"{x['name']} {_p(x['ret'])}" for x in kr["top"][:3]) + "가 가장 많이 올랐다.")
        lu = [r for r in kr.get("featured") or [] if r.get("tag") == "상한가"]
        if lu:
            S.append("상한가 " + ", ".join(r["name"] for r in lu[:3]) + ".")
        tt = (kr.get("turnover_top") or [None])[0]
        if tt:
            S.append(f"거래대금 1위는 {tt['name']}({_p(tt['ret'])}, {tt['amt_b'] / 1e4:,.1f}조).")
    else:
        u = (f.get("internals") or {}).get("US") or {}
        if u.get("top"):
            S.append("시총 상위 500에서 " + ", ".join(f"{x['name']} {_p(x['ret'])}" for x in u["top"][:3]) + "가 가장 많이 올랐다.")
        if u.get("bottom"):
            S.append("가장 많이 내린 종목은 " + ", ".join(f"{x['name']} {_p(x['ret'])}" for x in u["bottom"][:2]) + ".")
    return " ".join(S)


def week52(f):
    h = (f.get("ctx") or {}).get("hilo") or {}
    if not h:
        return ""
    s = (f"이번 주 52주 신고가 {h['nh']:,}종, 신저가 {h['nl']:,}종({str(h.get('asof'))[5:]}까지 · 지난주 신고가 {h['prev_nh']:,}·신저가 {h['prev_nl']:,}).")
    if h.get("nl_over_nh_weeks", 0) >= 2:
        s += f" 신저가가 신고가보다 많은 주가 {h['nl_over_nh_weeks']}주째다."
    elif h["nh"] > h["nl"]:
        s += " 신고가가 신저가보다 많다."
    return s


def ledger(f):
    lg = (f.get("ctx") or {}).get("ledger") or {}
    if not lg:
        return ""
    s = f"실전 계좌는 {lg['n']}종 보유, 오늘 평균 {_p(lg['d1_avg'])}, 매수 후 평균 {_p(lg['pnl_avg'])}. 오늘 체결 {lg['trades_today']}건."
    if lg.get("near_stop"):
        s += " 손절선 5% 안: " + ", ".join(f"{r['name']}({abs(r['to_stop']):.1f}% 남음)" for r in lg["near_stop"]) + "."
    return s


def checkpoints(f):
    C = []
    for s in (("^KS11",) if f["kind"] == "kr" else ()):
        x = _idx(f, s) or {}
        g = x.get("gate5w") or {}
        lg = g.get("live_gap")
        if g.get("on") is False and lg is not None:
            ma = x["close"] / (1 + lg / 100)
            C.append(f"{x['name']} 5주선({ma:,.0f}) 회복 여부 — 금요일 종가로 판정, 오늘 종가와 {abs(lg):.1f}% 차이")
    ev = ((f.get("ctx") or {}).get("events") or [])
    if ev:
        e = ev[0]
        C.append(f"{e['date'][5:]}({e.get('wd', '')}) {(e.get('time') or '').strip()} {e['name']}".replace("  ", " "))
    x = _idx(f, "^KS11" if f["kind"] == "kr" else "^GSPC") or {}
    pz = x.get("pulse") or {}
    if str(pz.get("state", "")).startswith("반등 시도"):
        C.append(f"{x['name']} 반등 4거래일째부터 +1.25% 이상·거래량 증가(팔로스루)가 나오는지")
    cum = (((f.get("ctx") or {}).get("flow") or {}).get("foreign_cum") or {}).get("KOSPI") or {}
    if len(C) < 3 and cum.get("d20") is not None:
        C.append(f"외국인 순매수가 이어지는지 — 20일 누적 {_eok(cum['d20'])}")
    return C[:3]


def why_lines(f):
    return [f"{w['label']}: “{w['title']}” — {w['source']} ({w['date']})" for w in (f.get("why") or [])]


def narrate(f):
    return dict(summary=summary(f), why=why_lines(f), direction=direction(f), week52=week52(f), breadth=breadth(f), flow=flow(f),
                sector=sector(f), stocks=stocks(f), ledger=ledger(f), checkpoints=checkpoints(f))


def compose(f, n):
    title = {"daily": "미국 장 마감 시황", "kr": "한국 장 마감 시황", "weekly": "주간 시황"}.get(f["kind"], "시황")
    L = [f"## {title}", "", "## 한 줄 요약", n["summary"]]
    if n["why"]:
        L += ["", "**왜 움직였나 (뉴스 제목 그대로)**"] + [f"- {w}" for w in n["why"]]
    L += ["", "## 해설"]
    for k, lab in (("direction", "시장 방향"), ("week52", "52주 신고가·신저가"), ("breadth", "시장 폭"), ("flow", "돈의 흐름"), ("sector", "업종·테마"),
                   ("stocks", "종목"), ("ledger", "실전 원장")):
        if n.get(k):
            L.append(f"- **{lab}** {n[k]}")
    return "\n".join(L)
