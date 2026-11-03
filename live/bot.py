# -*- coding: utf-8 -*-
"""실전 시범 주문 봇 — 사람 손 없이 live/plan_latest.json + 원장 규칙대로 토스에 주문 (2026-11-03)

  python live/bot.py              모의: 낼 주문만 계산해 보고(원장·계좌 변화 0)
  python live/bot.py --send       + 텔레그램 보고
실전 주문은 live/switch.json 의 "live": true **그리고** 환경변수 LIVE_TRADING=ON 둘 다일 때만 나간다.

왜 노트북(또는 고정 IP 서버)에서만 도는가: 토스 Open API 는 허용 IP 에서만 응답한다(broker_toss.py 주석).

하루 한 번, 미국장 개장 +30분(바르샤바 16:00, 서머타임 해제 기준)에 돈다:
  ① 대조   토스 보유 ↔ 원장. 원장 종목 수량이 1주라도 다르면 = 규칙 밖 거래 → 기록(live/violations.jsonl)·경보·이번 실행 중단
  ② 손절   전날 종가 ≤ 손절선(최고 종가 −20%, 올라가기만) → 전량 시장가 매도
  ③ 불타기 전날 종가 ≥ 첫 매수가 +10% · S&P500 200일선 위 · 아직 안 했으면 → 목표 비중의 40% 추가
  ④ 신규   이번 주 계획표의 매수(계획 작성 7일 이내, 아직 원장에 없는 종목) → 금액 기준 시장가
  같은 주문은 clientOrderId(계획일·종목·행동)로 두 번 나가지 않는다. 한국 슬리브는 자금 0이라 이번 버전은 미국만.
"""
import argparse, json, os, sys, time
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
LIVE = ROOT / "live"
LEDGER, PLAN, SWITCH = LIVE / "ledger.json", LIVE / "plan_latest.json", LIVE / "switch.json"
TRADES, VIOL = LIVE / "trades.jsonl", LIVE / "violations.jsonl"
STOP, ADD_AT, ADD, CAP = 0.20, 0.10, 0.40, 0.35          # PREREG: 손절 −20% · +10% 불타기 40% · 1회 주문 상한 = 슬리브 35%
TOL = 1e-4                                              # 소수점 수량 대조 허용 오차


def _load(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def _append(p, row):
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def is_live():
    sw = _load(SWITCH, {}).get("live") is True
    return sw and os.environ.get("LIVE_TRADING", "").upper() == "ON"


def blocked():
    return set(_load(ROOT / "executor" / "config.json", {}).get("safety", {}).get("blocked_symbols", []))


# ── 시세 ───────────────────────────────────────────────────────────────
def last_closes(syms):
    """확정된 마지막 일봉 종가(오늘 진행 중 봉 제외). 못 받으면 그 종목은 빠진다 — 있는 척하지 않는다."""
    out = {}
    if not syms:
        return out
    import yfinance as yf
    today = datetime.utcnow().date()
    for s in syms:
        try:
            h = yf.Ticker(s).history(period="1mo", auto_adjust=False)["Close"].dropna()
            h = h[[d.date() < today for d in h.index]]
            if len(h):
                out[s] = (float(h.iloc[-1]), str(h.index[-1])[:10])
        except Exception:
            pass
    return out


# ── 판단 (순수 함수 · 테스트 대상) ─────────────────────────────────────
def reconcile(ledger_pos, toss_hold):
    """원장 종목만 비교한다. 원장에 없는 토스 종목(시스템 밖 기존 보유)은 '레거시'로 보고만."""
    t = {h["sym"]: h["qty"] for h in toss_hold if (h.get("market") or "US") == "US"}
    diff = []
    for sym, p in ledger_pos.items():
        if abs(t.get(sym, 0.0) - p["shares"]) > TOL:
            diff.append(dict(sym=sym, ledger=p["shares"], toss=t.get(sym, 0.0)))
    legacy = sorted(s for s in t if s not in ledger_pos)
    return diff, legacy


def decide(L, plan, closes, today=None):
    """원장·계획표·전날 종가 → 주문 목록. 원장은 바꾸지 않는다."""
    today = today or date.today()
    S, P = L["US"], (plan.get("sleeves") or {}).get("US") or {}
    fx = float(plan.get("usdkrw") or 1350)
    ix_ok = bool(((plan.get("index") or {}).get("US") or {}).get("ok", False))
    done = set(L.get("done_ids", []))
    pend = set(L.get("pending", {}))
    equity = S["cash_krw"] + sum(p["shares"] * closes.get(s, (p["last_px"],))[0] * fx for s, p in S["positions"].items())
    target = equity / 5
    orders, notes = [], []

    for sym, p in S["positions"].items():
        if sym not in closes:
            notes.append(f"{sym} 종가 못 받음 — 손절·불타기 판정 보류"); continue
        c, d = closes[sym]
        peak = max(p.get("peak", p["avg"]), c)
        stop = max(p.get("stop", p["avg"] * (1 - STOP)), peak * (1 - STOP))
        if c <= stop:
            orders.append(dict(sym=sym, side="SELL", quantity=p["shares"], why=f"손절: {d} 종가 {c:.2f} ≤ 손절선 {stop:.2f}",
                               cid=f"{d}-{sym}-STOP"))
        elif not p.get("added") and c >= p["first_px"] * (1 + ADD_AT):
            if ix_ok:
                orders.append(dict(sym=sym, side="BUY", amount_usd=round(target * ADD / fx, 2),
                                   why=f"불타기: 종가 {c:.2f} ≥ 첫 매수가 +10% {p['first_px'] * (1 + ADD_AT):.2f}", cid=f"{sym}-{p['opened']}-ADD"))
            else:
                notes.append(f"{sym} 불타기 조건 충족 — S&P500 200일선 아래라 보류")

    made = plan.get("made")
    fresh = made and (today - date.fromisoformat(made)) <= timedelta(days=7)
    if not fresh:
        notes.append(f"계획표 {made} — 7일 지나 신규 매수 없음(토요일 새 계획 대기)")
    elif not ix_ok:
        notes.append("S&P500 200일선 아래 — 신규 매수 중지")
    else:
        for b in P.get("buys") or []:
            if b["sym"] in S["positions"]:
                continue
            orders.append(dict(sym=b["sym"], side="BUY", amount_usd=round(b["krw"] / fx, 2), name=b.get("name"),
                               why=f"신규: {b.get('why', '')} RS{b.get('rs')}", cid=f"{made}-{b['sym']}-BUY"))

    out = []
    for o in orders:
        if o["cid"] in done or o["cid"] in pend:
            continue                                             # 이중 주문 방지
        out.append(o)
    return out, notes, dict(equity_krw=round(equity), target_krw=round(target), fx=fx)


def guard(orders, L, plan, eq, cash_usd=None):
    """코드가 강제하는 안전장치. 걸린 주문은 빼고 이유를 남긴다."""
    ok, why = [], []
    allow = {b["sym"] for b in ((plan.get("sleeves") or {}).get("US") or {}).get("buys", [])} | set(L["US"]["positions"])
    cap_usd = eq["equity_krw"] * CAP / eq["fx"]
    left = cash_usd if cash_usd is not None else L["US"]["cash_krw"] / eq["fx"]
    for o in orders:
        if o["sym"] in blocked():
            why.append(f"{o['sym']} 레버리지·인버스 차단 목록"); continue
        if o["sym"] not in allow:
            why.append(f"{o['sym']} 계획표·원장에 없는 종목"); continue
        if o["side"] == "BUY":
            if o["amount_usd"] > cap_usd:
                why.append(f"{o['sym']} 1회 주문 ${o['amount_usd']:.2f} > 상한 ${cap_usd:.2f}"); continue
            if o["amount_usd"] < 1:
                why.append(f"{o['sym']} 주문액 $1 미만"); continue
            if o["amount_usd"] > left + 0.01:
                why.append(f"{o['sym']} 현금 부족(${left:.2f})"); continue
            left -= o["amount_usd"]
        ok.append(o)
    sells = [o for o in ok if o["side"] == "SELL"]
    return sells + [o for o in ok if o["side"] == "BUY"], why     # 매도 먼저


# ── 체결 반영 ──────────────────────────────────────────────────────────
def _fill(res):
    """주문 상세 응답에서 체결 수량·평균가. 필드 이름이 문서마다 달라 넓게 읽는다."""
    def n(*ks):
        for k in ks:
            v = res.get(k)
            try:
                if v not in (None, ""):
                    return float(v)
            except (TypeError, ValueError):
                pass
        return None
    q = n("filledQuantity", "executedQuantity", "executionQuantity")
    px = n("averageFilledPrice", "averageExecutedPrice", "executionPrice", "avgPrice")
    fee = n("commission", "fee") or 0.0
    st = str(res.get("status") or res.get("orderStatus") or "").upper()
    return q, px, fee, st


def apply_fill(L, o, q, px, fee, fx, day):
    S = L["US"]; P = S["positions"]
    if o["side"] == "BUY":
        p = P.get(o["sym"])
        if p:                                                    # 불타기
            tot = p["shares"] + q
            p.update(avg=(p["avg"] * p["shares"] + px * q) / tot, shares=tot, added=True)
        else:
            P[o["sym"]] = dict(name=o.get("name") or o["sym"], shares=q, avg=px, first_px=px, peak=px, stop=px * (1 - STOP),
                               added=False, last_px=px, opened=day)
        S["cash_krw"] -= (q * px + fee) * fx
    else:
        p = P.pop(o["sym"])
        S["cash_krw"] += (q * px - fee) * fx
        L.setdefault("cooldown", {})[o["sym"]] = day          # PREREG 재진입 2주 냉각
    _append(TRADES, dict(day=day, sym=o["sym"], side=o["side"], qty=q, px=px, fee=fee, fx=fx, why=o["why"], cid=o["cid"]))


def mark_peaks(L, closes):
    for s, p in L["US"]["positions"].items():
        if s in closes:
            c = closes[s][0]
            p["last_px"] = c
            p["peak"] = max(p.get("peak", c), c)
            p["stop"] = max(p.get("stop", p["avg"] * (1 - STOP)), p["peak"] * (1 - STOP))


# ── 실행 ───────────────────────────────────────────────────────────────
def _keys():
    D = ROOT / "data"
    rd = lambda env, f: os.environ.get(env, "").strip() or ((D / f).read_text(encoding="utf-8").strip() if (D / f).exists() else "")
    return rd("TOSS_CLIENT_ID", ".toss_client_id"), rd("TOSS_CLIENT_SECRET", ".toss_client_secret")


def run(send=False):
    live = is_live()
    L = _load(LEDGER, None); plan = _load(PLAN, {})
    L.setdefault("done_ids", []); L.setdefault("pending", {})
    day = str(date.today())
    head = ("🔴 실전" if live else "🧪 모의") + f" 주문 봇 {day}"
    msg = [head]
    cid, sec = _keys()
    T = acct = None; cash_usd = None
    if cid and sec:
        from executor.broker_toss import TossTrader, TossError
        try:
            T = TossTrader(cid, sec, live=live)
            accts = T.accounts()
            acct = (accts[0] or {}).get("accountSeq") if accts else None
            hold = T.holdings(acct)
            diff, legacy = reconcile(L["US"]["positions"], hold)
            cash_usd = T.cash(acct).get("USD")
            if legacy:
                msg.append(f"  · 시스템 밖 보유(건드리지 않음): {', '.join(legacy[:8])}")
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

    # 지난 실행의 미체결 확인
    if T and live:
        for c_id, pd_ in list(L["pending"].items()):
            q, px, fee, st = _fill(T.order(acct, pd_["orderId"]))
            if q and px:
                apply_fill(L, pd_["o"], q, px, fee, float(plan.get("usdkrw") or 1350), day)
                L["done_ids"].append(c_id); L["pending"].pop(c_id)
                msg.append(f"  ✅ 지난 주문 체결: {pd_['o']['side']} {pd_['o']['sym']} {q} @ {px}")

    syms = list(L["US"]["positions"])
    closes = last_closes(syms)
    orders, notes, eq = decide(L, plan, closes)
    orders, blocked_why = guard(orders, L, plan, eq, cash_usd)
    if live:
        mark_peaks(L, closes)
    for n_ in notes + [f"차단: {w}" for w in blocked_why]:
        msg.append(f"  ※ {n_}")
    if not orders:
        msg.append("  주문 없음")
    for o in orders:
        amt = f"{o['quantity']}주" if "quantity" in o else f"${o['amount_usd']:.2f}"
        line = f"  {'🔵 매도' if o['side'] == 'SELL' else '🔴 매수'} {o['sym']} {amt} — {o['why']}"
        if T is None:
            msg.append(line + " (모의)"); continue
        kw = dict(symbol=o["sym"], side=o["side"], client_order_id=o["cid"])
        kw.update(quantity=o["quantity"]) if "quantity" in o else kw.update(amount_usd=o["amount_usd"])
        try:
            r = T.place(acct, **kw)
        except Exception as e:
            msg.append(line + f" ⛔ 실패 {str(e)[:120]}"); continue
        if not live:
            msg.append(line + " (모의 — 보낼 요청 생성만)"); continue
        oid = r.get("orderId")
        L["pending"][o["cid"]] = dict(orderId=oid, o=o, at=day)
        for _ in range(10):                                       # 시장가라 대개 바로 체결
            time.sleep(3)
            q, px, fee, st = _fill(T.order(acct, oid))
            if q and px:
                apply_fill(L, o, q, px, fee, eq["fx"], day)
                L["done_ids"].append(o["cid"]); L["pending"].pop(o["cid"]); line += f" ✅ {q} @ {px}"; break
        else:
            line += " ⏳ 미체결 — 다음 실행에서 확인"
        msg.append(line)
    msg.append(f"  슬리브 자산 ≈ {eq['equity_krw']:,}원 · 종목당 목표 {eq['target_krw']:,}원 · 환율 {eq['fx']:,.0f}")
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


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(); ap.add_argument("--send", action="store_true")
    run(ap.parse_args().send)
