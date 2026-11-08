# -*- coding: utf-8 -*-
"""실전 시범 주문 봇 — 사람 손 없이 live/plan_latest.json + 원장 규칙대로 토스에 주문 (v1.7 한국 단독, 2026-11-04)

  python live/bot.py              모의: 낼 주문만 계산해 보고(원장·계좌 변화 0)
  python live/bot.py --send       + 텔레그램 보고
실전 주문은 live/switch.json 의 "live": true **그리고** 환경변수 LIVE_TRADING=ON 둘 다일 때만 나간다.

왜 노트북(또는 고정 IP 서버)에서만 도는가: 토스 Open API 는 허용 IP 에서만 응답한다(broker_toss.py 주석).

실행 시각(2026-11-09 개정 — 백테스트처럼 '시가'에 산다):
  작업 스케줄러가 평일 00:40·01:10·08:40·09:10(노트북 현지 시각) 깨운다 → 한국에선 08:40·09:10, 폴란드(겨울)에선 00:40·01:10 이 KST 08:40·09:10.
  ① 08:31~08:58 KST '시가 단일가' 창: 매도 = 시장가, 매수 = 전날 종가 +10% 지정가 → 둘 다 09:00 시가 한 가격으로 체결(백테스트 '다음 주 시가 체결'과 같음).
     매수를 지정가로 두는 이유: 시장가 매수는 증권사가 상한가(+30%) 기준으로 현금을 묶어 소액 계좌에선 거부될 수 있고, +10% 넘는 갭은 쫓지 않는다.
  ② 09:05~15:10 KST 정규장 창: 지난 실행의 체결 확인 + 시가 창에서 거부·누락된 주문만 시장가로 다시(clientOrderId 로 이중 주문 없음).
  그 밖의 시각은 기록만 남기고 끝(--force 로 무시).
순서:
  ① 대조   토스 국내 보유 ↔ 원장. 원장 종목 수량이 다르면 = 규칙 밖 거래 → live/violations.jsonl·경보·이번 실행 중단
  ② 손절   전날 종가 ≤ 손절선(보유 중 최고 종가 −20%, 올라가기만) → 전량 시장가 매도
  ③ 불타기 전날 종가 ≥ 첫 매수가 +10% · 소속 시장(코스피/코스닥) 주봉 5주선 위 · 아직 안 했으면 → 목표 비중 40% 만큼 정수 주
  ④ 신규   이번 주 계획표의 매수(작성 7일 이내, 원장에 없음, 손절 후 2주 냉각 아님) → 정수 주 시장가
  같은 주문은 clientOrderId(계획일·종목·행동)로 두 번 나가지 않는다.
"""
import argparse, json, math, os, sys, time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
LIVE = ROOT / "live"
LEDGER, PLAN, SWITCH = LIVE / "ledger.json", LIVE / "plan_latest.json", LIVE / "switch.json"
TRADES, VIOL = LIVE / "trades.jsonl", LIVE / "violations.jsonl"
M = "KR"                                                # v1.7 한국 단독
SLOTS, FIRST, STOP, CAP = 10, 0.50, 0.20, 0.35          # v1.9(2026-11-08): 보유 10 · 첫 50% · 1회 주문 상한 = 슬리브 35%
ADD_STEPS = ((0.10, 0.25), (0.20, 0.25))                # v1.9: 첫 매수가 +10%·+20%에 목표의 25%씩(각 1회)
TRIM_CAP = 0.30   # v1.8(2026-11-07): 종목 비중이 30%×1.05 를 넘으면 30% 까지 덜어낸다(주 1회) — 계획표 표시만 되던 구멍. 목표 20% 까지 덜기는 검증 불합격
COOL_DAYS = 14
KST = timezone(timedelta(hours=9))
PRE_LIMIT = 0.10                                        # 시가 단일가 매수 지정가 = 전날 종가 +10% (2026-11-09)


def _load(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def _append(p, row):
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def is_live():
    return _load(SWITCH, {}).get("live") is True and os.environ.get("LIVE_TRADING", "").upper() == "ON"


def board():
    """코드 → 'KR'(코스피) | 'KQ'(코스닥). plan.py 와 같은 data/krx_listing_last.csv"""
    try:
        import pandas as pd
        d = pd.read_csv(ROOT / "data" / "krx_listing_last.csv", dtype={"Code": str}, usecols=["Code", "MarketId"])
        return {c.zfill(6): ("KQ" if mi == "KSQ" else "KR") for c, mi in zip(d.Code, d.MarketId)}
    except Exception:
        return {}


# ── 시세 ───────────────────────────────────────────────────────────────
def _naver_rows(xml: str):
    """fchart.stock.naver.com 일봉 XML → [(date, close)] — <item data="YYYYMMDD|시|고|저|종|거래량" />"""
    import re
    out = []
    for d, c in re.findall(r'data="(\d{8})\|[^|]*\|[^|]*\|[^|]*\|([0-9.]+)\|', xml or ""):
        out.append((date(int(d[:4]), int(d[4:6]), int(d[6:])), float(c)))
    return out


def _naver_close(sym, today):
    """네이버 일봉 — 한국 가격 1순위(2026-11-09: 노트북에서 yfinance 가 전 종목 'Expecting value' 로 실패)."""
    import requests
    r = requests.get("https://fchart.stock.naver.com/sise.nhn",
                     params=dict(symbol=sym, timeframe="day", count=30, requestType=0),
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    rows = [x for x in _naver_rows(r.text) if x[0] < today and x[1] > 0]
    return (rows[-1][1], str(rows[-1][0])) if rows else None


def last_closes(syms):
    """확정된 마지막 일봉 종가(오늘 진행 중 봉 제외, KST). 네이버 → yfinance 순. 못 받으면 그 종목은 빠진다 — 있는 척하지 않는다."""
    out = {}
    if not syms:
        return out
    today = datetime.now(KST).date()
    for s in syms:
        try:
            v = _naver_close(s, today)
            if v:
                out[s] = v; continue
        except Exception:
            pass
        try:
            import yfinance as yf
        except Exception:
            continue
        for t in (f"{s}.KS", f"{s}.KQ"):
            try:
                h = yf.Ticker(t).history(period="1mo", auto_adjust=False)["Close"].dropna()
                h = h[[d.date() < today for d in h.index]]
                if len(h):
                    out[s] = (float(h.iloc[-1]), str(h.index[-1])[:10]); break
            except Exception:
                pass
    return out


# ── 판단 (순수 함수 · 테스트 대상) ─────────────────────────────────────
def reconcile(ledger_pos, toss_hold):
    """원장 종목만 비교한다. 원장에 없는 토스 국내 종목(시스템 밖 기존 보유)은 '레거시'로 보고만."""
    t = {h["sym"]: h["qty"] for h in toss_hold if (h.get("market") or "").upper() == "KR"}
    diff = [dict(sym=s, ledger=p["shares"], toss=t.get(s, 0)) for s, p in ledger_pos.items() if int(t.get(s, 0)) != int(p["shares"])]
    return diff, sorted(s for s in t if s not in ledger_pos)


def _adds(p) -> int:
    """불타기 몇 차까지 했나 — v1.8 이전 원장('added' 참/거짓)도 읽는다."""
    return int(p.get("adds", 1 if p.get("added") else 0))


def gate_ok(plan, sym, bmap):
    ix = (plan.get("index") or {}).get(bmap.get(sym, "KR")) or {}
    return bool(ix.get("ok", False))


def decide(L, plan, closes, bmap, today=None):
    """원장·계획표·전날 종가 → 주문 목록. 원장은 바꾸지 않는다."""
    today = today or datetime.now(KST).date()
    S, P = L[M], (plan.get("sleeves") or {}).get(M) or {}
    done, pend = set(L.get("done_ids", [])), set(L.get("pending", {}))
    equity = S["cash_krw"] + sum(p["shares"] * closes.get(s, (p["last_px"],))[0] for s, p in S["positions"].items())
    target = equity / SLOTS
    orders, notes = [], []

    made = plan.get("made")
    fresh = bool(made) and (today - date.fromisoformat(made)) <= timedelta(days=7)
    rs_out = {x["sym"]: x.get("rs") for x in (P.get("exits") or [])} if fresh else {}
    for sym, p in S["positions"].items():
        if sym not in closes:
            notes.append(f"{p.get('name', sym)} 종가 못 받음 — 손절·불타기 판정 보류"); continue
        c, d = closes[sym]
        peak = max(p.get("peak", p["avg"]), c)
        stop = max(p.get("stop", p["avg"] * (1 - STOP)), peak * (1 - STOP))
        if c <= stop:
            orders.append(dict(sym=sym, name=p.get("name"), side="SELL", quantity=int(p["shares"]), px=c,
                               why=f"손절: {d} 종가 {c:,.0f} ≤ 손절선 {stop:,.0f}(최고 {peak:,.0f})", cid=f"{d}-{sym}-STOP"))
        elif sym in rs_out:                                      # v1.9 주도주 탈락(계획표 RS < 70) → 전량 매도
            orders.append(dict(sym=sym, name=p.get("name"), side="SELL", quantity=int(p["shares"]), px=c,
                               why=f"주도주 탈락: RS {rs_out[sym]} < 70 (계획표 {plan.get('made')})", cid=f"{plan.get('made')}-{sym}-RSOUT"))
        elif equity > 0 and p["shares"] * c / equity > TRIM_CAP * 1.05:
            q = math.floor((p["shares"] * c - TRIM_CAP * equity) / c)
            if 1 <= q < p["shares"]:
                yw = date.fromisoformat(d).isocalendar()
                orders.append(dict(sym=sym, name=p.get("name"), side="SELL", quantity=q, px=c, trim=True,
                                   why=f"상한 덜기: 비중 {p['shares'] * c / equity * 100:.0f}% > {TRIM_CAP * 100:.0f}% → {TRIM_CAP * 100:.0f}%",
                                   cid=f"{yw[0]}W{yw[1]:02d}-{sym}-TRIM"))
        elif _adds(p) < len(ADD_STEPS) and c >= p["first_px"] * (1 + ADD_STEPS[_adds(p)][0]):
            at, f = ADD_STEPS[_adds(p)]
            q = math.floor(min(target * f, TRIM_CAP * equity - p["shares"] * c) / c)   # 불타기로 상한 30% 를 넘지 않게
            if not gate_ok(plan, sym, bmap):
                notes.append(f"{p.get('name', sym)} 불타기 조건 충족 — 소속 시장 5주선 아래라 보류")
            elif q < 1:
                notes.append(f"{p.get('name', sym)} 불타기 배정 {target * f:,.0f}원 < 1주 {c:,.0f}원")
            else:
                orders.append(dict(sym=sym, name=p.get("name"), side="BUY", quantity=q, px=c,
                                   why=f"불타기 {_adds(p) + 1}차: 종가 {c:,.0f} ≥ 첫 매수가 +{at * 100:.0f}% {p['first_px'] * (1 + at):,.0f}",
                                   cid=f"{sym}-{p['opened']}-ADD{_adds(p) + 1}"))

    free = SLOTS - len(S["positions"]) + sum(1 for s_ in S["positions"] if s_ in rs_out)
    if not fresh:
        notes.append(f"계획표 {made} — 7일 지나 신규 매수 없음(토요일 새 계획 대기)")
    else:
        for b in P.get("buys") or []:
            if free <= 0:
                break
            sym = b["sym"]
            if sym in S["positions"]:
                continue
            cd = (L.get("cooldown") or {}).get(sym)
            if cd and (today - date.fromisoformat(cd)).days < COOL_DAYS:
                notes.append(f"{b.get('name', sym)} 손절 후 2주 냉각 중"); continue
            if not gate_ok(plan, sym, bmap):
                notes.append(f"{b.get('name', sym)} 소속 시장 5주선 아래 — 신규 중지"); continue
            px = closes.get(sym, (b["ref_px"],))[0]
            q = math.floor(target * FIRST / px)
            if q < 1:
                notes.append(f"{b.get('name', sym)} 1주 {px:,.0f}원 > 배정 {target * FIRST:,.0f}원"); continue
            orders.append(dict(sym=sym, name=b.get("name"), side="BUY", quantity=q, px=px,
                               why=f"신규: {b.get('why', '')} RS{b.get('rs')}", cid=f"{made}-{sym}-BUY"))
            free -= 1

    return [o for o in orders if o["cid"] not in done and o["cid"] not in pend], notes, dict(equity_krw=round(equity), target_krw=round(target))


def guard(orders, L, plan, eq, cash_krw=None):
    """코드가 강제하는 안전장치. 걸린 주문은 빼고 이유를 남긴다."""
    ok, why = [], []
    allow = {b["sym"] for b in ((plan.get("sleeves") or {}).get(M) or {}).get("buys", [])} | set(L[M]["positions"])
    cap = eq["equity_krw"] * CAP
    left = (cash_krw if cash_krw is not None else L[M]["cash_krw"]) * 0.995          # 시장가 슬리피지·수수료 여유 0.5%
    for o in orders:
        if o["sym"] not in allow:
            why.append(f"{o['sym']} 계획표·원장에 없는 종목"); continue
        if o["side"] == "BUY":
            amt = o["quantity"] * o.get("lim", o["px"])          # 시가 창 지정가 매수는 지정가만큼 현금이 묶인다
            if amt > cap:
                why.append(f"{o['sym']} 1회 주문 {amt:,.0f}원 > 상한 {cap:,.0f}원"); continue
            if amt > left and "lim" in o and math.floor(left / o["lim"]) >= 1:   # 지정가 여유분 때문이면 수량만 줄인다
                o["quantity"] = math.floor(left / o["lim"]); amt = o["quantity"] * o["lim"]
            if amt > left:
                why.append(f"{o['sym']} 현금 부족({left:,.0f}원)"); continue
            left -= amt
        ok.append(o)
    return [o for o in ok if o["side"] == "SELL"] + [o for o in ok if o["side"] == "BUY"], why   # 매도 먼저


# ── 체결 반영 ──────────────────────────────────────────────────────────
def _fill(res):
    """주문 상세 응답에서 체결 수량·평균가. 필드 이름은 첫 실주문에서 확정(넓게 읽는다)."""
    def n(*ks):
        for k in ks:
            try:
                v = res.get(k)
                if v not in (None, ""):
                    return float(v)
            except (TypeError, ValueError, AttributeError):
                pass
        return None
    q = n("filledQuantity", "executedQuantity", "executionQuantity")
    px = n("averageFilledPrice", "averageExecutedPrice", "executionPrice", "avgPrice")
    return q, px, n("commission", "fee") or 0.0


def apply_fill(L, o, q, px, fee, day):
    S = L[M]; P = S["positions"]
    if o["side"] == "BUY":
        p = P.get(o["sym"])
        if p:                                                    # 불타기
            tot = p["shares"] + q
            p.update(avg=(p["avg"] * p["shares"] + px * q) / tot, shares=tot, adds=_adds(p) + 1, added=True)
        else:
            P[o["sym"]] = dict(name=o.get("name") or o["sym"], shares=q, avg=px, first_px=px, peak=px, stop=px * (1 - STOP),
                               added=False, adds=0, last_px=px, opened=day)
        S["cash_krw"] -= q * px + fee
    elif o.get("trim") and q < P[o["sym"]]["shares"]:           # 상한 덜기 — 일부만 판다(손절선·고점은 그대로)
        P[o["sym"]]["shares"] -= q
        S["cash_krw"] += q * px - fee
    else:
        P.pop(o["sym"])
        S["cash_krw"] += q * px - fee
        L.setdefault("cooldown", {})[o["sym"]] = day
    _append(TRADES, dict(day=day, sym=o["sym"], name=o.get("name"), side=o["side"], qty=q, px=px, fee=fee, why=o["why"], cid=o["cid"]))


def mark_peaks(L, closes):
    for s, p in L[M]["positions"].items():
        if s in closes:
            c = closes[s][0]
            p["last_px"], p["peak"] = c, max(p.get("peak", c), c)
            p["stop"] = max(p.get("stop", p["avg"] * (1 - STOP)), p["peak"] * (1 - STOP))


# ── 실행 ───────────────────────────────────────────────────────────────
def _keys():
    D = ROOT / "data"
    rd = lambda env, f: os.environ.get(env, "").strip() or ((D / f).read_text(encoding="utf-8").strip() if (D / f).exists() else "")
    return rd("TOSS_CLIENT_ID", ".toss_client_id"), rd("TOSS_CLIENT_SECRET", ".toss_client_secret")


def run(send=False, phase="reg"):
    live = is_live()
    L = _load(LEDGER, None); plan = _load(PLAN, {})
    L.setdefault("done_ids", []); L.setdefault("pending", {})
    day = str(datetime.now(KST).date())
    msg = [("🔴 실전" if live else "🧪 모의") + f" 주문 봇 {day} · 🇰🇷 · " + ("시가 단일가 창" if phase == "pre" else "정규장")]
    cid, sec = _keys()
    T = acct = cash = None
    if cid and sec:
        from executor.broker_toss import TossTrader, TossError
        try:
            T = TossTrader(cid, sec, live=live)
            accts = T.accounts()
            acct = (accts[0] or {}).get("accountSeq") if accts else None
            diff, legacy = reconcile(L[M]["positions"], T.holdings(acct))
            cash = T.cash(acct).get("KRW")
            if legacy:
                msg.append(f"  · 시스템 밖 국내 보유(건드리지 않음): {', '.join(legacy[:8])}")
            if diff:
                for d_ in diff:
                    _append(VIOL, dict(day=day, **d_, note="원장과 토스 수량 불일치 — 사람이 직접 매매했거나 미반영 체결"))
                msg.append("  ⛔ 원장 ≠ 토스 → 이번 실행 중단: " + "; ".join(f"{d_['sym']} 원장 {d_['ledger']} / 토스 {d_['toss']}" for d_ in diff))
                return _done(msg, send, L, save=False)
        except TossError as e:
            msg.append(f"  ⛔ 토스 연결 실패 — {str(e)[:160]}")
            if live:
                return _done(msg, send, L, save=False)
            T = None
    elif live:
        msg.append("  ⛔ 토스 키 없음 — 실전 불가"); return _done(msg, send, L, save=False)
    else:
        msg.append("  · 토스 키 없음 — 원장만으로 모의 계산")

    if T and live:                                               # 지난 실행의 미체결 확인
        for c_id, pd_ in list(L["pending"].items()):
            q, px, fee = _fill(T.order(acct, pd_["orderId"]))
            if q and px:
                apply_fill(L, pd_["o"], q, px, fee, day)
                L["done_ids"].append(c_id); L["pending"].pop(c_id)
                msg.append(f"  ✅ 지난 주문 체결: {pd_['o']['side']} {pd_['o'].get('name')} {q:.0f}주 @ {px:,.0f}")
            elif pd_.get("at") != day:                          # DAY 주문은 그날 끝나면 소멸 — 묶어 두지 않고 다음 판단으로
                L["pending"].pop(c_id)
                msg.append(f"  ⌛ 지난 주문 미체결 소멸: {pd_['o']['side']} {pd_['o'].get('name')} ({pd_['at']}) — 오늘 다시 판단")

    bmap = board()
    buys = [b["sym"] for b in ((plan.get("sleeves") or {}).get(M) or {}).get("buys", [])]
    closes = last_closes(sorted(set(L[M]["positions"]) | set(buys)))
    orders, notes, eq = decide(L, plan, closes, bmap)
    if phase == "pre":
        for o in orders:
            if o["side"] == "BUY":
                o["lim"] = limit_px(o["px"])
    orders, blocked = guard(orders, L, plan, eq, cash)
    if live:
        mark_peaks(L, closes)
    for n_ in notes + [f"차단: {w}" for w in blocked]:
        msg.append(f"  ※ {n_}")
    if not orders:
        msg.append("  주문 없음")
    for o in orders:
        line = f"  {'🔵 매도' if o['side'] == 'SELL' else '🔴 매수'} {o.get('name') or o['sym']}({o['sym']}) {o['quantity']}주 ≈ {o['quantity'] * o['px']:,.0f}원 — {o['why']}"
        if phase == "pre":
            line += f" · 시가 체결({'지정가 ≤ ' + format(o['lim'], ',') + '원' if 'lim' in o else '시장가'})"
        if T is None:
            msg.append(line + " (모의)"); continue
        try:
            kw = dict(order_type="LIMIT", price=o["lim"]) if "lim" in o else {}
            r = T.place(acct, symbol=o["sym"], side=o["side"], client_order_id=o["cid"], quantity=o["quantity"], **kw)
        except Exception as e:
            msg.append(line + f" ⛔ 실패 {str(e)[:120]}"); continue
        if not live:
            msg.append(line + " (모의 — 보낼 요청 생성만)"); continue
        oid = r.get("orderId")
        L["pending"][o["cid"]] = dict(orderId=oid, o=o, at=day)
        if phase == "pre":                                        # 09:00 시가에 체결 — 09:10 실행이 확인
            msg.append(line + " ⏳ 시가 체결 대기"); continue
        for _ in range(10):                                       # 시장가라 대개 바로 체결
            time.sleep(3)
            q, px, fee = _fill(T.order(acct, oid))
            if q and px:
                apply_fill(L, o, q, px, fee, day)
                L["done_ids"].append(o["cid"]); L["pending"].pop(o["cid"]); line += f" ✅ {q:.0f}주 @ {px:,.0f}"; break
        else:
            line += " ⏳ 미체결 — 다음 실행에서 확인"
        msg.append(line)
    msg.append(f"  슬리브 자산 ≈ {eq['equity_krw']:,}원 · 종목당 목표 {eq['target_krw']:,}원")
    return _done(msg, send, L, save=live)


def _done(msg, send, L, save):
    if save:
        LEDGER.write_text(json.dumps(L, ensure_ascii=False, indent=1), encoding="utf-8")
    text = "\n".join(msg)
    print(text)
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if send and not (tok and chat):
        try:
            import config as C                                   # 노트북: data/.telegram_token
            tok, chat = tok or C.TELEGRAM_TOKEN, chat or C.TELEGRAM_CHAT_ID
        except Exception:
            pass
    if send and tok and chat:
        import telegram_notifier as Tn
        Tn.send_message(tok, chat, text)
    return text


def kr_phase(now=None):
    """'pre' = 평일 08:31~08:58 KST 시가 단일가 접수(09:00 시가 한 가격 체결) · 'reg' = 09:05~15:10 정규장 · None = 그 밖.
    공휴일은 가격 자료·토스가 걸러낸다."""
    now = now or datetime.now(KST)
    if now.weekday() >= 5:
        return None
    hm = (now.hour, now.minute)
    if (8, 31) <= hm <= (8, 58):
        return "pre"
    if (9, 5) <= hm <= (15, 10):
        return "reg"
    return None


def in_kr_session(now=None) -> bool:
    return kr_phase(now) is not None


def tick(px: float) -> int:
    """KRX 호가 단위(코스피·코스닥 공통, 2023-01-25~)."""
    for lim, t in ((2000, 1), (5000, 5), (20000, 10), (50000, 50), (200000, 100), (500000, 500)):
        if px < lim:
            return t
    return 1000


def limit_px(prev_close: float, up: float = PRE_LIMIT) -> int:
    """전날 종가 +up 을 호가 단위로 내림 — 상한가(+30%) 안이라 항상 유효."""
    x = prev_close * (1 + up)
    t = tick(x)
    return int(math.floor(x / t) * t)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(); ap.add_argument("--send", action="store_true"); ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    ph = kr_phase()
    if not a.force and not ph:
        print(f"장 밖 {datetime.now(KST):%Y-%m-%d %H:%M} KST — 건너뜀(노트북은 살아 있음)")
        sys.exit(0)
    run(a.send, phase=ph or "reg")
