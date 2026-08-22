# -*- coding: utf-8 -*-
"""
주도주 포워드 페이퍼 트레이딩 (2026-08-04~) — 2026-08-16 운용 규칙 전면 반영

  진입   A  이익폭증 & 0<PER<20 & RS13>1.5      · 매주 스크리닝
         R6 RS13>1.5 & OPM>0 & (흑자전환 OR 이익폭증) & 시총2B · 월 1회 스크리닝
  비중   종목당 상한 20% · 균등 4분할(5%씩) · 최대 12종
  불타기 A  = 눌림목형  (고점 −5~10% AND 직전매수가 초과 AND 20주선 위)
         R6 = 신고가형  (주봉 종가가 52주 신고가)
         ※ 자금 경합 시 불타기 우선 — 백테에서 신규우선·비례배분보다 우월
  축소   보유 종목이 3주간 52주 신고가 미갱신 → 그 종목 30% 축소 (1회, 재진입 없음)
  트림   평가 비중 40% 초과 → 월말에 30%로
  청산   주봉 고점 대비 −20% 트레일링, 전 물량 공통

왜 이 조합인가 (2026-08-16 백테 · 2019-01~2026-08 · 생존편향 미보정)
  · 대조군 100시드 대비 A 96~100%ile, R6 94~99%ile — 필터가 무작위보다 낫다
  · A는 승률형(49.1%)이라 눌림목(평단 관리), R6는 손익비형(43.0%)이라 신고가(추세 확증)
  · 지수(SPY) 기준 현금 규칙은 수익을 19~28% 깎고 낙폭은 그대로여서 제외.
    트레일 −20%와 종목별 30% 축소가 이미 같은 일을 두 겹으로 하고 있다.
  · 전량 매도(3주 미갱신 시)는 발동 369회로 재앙 — 30% 축소가 정확히 봉우리

R5·R6T·B는 신규 진입을 중단한다(기존 보유는 트레일까지 유지). 규칙을 늘리면
표본만 쪼개지고 판정이 늦어진다.

CLI
  python leaders_paper.py log      # 이번 주 신호를 가상진입 기록 (주 1회)
  python leaders_paper.py update   # 시세 갱신 → 불타기·축소·트레일링 청산 판정
  python leaders_paper.py report   # 실전 vs 백테스트 대조
  python leaders_paper.py notify   # 텔레그램 주간 요약
"""
import json, os, sys
from datetime import date
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(BASE, "results", "leaders_paper.json")

TRAIL = 0.20               # 주봉 고점 대비 −20% 트레일링 (전 물량 공통)
CAP_WT = 20.0              # 종목당 매입 상한 (포트 %)
NTR = 4                    # 균등 분할 수
TRANCHE = CAP_WT / NTR     # 분할당 5%
QUIET_WK = 3               # 52주 신고가 미갱신 판정 주수
CUT_FRAC = 0.30            # 미갱신 시 축소 비율
TRIM_HI, TRIM_TO = 40.0, 30.0
COST = 0.25 / 100          # 왕복 비용 근사
POLICY = (f"종목당 상한 {CAP_WT:.0f}% · 균등 {NTR}분할({TRANCHE:.0f}%씩) · 불타기 우선 · "
          f"{QUIET_WK}주 신고가 미갱신 시 {CUT_FRAC*100:.0f}% 축소 · 평가 {TRIM_HI:.0f}%초과 시 {TRIM_TO:.0f}%로 트림")

SLOTS = {"A": 12, "R6": 12}                    # 신규 진입 허용 규칙
FROZEN = ("R5", "R6T", "B")                    # 진입 중단, 보유분만 유지
PYRAMID = {"A": "눌림목", "R6": "신고가"}
MONTHLY = ("R6",)                              # 월 1회만 스크리닝하는 규칙

RULES = {
    "A": ("A 이익폭증 & 0<PER<20 & RS13>1.5 · 12종 · 눌림목 불타기",
          lambda b: (b.b_any == 1) & (b.per > 0) & (b.per < 20) & (b.rs_13w > 1.5)),
    "R6": ("R6 RS13>1.5 & OPM>0 & (흑자전환 OR 이익폭증) · 12종 · 신고가 불타기",
           lambda b: (b.rs_13w > 1.5) & (b.opm > 0) & ((b.op_turn == 1) | (b.b_any == 1))),
    "R5": ("⑤ (동결) RS13>1.5 & (흑자전환 OR 이익폭증) & PSR<3",
           lambda b: (b.rs_13w > 1.5) & (b.psr < 3) & ((b.op_turn == 1) | (b.b_any == 1))),
    "R6T": ("⑥ (동결) 10종목판", lambda b: (b.rs_13w > 1.5) & (b.opm > 0) &
            ((b.op_turn == 1) | (b.b_any == 1))),
    "B": ("B (동결) (흑자전환 OR 이익폭증) & RS13>1.7",
          lambda b: ((b.op_turn == 1) | (b.b_any == 1)) & (b.rs_13w > 1.7)),
}

# 백테 기대값 — 2019-01~2026-08 · 12종 · 상한 20% · 균등 4분할 · 불타기 우선 · 종목축소 ON
# (results/alloc.csv. 생존편향·인샘플 선택이 남아 있어 실전은 이보다 낮게 나오는 게 정상)
REF_BY_RULE = {
    "A": dict(mult=8.43, cagr=32.5, mdd=-20.7, recov=1.57, winrate=49.1,
              med_ret=None, hold_wk=None, top3=38.9),
    "R6": dict(mult=12.56, cagr=39.7, mdd=-30.5, recov=1.30, winrate=43.0,
               med_ret=None, hold_wk=None, top3=52.4),
    "R5": dict(winrate=38.3, cagr=27.7, mdd=-23.9, recov=1.16, med_ret=-6.9, hold_wk=21.3),
    "R6T": dict(winrate=39.8, cagr=27.0, mdd=-30.1, recov=0.90),
    "B": dict(winrate=40.5, cagr=43.4, mdd=-51.3, recov=0.85),
}
GATES = {"R5": (5e6, 2e9), "R6": (5e6, 2e9), "R6T": (5e6, 2e9),
         "A": (1e6, 0), "B": (1e6, 0)}
REF = REF_BY_RULE["A"]


def _fdr():
    import FinanceDataReader as fdr
    return fdr


def price_now(sym):
    try:
        d = _fdr().DataReader(sym, (date.today() - pd.Timedelta(days=15)).isoformat())
        c = d["Close"].dropna()
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


def weekly(sym, days=520):
    """완성된 주봉만. 백테(leaders_build)와 같은 W-MON 리샘플을 쓴다.

    52주 신고가·20주선을 보려면 진입 이전 이력까지 필요하므로 넉넉히 받는다.
    """
    s = price_series(sym, (date.today() - pd.Timedelta(days=days)).isoformat())
    if s is None or len(s) == 0:
        return None, None
    w = s.resample("W-MON", label="left", closed="left").last().dropna()
    if len(w) and (pd.Timestamp(s.index[-1]) - pd.Timestamp(w.index[-1])).days < 4:
        w = w.iloc[:-1]                       # 미완성 주 제거
    return (w if len(w) else None), s


def migrate(t):
    """08-16 이전 기록에는 분할·축소 필드가 없다. 1차 5%만 산 것으로 간주한다."""
    t.setdefault("rule", "R5")
    t.setdefault("lots", [dict(px=t["entry_px"], date=t.get("entry_px_date"), wt=TRANCHE)])
    t.setdefault("tr", len(t["lots"]))
    t.setdefault("wt", round(sum(l["wt"] for l in t["lots"]), 2))
    t.setdefault("cut", False)
    t.setdefault("hi_date", None)
    t.setdefault("adds", [])
    return t


def load():
    if os.path.exists(LEDGER):
        d = json.load(open(LEDGER, encoding="utf-8"))
        for t in d.get("trades", []):
            migrate(t)
        return d
    return dict(created=str(date.today()), rule=RULES["A"][0],
                rules={k: v[0] for k, v in RULES.items()},
                exit="주봉 고점 대비 -20% 트레일링", ref=REF,
                ref_by_rule=REF_BY_RULE, trades=[])


def save(d):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    json.dump(d, open(LEDGER, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def avg_px(t):
    tot = sum(l["wt"] for l in t["lots"])
    return sum(l["px"] * l["wt"] for l in t["lots"]) / tot if tot else t["entry_px"]


# ────────────────────────── log ──────────────────────────
def cmd_log():
    import leaders_boost as B
    d = B.build()
    d["as_of"] = pd.to_datetime(d.as_of)
    wk = d.as_of.max()
    w = d[d.as_of == wk]
    w = w[w.close >= 5]

    led = load()
    led["rules"] = {k: v[0] for k, v in RULES.items()}
    led["ref_by_rule"] = REF_BY_RULE
    led["exit"] = "주봉 고점 대비 -20% 트레일링"
    led["policy"] = POLICY

    runs = led.setdefault("runs", [])
    sw = str(wk.date())
    if not any(r["signal_week"] == sw for r in runs):
        runs.append(dict(signal_week=sw, ran_on=str(date.today())))
        runs.sort(key=lambda r: r["signal_week"])

    # R6는 월 1회 스크리닝 — 그 달 마지막 신호주에만 신규 진입한다.
    is_month_end = (wk + pd.Timedelta(days=7)).month != wk.month
    px_cache, total = {}, 0

    for rk in SLOTS:
        rlabel, cond = RULES[rk]
        if rk in MONTHLY and not is_month_end:
            print(f"[{rk}] 월 1회 스크리닝 — 이번 주는 건너뜀 (신호주 {wk.date()})")
            continue
        liq, mc = GATES.get(rk, (5e6, 2e9))
        base = w[(w.adv_20d >= liq) & (w.marcap >= mc)]
        sel = base[cond(base)].sort_values("rs_13w", ascending=False)
        held = {t["sym"] for t in led["trades"]
                if t["status"] == "open" and t.get("rule") == rk}
        room = SLOTS[rk] - len(held)
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
            if r.sym not in px_cache:
                px_cache[r.sym] = price_now(r.sym)
            px, pdate = px_cache[r.sym]
            if px is None:
                print(f"     SKIP {r.sym} 시세 조회 실패"); continue
            trig = (["흑자전환"] if r.op_turn == 1 else []) + \
                   [k for k in ("b_ophigh", "b_nihigh", "b_opjump", "b_opmjump") if r[k] == 1]
            led["trades"].append(dict(
                id=f"{rk}_{r.sym}_{date.today()}", rule=rk, sym=r.sym, market="US",
                signal_week=str(wk.date()), log_date=str(date.today()),
                entry_px=round(px, 4), entry_px_date=pdate,
                peak_px=round(px, 4), peak_date=pdate,
                lots=[dict(px=round(px, 4), date=pdate, wt=TRANCHE)],
                tr=1, wt=TRANCHE, cut=False, hi_date=None, adds=[],
                rs_13w=round(float(r.rs_13w), 2),
                psr=round(float(r.psr), 2) if r.psr == r.psr else None,
                opm=round(float(r.opm), 2) if r.opm == r.opm else None,
                dist_52w=round(float(r.dist_52w), 1),
                triggers=trig, status="open", exit_px=None, exit_date=None,
                ret_pct=None, hold_wk=None, marks={}))
            added += 1; total += 1
            print(f"     LOG  {r.sym:6s} ${px:>9,.2f}  {TRANCHE:.0f}%  RS {r.rs_13w:.2f}  "
                  f"{' '.join(trig)}")

    for rk in FROZEN:
        n = sum(1 for t in led["trades"] if t["status"] == "open" and t.get("rule") == rk)
        if n:
            print(f"[{rk}] 동결 — 신규 진입 없음 (보유 {n}종은 트레일까지 유지)")
    led["updated"] = str(date.today())
    save(led)
    print(f"\n1차 진입 {total}건 → {LEDGER}")


# ───────────────────────── update ─────────────────────────
def cmd_update():
    """주봉 확정 후 실행. 순서는 백테와 동일 — 청산 → 축소 → 불타기."""
    led = load()
    ops = [t for t in led["trades"] if t["status"] == "open"]
    if not ops:
        print("열린 포지션 없음"); return
    print(f"열린 포지션 {len(ops)}건 갱신 "
          f"(상한 {CAP_WT:.0f}% · 분할 {TRANCHE:.0f}% · 트레일 −{TRAIL*100:.0f}%)")

    for t in ops:
        w, s = weekly(t["sym"])
        if w is None:
            print(f"  SKIP {t['sym']} 시세 실패"); continue
        ed = pd.Timestamp(t["entry_px_date"]).normalize()
        ew = ed - pd.Timedelta(days=ed.weekday())
        since = w[w.index >= ew]
        if len(since) == 0:
            print(f"  WAIT {t['sym']:6s} 완성된 주봉 없음 (진입 당주)"); continue

        peak = float(since.max()); last = float(w.iloc[-1])
        hi52 = w >= w.rolling(52, min_periods=10).max() - 1e-9
        ma20 = w.rolling(20, min_periods=5).mean()
        hi_dates = w.index[hi52.values]
        t["hi_date"] = str(hi_dates[-1].date()) if len(hi_dates) else None
        t["peak_px"] = round(peak, 4); t["peak_date"] = str(since.idxmax().date())
        t["last_px"] = round(last, 4); t["last_date"] = str(w.index[-1].date())
        hold = max(0.0, (pd.Timestamp(w.index[-1]) - ew).days / 7)

        for lab, wks in (("4w", 4), ("13w", 13), ("26w", 26)):
            if hold >= wks and lab not in t["marks"]:
                cut = ed + pd.Timedelta(weeks=wks)
                sub = w[w.index <= cut]
                if len(sub):
                    t["marks"][lab] = round((float(sub.iloc[-1]) / t["entry_px"] - 1) * 100, 2)

        dpeak = s.cummax()
        dhit = s[(s <= dpeak * (1 - TRAIL)) & (s.index > ed)]
        if len(dhit) and not t.get("daily_breach"):
            t["daily_breach"] = dict(date=str(dhit.index[0].date()),
                                     px=round(float(dhit.iloc[0]), 4))

        # ① 트레일 청산 — 전 물량 공통, 평단 기준으로 수익률 계산
        hit = since[(since <= peak * (1 - TRAIL)) & (since.index > ew)]
        if len(hit):
            xp = float(hit.iloc[0]); xd = str(hit.index[0].date())
            ap = avg_px(t)
            t.update(status="closed", exit_px=round(xp, 4), exit_date=xd,
                     avg_px=round(ap, 4),
                     ret_pct=round(((xp / ap) * (1 - COST) - 1) * 100, 2),
                     hold_wk=round((pd.Timestamp(xd) - ed).days / 7, 1))
            db = t.get("daily_breach")
            print(f"  EXIT {t['sym']:6s} {t['ret_pct']:+7.1f}%  {t['hold_wk']:.0f}주  "
                  f"{t['tr']}차·{t['wt']:.1f}%  (평단 ${ap:,.2f} → ${xp:,.2f})"
                  + (f"  [일봉 {db['date']} 선행]" if db else ""))
            continue

        # ② 3주간 52주 신고가 미갱신 → 30% 축소 (1회)
        # 기준일은 '마지막 신고가'와 '진입 주차' 중 나중 것. 백테(leaders_alloc)는
        # hi_wk를 진입 주차로 초기화하므로 진입 전부터 신고가를 못 낸 종목이 당주에
        # 축소되는 일이 없다. 페이퍼도 같은 자를 써야 대조가 성립한다.
        ref_hi = max(hi_dates[-1], ew) if len(hi_dates) else ew
        quiet = (pd.Timestamp(w.index[-1]) - ref_hi).days / 7 >= QUIET_WK
        if quiet and not t["cut"]:
            for l in t["lots"]:
                l["wt"] = round(l["wt"] * (1 - CUT_FRAC), 3)
            t["wt"] = round(sum(l["wt"] for l in t["lots"]), 2)
            t["cut"] = True
            print(f"  CUT  {t['sym']:6s} 신고가 {QUIET_WK}주+ 미갱신 → "
                  f"{CUT_FRAC*100:.0f}% 축소 (잔여 {t['wt']:.1f}%)")

        # ③ 불타기 — 규칙별 트리거, 상한 20%까지
        if t["tr"] < NTR and t.get("rule") in PYRAMID:
            mode = PYRAMID[t["rule"]]
            lastbuy = t["lots"][-1]["px"]
            m20 = float(ma20.iloc[-1]) if ma20.iloc[-1] == ma20.iloc[-1] else None
            if mode == "눌림목":
                go = (peak * 0.90 <= last <= peak * 0.95 and last > lastbuy
                      and m20 is not None and last > m20)
            else:
                go = bool(hi52.iloc[-1])
            if go:
                t["lots"].append(dict(px=round(last, 4), date=t["last_date"], wt=TRANCHE))
                t["tr"] += 1
                t["wt"] = round(sum(l["wt"] for l in t["lots"]), 2)
                t["adds"].append(dict(date=t["last_date"], px=round(last, 4), mode=mode))
                print(f"  ADD  {t['sym']:6s} {t['tr']}차 매수 ${last:,.2f} ({mode}) "
                      f"→ 비중 {t['wt']:.1f}% · 평단 ${avg_px(t):,.2f}")
                continue

        ap = avg_px(t)
        cur = (last / ap - 1) * 100
        dd = (last / peak - 1) * 100
        print(f"  HOLD {t['sym']:6s} {cur:+7.1f}%  고점대비 {dd:+6.1f}%  "
              f"{t['tr']}차·{t['wt']:.1f}%  {hold:.0f}주")

    # ④ 트림 — 월말에 평가 비중 40% 초과 시 30%로
    if (pd.Timestamp(date.today()) + pd.Timedelta(days=7)).month != date.today().month:
        opens = [t for t in led["trades"] if t["status"] == "open"]
        tot = sum(t["wt"] * (t.get("last_px", t["entry_px"]) / avg_px(t)) for t in opens)
        for t in opens:
            ev = t["wt"] * (t.get("last_px", t["entry_px"]) / avg_px(t))
            share = ev / tot * 100 if tot else 0
            if share > TRIM_HI:
                fr = 1 - TRIM_TO / share
                for l in t["lots"]:
                    l["wt"] = round(l["wt"] * (1 - fr), 3)
                t["wt"] = round(sum(l["wt"] for l in t["lots"]), 2)
                print(f"  TRIM {t['sym']:6s} 평가비중 {share:.0f}% → {TRIM_TO:.0f}% "
                      f"(잔여 {t['wt']:.1f}%)")
    led["updated"] = str(date.today())
    save(led)


# ───────────────────────── report ─────────────────────────
def cmd_report():
    led = load()
    T = pd.DataFrame(led["trades"])
    if T.empty:
        print("기록 없음 — 먼저 `python leaders_paper.py log`"); return
    T["rule"] = T["rule"].fillna("R5")
    print("=" * 104)
    print(f"주도주 페이퍼 — 시작 {led['created']} · 갱신 {led.get('updated','-')}")
    print(POLICY)
    print(f"청산 {led['exit']}   |   총 {len(T)}건")
    print("=" * 104)

    refs = REF_BY_RULE
    for rk in [k for k in RULES if (T.rule == k).any()]:
        sub = T[T.rule == rk]
        cl, op = sub[sub.status == "closed"], sub[sub.status == "open"]
        ref = refs.get(rk, {})
        frozen = " (동결)" if rk in FROZEN else f" · 불타기 {PYRAMID.get(rk,'-')}"
        print(f"\n[{rk}]{frozen} {RULES[rk][0]}")
        inv = op.wt.sum() if len(op) else 0
        print(f"     {len(sub)}건 (청산 {len(cl)} · 보유 {len(op)}) · 투입비중 {inv:.1f}%")
        if len(op):
            o = op.copy()
            o["평단"] = o.apply(lambda r: round(avg_px(r), 2), axis=1)
            cols = [c for c in ["sym", "tr", "wt", "평단", "last_px", "peak_px",
                                "cut", "hi_date"] if c in o.columns]
            print(o[cols].to_string(index=False))
        if len(cl) == 0:
            def _f(k, fmt):
                v = ref.get(k)
                return format(v, fmt) if isinstance(v, (int, float)) else "—"
            print(f"     청산 0건 — 대조 불가. 백테 기대: 승률 {_f('winrate','.0f')}% · "
                  f"CAGR {_f('cagr','.1f')}% · MDD {_f('mdd','.1f')}% · 회복 {_f('recov','.2f')}")
            continue
        live = dict(med_ret=cl.ret_pct.median(), winrate=(cl.ret_pct > 0).mean() * 100,
                    hold_wk=cl.hold_wk.mean())
        print(f"     {'지표':10s}{'실전':>10s}{'백테':>10s}{'괴리':>10s}")
        for k, lab, unit in [("med_ret", "중앙 수익", "%"), ("winrate", "승률", "%"),
                             ("hold_wk", "평균 보유", "주")]:
            lv, rf = live[k], ref.get(k)
            if rf is None or lv != lv:
                continue
            print(f"     {lab:10s}{lv:>9.1f}{unit}{rf:>9.1f}{unit}{lv-rf:>+9.1f}")
        print(f"     ⚠️ 청산 {len(cl)}건 — "
              f"{'표본 부족, 판단 불가' if len(cl) < 20 else '참고 가능'}")

    print("\n" + "-" * 104)
    print("  ⚠️ 성과 판정에는 청산 20건 이상이 필요하다 — 주 1회 실행 기준 약 1.5년.")
    print("  ⚠️ 백테는 생존편향(상폐 종목 0건)·인샘플 선택이 남아 있어 낙관적이다.")
    print("     실전이 낮게 나오는 게 정상이고, 그 격차를 재는 것이 이 원장의 목적이다.")


# ───────────────────────── notify ─────────────────────────
def _tg(text):
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
    led = load()
    T = pd.DataFrame(led["trades"])
    if T.empty:
        _tg("주도주 주간: 기록 없음"); return
    T["rule"] = T["rule"].fillna("R5")
    today = str(date.today())

    runs = led.get("runs", [])
    nrun = len(runs)
    sw = runs[-1]["signal_week"] if runs else "-"
    streak, gaps = (1 if runs else 0), 0
    for a, b in zip(runs, runs[1:]):
        dd = (pd.Timestamp(b["signal_week"]) - pd.Timestamp(a["signal_week"])).days
        if dd == 7:
            streak += 1
        else:
            streak, gaps = 1, gaps + 1

    op_all = T[T.status == "open"]
    L = [f"<b>🚀 주도주 {nrun}주차</b>  (신호주 {sw})",
         f"{today} · 상한 {CAP_WT:.0f}% · {NTR}분할 · 트레일 −{TRAIL*100:.0f}%",
         f"M6a 규율 {streak}/13주" + (f" · 🔴 {gaps}주 걸름" if gaps else " ✅ 연속"),
         " · ".join(f"{rk} 투입 {op_all[op_all.rule==rk].wt.sum():.0f}%"
                     for rk in SLOTS), ""]

    new_x = T[(T.status == "closed") & (T.exit_date.astype(str) >= today)]
    new_e = T[(T.status == "open") & (T.log_date == today)]
    new_a = [t for t in led["trades"] if t["status"] == "open"
             and any(a["date"] >= today for a in t.get("adds", []))]
    if len(new_x):
        L.append("<b>❌ 청산</b>")
        for _, t in new_x.iterrows():
            L.append(f"  {t['sym']} {t['ret_pct']:+.1f}% · {t['hold_wk']:.0f}주 [{t['rule']}]")
        L.append("")
    if new_a:
        L.append("<b>🔥 불타기</b>")
        for t in new_a:
            a = t["adds"][-1]
            L.append(f"  {t['sym']} {t['tr']}차 ${a['px']:,.2f} ({a['mode']}) → {t['wt']:.0f}%")
        L.append("")
    if len(new_e):
        L.append("<b>✅ 1차 진입</b>")
        for _, t in new_e.iterrows():
            L.append(f"  {t['sym']} ${t['entry_px']:,.2f} {TRANCHE:.0f}% "
                     f"RS{t['rs_13w']:.2f} [{t['rule']}]")
        L.append("")
    if not len(new_x) and not len(new_e) and not new_a:
        L.append("<i>이번 주 변동 없음</i>\n")

    for rk in [k for k in RULES if (T.rule == k).any()]:
        sub = T[T.rule == rk]
        op, cl = sub[sub.status == "open"], sub[sub.status == "closed"]
        tagf = "동결" if rk in FROZEN else PYRAMID.get(rk, "-")
        L.append(f"<b>[{rk}]</b> 보유 {len(op)} · 청산 {len(cl)} · "
                 f"비중 {op.wt.sum():.0f}% ({tagf})")
        rows = []
        for _, t in op.iterrows():
            pk = t["peak_px"]; last = t.get("last_px") or pk
            stop = pk * (1 - TRAIL)
            room = (stop / last - 1) * 100
            pnl = (last / avg_px(t) - 1) * 100
            rows.append((room, t["sym"], last, stop, pnl, t["tr"], t["wt"], t["cut"]))
        for room, sym, last, stop, pnl, tr, wt, cut in sorted(rows, reverse=True):
            flag = " ⚠️" if room > -5 else ""
            mark = " ✂️" if cut else ""
            L.append(f"  {sym:<5} ${last:,.2f} ({pnl:+.1f}%) {tr}차·{wt:.1f}%{mark} "
                     f"· 청산선 ${stop:,.2f} [{room:+.1f}%]{flag}")
        if len(cl):
            L.append(f"  실적: 승률 {(cl.ret_pct>0).mean()*100:.0f}% · "
                     f"중앙 {cl.ret_pct.median():+.1f}%")
        L.append("")

    n_cl = int((T.status == "closed").sum())
    L.append(f"<i>M6b 성과표본 청산 {n_cl}/20건</i>")
    _tg("\n".join(L))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    {"log": cmd_log, "update": cmd_update, "report": cmd_report,
     "notify": cmd_notify}.get(cmd, cmd_report)()
