# -*- coding: utf-8 -*-
"""
주도주 포워드 페이퍼 트레이딩 — 두 규칙을 나란히 실시간 추적 (2026-08-08~)
  규칙⑥ (주력): RS13>1.5 AND (흑자전환 OR 이익폭증) AND OPM>0
  규칙⑤ (대조): RS13>1.5 AND (흑자전환 OR 이익폭증) AND PSR<3   ← 08-04 기록분 유지
  청산: 고점 대비 −20% 트레일링  ← 고정 기간이 아니므로 매 갱신마다 고점을 추적한다
  목적: 백테스트가 실전에서 재현되는지, 그리고 두 규칙 중 어느 쪽이 나은지 실측 대조

  ※ PSR은 2026-08-08부터 의사결정에서 빠지고 표시용 참고지표로만 남는다.

CLI
  python leaders_paper.py log      # 이번 주 신호를 가상진입 기록 (주 1회)
  python leaders_paper.py update   # 시세 갱신 → 고점·트레일링 청산 판정
  python leaders_paper.py report   # 실전 vs 백테스트 대조
"""
import json, os, sys
from datetime import date, datetime
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(BASE, "results", "leaders_paper.json")
TRAIL = 0.20            # 고점 대비 −20% 트레일링
MAXPOS = 8              # 규칙별 동시 보유 상한
COST = 0.25 / 100       # 왕복 비용 근사

# 규칙별 진입 조건 — base(유동성·시총 통과분)를 받아 마스크를 돌려준다
RULES = {
    "R6": ("⑥ RS13>1.5 & (흑자전환 OR 이익폭증) & OPM>0",
           lambda b: (b.rs_13w > 1.5) & (b.opm > 0) & ((b.op_turn == 1) | (b.b_any == 1))),
    "R5": ("⑤ RS13>1.5 & (흑자전환 OR 이익폭증) & PSR<3",
           lambda b: (b.rs_13w > 1.5) & (b.psr < 3) & ((b.op_turn == 1) | (b.b_any == 1))),
}

# 백테스트 기대값 (2018-06~2026-08 · trail-20 · 8종목 12.5%)
REF_BY_RULE = {
    "R6": dict(avg_ret=None, med_ret=-5.9, winrate=43.4, hold_wk=20.7,
               cagr=32.8, mdd=-37.7, recov=0.87),
    "R5": dict(avg_ret=23.1, med_ret=-6.9, winrate=38.3, hold_wk=21.3,
               payoff=5.5, cagr=27.7, mdd=-23.9, recov=1.16),
}
REF = REF_BY_RULE["R5"]     # 기존 원장 호환


def _fdr():
    import FinanceDataReader as fdr
    return fdr


def price_now(sym):
    try:
        d = _fdr().DataReader(sym, (date.today() - pd.Timedelta(days=15)).isoformat())
        c = d["Close"].dropna()          # 당일 미체결 바는 Close=NaN
        if len(c) == 0:
            return None, None
        return float(c.iloc[-1]), str(c.index[-1].date())
    except Exception:
        return None, None


def price_series(sym, start):
    try:
        return _fdr().DataReader(sym, start)["Close"].dropna()
    except Exception:
        return None


def load():
    if os.path.exists(LEDGER):
        return json.load(open(LEDGER, encoding="utf-8"))
    return dict(created=str(date.today()), rule=RULES["R6"][0],
                rules={k: v[0] for k, v in RULES.items()},
                exit="고점 대비 -20% 트레일링", ref=REF, ref_by_rule=REF_BY_RULE, trades=[])


def save(d):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    json.dump(d, open(LEDGER, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


# ────────────────────────── log ──────────────────────────
def cmd_log():
    import leaders_boost as B
    d = B.build()
    d["as_of"] = pd.to_datetime(d.as_of)
    wk = d.as_of.max()
    w = d[d.as_of == wk]
    base = w[(w.close >= 5) & (w.adv_20d >= 5e6) & (w.marcap >= 2e9)]

    led = load()
    led.setdefault("rules", {k: v[0] for k, v in RULES.items()})
    led.setdefault("ref_by_rule", REF_BY_RULE)

    # ── 사이클 실행 이력 ──────────────────────────────────────────────
    # M6a 완료조건이 "13주 연속 실행"이라 실행 자체를 세야 한다.
    # 신규 진입이 없는 주(슬롯 만석)에는 trades가 안 늘어나므로
    # trades에서 역산하면 그 주를 통째로 놓친다. 그래서 따로 기록한다.
    runs = led.setdefault("runs", [])
    sw = str(wk.date())
    if not any(r["signal_week"] == sw for r in runs):
        runs.append(dict(signal_week=sw, ran_on=str(date.today())))
        runs.sort(key=lambda r: r["signal_week"])
    px_cache, total = {}, 0

    # 규칙별로 독립된 보유 상한을 둔다 — 두 규칙의 성적을 섞지 않기 위해서.
    # 08-04 이전 기록은 rule 필드가 없으므로 규칙⑤로 간주한다.
    for rk, (rlabel, cond) in RULES.items():
        sel = base[cond(base)].sort_values("rs_13w", ascending=False)
        held = {t["sym"] for t in led["trades"]
                if t["status"] == "open" and t.get("rule", "R5") == rk}
        room = MAXPOS - len(held)
        print(f"[{rk}] {rlabel}")
        print(f"     기준 주차 {wk.date()} · 조건 충족 {len(sel)}종 · 보유 {len(held)}종 · 여유 {room}")
        if room <= 0:
            print("     보유 상한 도달 — 신규 진입 없음"); continue

        added = 0
        for _, r in sel.iterrows():
            if added >= room:
                break
            if r.sym in held:
                continue
            if r.sym not in px_cache:                 # 두 규칙이 겹칠 때 시세 재조회 방지
                px_cache[r.sym] = price_now(r.sym)
            px, pdate = px_cache[r.sym]
            if px is None:
                print(f"     SKIP {r.sym} 시세 조회 실패"); continue
            trig = ([" 흑자전환"] if r.op_turn == 1 else []) + \
                   [k for k in ("b_ophigh", "b_nihigh", "b_opjump", "b_opmjump") if r[k] == 1]
            led["trades"].append(dict(
                id=f"{rk}_{r.sym}_{date.today()}", rule=rk, sym=r.sym, market="US",
                signal_week=str(wk.date()), log_date=str(date.today()),
                entry_px=round(px, 4), entry_px_date=pdate,
                peak_px=round(px, 4), peak_date=pdate,
                rs_13w=round(float(r.rs_13w), 2),
                psr=round(float(r.psr), 2) if r.psr == r.psr else None,   # 참고지표
                opm=round(float(r.opm), 2) if r.opm == r.opm else None,
                dist_52w=round(float(r.dist_52w), 1),
                triggers=[t.strip() for t in trig],
                status="open", exit_px=None, exit_date=None, ret_pct=None, hold_wk=None,
                marks={}))
            added += 1
            total += 1
            print(f"     LOG  {r.sym:6s} ${px:>9,.2f}  RS {r.rs_13w:.2f}  "
                  f"OPM {r.opm:6.2f}  PSR {r.psr:6.2f}  {' '.join(trig)}")
    led["updated"] = str(date.today())
    save(led)
    print(f"\n기록 {total}건 → {LEDGER}")


# ───────────────────────── update ─────────────────────────
def cmd_update():
    led = load()
    ops = [t for t in led["trades"] if t["status"] == "open"]
    if not ops:
        print("열린 포지션 없음"); return
    print(f"열린 포지션 {len(ops)}건 갱신")
    for t in ops:
        s = price_series(t["sym"], t["entry_px_date"])
        if s is None or len(s) == 0:
            print(f"  SKIP {t['sym']} 시세 실패"); continue

        # ── 청산 판정은 '주봉 종가' 기준 ─────────────────────────────────
        # 2026-08-10 수정. 이전에는 일봉 종가로 판정했는데 백테스트
        # (leaders_boost.run)는 주봉 종가로 청산한다. 일봉 고점은 주봉 고점보다
        # 항상 크거나 같고 판정 횟수도 5배라, 페이퍼가 구조적으로 더 빨리·더 자주
        # 털린다. 그 상태로는 M6b(백테스트 대조)가 전략을 재는 게 아니라
        # 자의 차이를 재게 된다. leaders_build.py 와 동일한 주봉 규칙을 쓴다.
        w = s.resample("W-MON", label="left", closed="left").last().dropna()
        if len(w) and (pd.Timestamp(s.index[-1]) - pd.Timestamp(w.index[-1])).days < 4:
            w = w.iloc[:-1]          # 미완성 주(금요일 봉 없음) 제거
        if len(w) == 0:
            print(f"  WAIT {t['sym']:6s} 완성된 주봉 없음 (진입 당주)"); continue

        peak = float(w.max()); last = float(w.iloc[-1])
        t["peak_px"] = round(peak, 4)
        t["peak_date"] = str(w.idxmax().date())
        t["last_px"] = round(last, 4)          # 알림에서 청산선까지 거리를 보여주려면 필요
        t["last_date"] = str(w.index[-1].date())
        # 주봉 라벨은 그 주 '월요일'이고 진입은 그 주 '금요일 종가'라 그대로 빼면 음수가 된다.
        # 진입 주의 월요일을 기준으로 잡아 완성된 주봉 수를 센다 (진입 당주 = 0주).
        ed = pd.Timestamp(t["entry_px_date"]).normalize()
        ew = ed - pd.Timedelta(days=ed.weekday())
        hold = max(0.0, (pd.Timestamp(w.index[-1]) - ew).days / 7)

        # 고정 지평 마크 (백테스트 대조용)
        for lab, wks in (("4w", 4), ("13w", 13), ("26w", 26)):
            if hold >= wks and lab not in t["marks"]:
                cut = pd.Timestamp(t["entry_px_date"]) + pd.Timedelta(weeks=wks)
                sub = w[w.index <= cut]
                if len(sub):
                    t["marks"][lab] = round((float(sub.iloc[-1]) / t["entry_px"] - 1) * 100, 2)

        # 참고 기록: 일봉이 먼저 -20%를 뚫었는지. 청산 판정에는 쓰지 않는다.
        # 실계좌(M7)로 갈 때 "일봉으로 봤으면 언제 털렸나"를 비교하기 위한 자료.
        dpeak = s.cummax()
        dhit = s[(s <= dpeak * (1 - TRAIL)) & (s.index > pd.Timestamp(t["entry_px_date"]))]
        if len(dhit) and not t.get("daily_breach"):
            t["daily_breach"] = dict(date=str(dhit.index[0].date()),
                                     px=round(float(dhit.iloc[0]), 4))

        hit = w[(w <= peak * (1 - TRAIL)) & (w.index > pd.Timestamp(t["entry_px_date"]))]
        if len(hit):
            xp = float(hit.iloc[0]); xd = str(hit.index[0].date())
            t.update(status="closed", exit_px=round(xp, 4), exit_date=xd,
                     ret_pct=round(((xp / t["entry_px"]) * (1 - COST) - 1) * 100, 2),
                     hold_wk=round((pd.Timestamp(xd) - pd.Timestamp(t["entry_px_date"])).days / 7, 1))
            db = t.get("daily_breach")
            print(f"  EXIT {t['sym']:6s} {t['ret_pct']:+7.1f}%  {t['hold_wk']:.0f}주  "
                  f"(주봉고점 ${peak:,.2f} → −20%)"
                  + (f"  [일봉은 {db['date']}에 먼저 뚫음]" if db else ""))
        else:
            cur = ((last / t["entry_px"]) - 1) * 100
            dd = (last / peak - 1) * 100
            print(f"  HOLD {t['sym']:6s} {cur:+7.1f}%  고점대비 {dd:+6.1f}%  {hold:.0f}주")
    led["updated"] = str(date.today())
    save(led)


# ───────────────────────── report ─────────────────────────
def cmd_report():
    led = load()
    T = pd.DataFrame(led["trades"])
    if T.empty:
        print("기록 없음 — 먼저 `python leaders_paper.py log`"); return
    if "rule" not in T.columns:
        T["rule"] = "R5"                      # 08-04 이전 기록은 규칙⑤
    T["rule"] = T["rule"].fillna("R5")
    print("=" * 96)
    print(f"주도주 페이퍼 트레이딩 — 시작 {led['created']} · 갱신 {led.get('updated','-')}")
    print(f"청산 {led['exit']}   |   총 {len(T)}건")
    print("=" * 96)

    refs = led.get("ref_by_rule", REF_BY_RULE)
    for rk in [k for k in RULES if (T.rule == k).any()]:
        sub = T[T.rule == rk]
        cl, op = sub[sub.status == "closed"], sub[sub.status == "open"]
        ref = refs.get(rk, {})
        print(f"\n[{rk}] {RULES[rk][0]}")
        print(f"     {len(sub)}건 (청산 {len(cl)} · 보유 {len(op)})")
        if len(op):
            cols = [c for c in ["sym", "log_date", "entry_px", "peak_px",
                                "rs_13w", "opm", "psr", "triggers"] if c in op.columns]
            print(op[cols].to_string(index=False))
        if len(cl) == 0:
            print(f"     청산 0건 — 대조 불가. 백테스트 기대: 중앙 {ref.get('med_ret'):+.1f}% · "
                  f"승률 {ref.get('winrate'):.0f}% · 보유 {ref.get('hold_wk'):.0f}주")
            continue
        live = dict(med_ret=cl.ret_pct.median(), winrate=(cl.ret_pct > 0).mean() * 100,
                    hold_wk=cl.hold_wk.mean())
        print(f"     {'지표':10s}{'실전':>10s}{'백테스트':>12s}{'괴리':>10s}")
        for k, lab, unit in [("med_ret", "중앙 수익", "%"), ("winrate", "승률", "%"),
                             ("hold_wk", "평균 보유", "주")]:
            lv, rf = live[k], ref.get(k)
            if rf is None or lv != lv:
                continue
            print(f"     {lab:10s}{lv:>9.1f}{unit}{rf:>11.1f}{unit}{lv-rf:>+9.1f}")
        print(f"     ⚠️ 청산 {len(cl)}건 — "
              f"{'표본 부족, 판단 불가' if len(cl) < 20 else '참고 가능'}")

    # 2026-08-08 측정: 13주 추적으로는 청산이 3~4건에 그치고, 롤링 13주 성과의
    # p10~p90 폭이 200%p를 넘는다. 짧은 기간으로 성과를 판정하려 하지 말 것.
    print("\n" + "-" * 96)
    print("  ⚠️ 성과 판정에는 청산 20건 이상이 필요하다 — 주 1회 실행 기준 약 1.5년.")
    print("  ⚠️ 13주로 확인할 수 있는 건 성과가 아니라 '규칙대로 굴렸는가'(M6a)뿐이다.")
    print("  ⚠️ 백테스트는 생존편향·인샘플 선택이 있어 낙관적. 실전이 낮게 나오는 게 정상이다.")


# ───────────────────────── notify ─────────────────────────
def _tg(text):
    """config.py의 텔레그램 설정 재사용. 미설정이면 콘솔 출력."""
    try:
        import config
        if not config.TELEGRAM_ENABLED:
            raise RuntimeError("disabled")
        import requests
        r = requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10)
        if r.status_code != 200:
            print(f"[텔레그램 실패 {r.status_code}] {r.text[:200]}")
            return False
        return True
    except Exception as e:
        print(f"[텔레그램 미발송: {e}]\n{text}")
        return False


def cmd_notify():
    """토요일 주간 요약 — 금요일 종가 확정 기준."""
    led = load()
    T = pd.DataFrame(led["trades"])
    if T.empty:
        _tg("주도주 주간: 기록 없음"); return
    if "rule" not in T.columns:
        T["rule"] = "R5"
    T["rule"] = T["rule"].fillna("R5")
    today = str(date.today())

    # ── 주차 / M6a 연속성 ────────────────────────────────────────────
    runs = led.get("runs", [])
    nrun = len(runs)
    sw = runs[-1]["signal_week"] if runs else "-"
    # 신호주가 7일 간격으로 이어지는지 — 건너뛴 주가 있으면 M6a 카운트는 끊긴다
    streak, gaps = (1 if runs else 0), 0
    for a, b in zip(runs, runs[1:]):
        d = (pd.Timestamp(b["signal_week"]) - pd.Timestamp(a["signal_week"])).days
        if d == 7:
            streak += 1
        else:
            streak, gaps = 1, gaps + 1
    head = f"<b>🚀 주도주 {nrun}주차</b>  (신호주 {sw})"
    m6a = f"M6a 규율 {streak}/13주" + (f" · 🔴 중간에 {gaps}주 걸름" if gaps else " ✅ 연속")

    L = [head, f"{today} · 청산 규칙: 주봉 고점 −{int(TRAIL*100)}% 트레일링",
         m6a, ""]

    # 이번 실행에서 새로 청산·진입된 것부터 (사람이 제일 먼저 볼 것)
    new_x = T[(T.status == "closed") & (T.exit_date.astype(str) >= today)]
    new_e = T[(T.status == "open") & (T.log_date == today)]
    if len(new_x):
        L.append("<b>❌ 청산</b>")
        for _, t in new_x.iterrows():
            L.append(f"  {t['sym']} {t['ret_pct']:+.1f}% · {t['hold_wk']:.0f}주 [{t['rule']}]")
        L.append("")
    if len(new_e):
        L.append("<b>✅ 신규 진입 (금요일 종가)</b>")
        for _, t in new_e.iterrows():
            trg = " ".join(t["triggers"])[:38]
            L.append(f"  {t['sym']} ${t['entry_px']:,.2f} RS{t['rs_13w']:.2f} [{t['rule']}] {trg}")
        L.append("")
    if not len(new_x) and not len(new_e):
        L.append("<i>이번 주 청산·진입 없음</i>\n")

    for rk in [k for k in RULES if (T.rule == k).any()]:
        sub = T[T.rule == rk]
        op, cl = sub[sub.status == "open"], sub[sub.status == "closed"]
        L.append(f"<b>[{rk}]</b> 보유 {len(op)} · 청산 {len(cl)}")
        rows = []
        for _, t in op.iterrows():
            pk, last = t["peak_px"], t.get("last_px") or t["peak_px"]
            stop = pk * (1 - TRAIL)
            room = (stop / last - 1) * 100          # 현재가에서 청산선까지 남은 %
            pnl = (last / t["entry_px"] - 1) * 100
            rows.append((room, t["sym"], last, stop, room, pnl))
        # room이 0에 가까울수록 청산선에 붙은 것 → 급한 순으로 위에 놓는다
        for room, sym, last, stop, _r, pnl in sorted(rows, reverse=True):
            flag = " ⚠️" if room > -5 else ""
            L.append(f"  {sym:<5} ${last:,.2f} ({pnl:+.1f}%) · 청산선 ${stop:,.2f} "
                     f"[{room:+.1f}%]{flag}")
        if len(cl):
            L.append(f"  실적: 승률 {(cl.ret_pct>0).mean()*100:.0f}% · "
                     f"중앙 {cl.ret_pct.median():+.1f}%")
        L.append("")

    # 차기 후보 (이번 주 신호에서 슬롯 밖으로 밀린 종목)
    try:
        sig = json.load(open(os.path.join(BASE, "results", "leaders_signal.json"),
                             encoding="utf-8"))
        held = set(T[T.status == "open"].sym)
        wait = [c for c in sig.get("candidates", []) if c["sym"] not in held][:6]
        if wait:
            L.append(f"<b>📋 대기 후보</b> (신호주 {sig.get('signal_week','')})")
            for c in wait:
                L.append(f"  {c['sym']:<5} ${c['close']:,.2f} RS{c['rs_13w']:.2f} "
                         f"OPM {c.get('opm')}")
            L.append("")
    except Exception:
        pass

    n_cl = int((T.status == "closed").sum())
    L.append(f"<i>M6b 성과표본 청산 {n_cl}/20건</i>")
    _tg("\n".join(L))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    {"log": cmd_log, "update": cmd_update, "report": cmd_report,
     "notify": cmd_notify}.get(cmd, cmd_report)()
