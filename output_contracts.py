# -*- coding: utf-8 -*-
"""산출물 계약 — '파일이 새로 써졌나'가 아니라 '내용이 정상인가'를 커밋 직전에 검사한다.

왜 만들었나 (2026-10-14)
  10-13 전수 점검에서 나온 고장 8건이 전부 같은 모양이었다: **파일은 매일 새로 써지는데
  내용이 비었거나 낡았다.** 감시 장치는 파일 날짜(mtime)·JSON 안 날짜만 봤다.
    · perf_latest.json   KR 692 → 0종          (날짜는 매일 갱신)
    · 52주 신고가 신호     1,065종 중 0종        (항상)
    · leaders_accel.json  universe 945 → 2종    (CI 가 덮어씀)
    · kr_fundamentals_q   순이익 전 행 공란·2026Q1 정지 — 신선도 검사는 'age 0 정상'
  개별 원인은 고쳤지만, 다음 고장도 같은 모양으로 올 것이다. 그래서 **산출물마다
  '정상이면 반드시 성립하는 조건'을 적어두고, 어기면 커밋하지 않는다.**

동작
  python output_contracts.py --guard      변경된 산출물 중 BLOCK 위반은 직전 커밋본으로 되돌리고
                                          results/contract_violations.json 에 기록. 종료코드 0.
  python output_contracts.py --fail-if-violated   위 기록이 있으면 텔레그램 + 종료코드 1
                                          (커밋 '뒤'에 두어 정상 산출물은 커밋되게 한다)
  python output_contracts.py --report     전체 점검 결과 출력(되돌리지 않음)

등급
  BLOCK — 이 상태로 화면에 내보내면 틀린 결론을 낸다 → 되돌린다
  WARN  — 이상하지만 시장 상황으로 정상일 수 있다 → 알리기만 한다
"""
import json
import os
import subprocess
import sys
from datetime import date, datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.abspath(__file__))
VIOL = os.path.join(BASE, ".contract_violations.json")   # results/*.json 은 통째로 커밋되므로 밖에 둔다
TODAY = date.today()
BLOCK, WARN = "BLOCK", "WARN"


# ───────────────────────── 도구 ─────────────────────────
def _j(path):
    with open(os.path.join(BASE, path), encoding="utf-8") as f:
        return json.load(f)


def _age(s):
    """'2026-10-13' 또는 '2026-10-13T02:27:04' → 오늘까지 일수"""
    if not s:
        return 9999
    try:
        return (TODAY - datetime.fromisoformat(str(s)[:19]).date()).days
    except Exception:
        return 9999


def _mkt(stocks, m):
    return sum(1 for s in stocks if s.get("market") == m)


def _fill(stocks, key):
    if not stocks:
        return 0.0
    return sum(1 for s in stocks if s.get(key) not in (None, "", "-")) / len(stocks)


def chk(cond, sev, msg):
    return None if cond else (sev, msg)


# ───────────────────────── 계약 ─────────────────────────
# 각 함수는 [(등급, 문구), ...] 를 돌려준다. 빈 리스트 = 정상.
def c_perf():
    d = _j("results/perf_latest.json"); st = d.get("stocks", [])
    n52 = sum(1 for s in st if s.get("now_sig_52w"))
    return [chk(_age(d.get("date")) <= 4, BLOCK, f"date {d.get('date')} 4일 초과"),
            chk(_mkt(st, "KR") >= 300, BLOCK, f"KR {_mkt(st,'KR')}종 (<300) — KR 수집 고장"),
            chk(_mkt(st, "US") >= 300, BLOCK, f"US {_mkt(st,'US')}종 (<300)"),
            chk(n52 > 0, WARN, f"52주 신고가 신호 0/{len(st)} — 시장 급락이 아니면 신호 계산 고장")]


def c_screener():
    d = _j("results/screener_latest.json"); st = d.get("stocks", [])
    fails = d.get("fetch_fail_pct") or {}
    out = [chk(_age(d.get("date")) <= 4, BLOCK, f"date {d.get('date')} 4일 초과"),
           chk(_mkt(st, "KR") > 0 or len(st) == 0, WARN, "신호 종목이 전부 US — KR 수집 확인")]
    for m, v in fails.items():
        out.append(chk((v or 0) < 30, BLOCK, f"{m} 가격 수집 실패 {v}% (≥30%)"))
    return out


def c_canslim_kr():
    d = _j("results/canslim_latest.json"); st = d.get("stocks", [])
    return [chk(_age(d.get("date")) <= 4, BLOCK, f"date {d.get('date')} 4일 초과 — 유니버스/가격 수집 고장"),
            chk(d.get("market_dir") not in (None, "N/A", "—"), BLOCK, "시장방향(M) 판정 실패"),
            chk(len(st) >= 10, WARN, f"후보 {len(st)}종 (<10)"),
            chk(_fill(st, "c_growth_pct") >= 0.5, WARN, f"C(분기실적) 채움률 {_fill(st,'c_growth_pct'):.0%}")]


def c_canslim_us():
    d = _j("results/canslim_us_latest.json"); st = d.get("stocks", [])
    return [chk(_age(d.get("date")) <= 4, BLOCK, f"date {d.get('date')} 4일 초과"),
            chk(len(st) >= 10, BLOCK, f"후보 {len(st)}종 (<10)"),
            chk(_fill(st, "c_growth_pct") >= 0.5, WARN, f"C 채움률 {_fill(st,'c_growth_pct'):.0%}")]


def c_value():
    d = _j("results/value_kr.json"); st = d.get("stocks", [])
    return [chk(_age(d.get("generated")) <= 4, BLOCK, f"generated {d.get('generated')} 4일 초과"),
            chk(len(st) >= 150, BLOCK, f"{len(st)}종 (<150)"),
            chk(_fill(st, "per") >= 0.6, WARN, f"PER 채움률 {_fill(st,'per'):.0%}")]


def c_turnaround():
    d = _j("results/turnaround_latest.json"); st = d.get("stocks", [])
    old = sum(1 for s in st if _age(s.get("q0_date")) > 200)
    gap = (d.get("skipped") or {}).get("분기_누락", 0)
    # 분기 누락으로 '판정 보류'된 것이면 틀린 결과를 되살리는 것보다 비어 있는 게 낫다 → 경고만
    kr_sev = WARN if gap >= 100 else BLOCK
    return [chk(_age(d.get("date")) <= 9, BLOCK, f"date {d.get('date')} 9일 초과"),
            chk(d.get("kr", 0) >= 100, kr_sev, f"KR {d.get('kr')}종 (<100)"
                + (f" — 분기 누락 {gap}종 판정 보류(KR 분기재무 재적재 필요)" if gap else " — KR 분기재무 확인")),
            chk(d.get("us", 0) >= 50, BLOCK, f"US {d.get('us')}종 (<50) — fq_ 캐시 확인"),
            chk(old <= max(3, len(st) * 0.02), BLOCK, f"최신 분기가 200일 넘은 종목 {old}개 — 낡은 재무로 판정 중")]


def c_profile(path, kr_min, us_min, key="date"):
    def f():
        d = _j(path); st = d.get("stocks", [])
        return [chk(_age(d.get(key)) <= 9, BLOCK, f"{key} {d.get(key)} 9일 초과"),
                chk(_mkt(st, "KR") >= kr_min, BLOCK, f"KR {_mkt(st,'KR')}종 (<{kr_min})"),
                chk(_mkt(st, "US") >= us_min, BLOCK, f"US {_mkt(st,'US')}종 (<{us_min})")]
    return f


def c_accel():
    d = _j("results/leaders_accel.json")
    wk = max(d.get("weeks") or {"": 0}) if d.get("weeks") else None
    u = d.get("universe") or 0
    # 목표는 2,400+ 이지만 10-14 현재 정상 운영값이 945 다. 붕괴(2·242)는 막고, 미달은 알린다.
    return [chk(u >= 500, BLOCK, f"universe {u} (<500) — 가격 DB 붕괴"),
            chk(u >= 1000, WARN, f"universe {u} (<1000) — 수집 범위 미달"),
            chk(_age(d.get("signal_week")) <= 16, BLOCK, f"signal_week {d.get('signal_week')} 16일 초과"),
            chk(_age(wk) <= 16, WARN, f"신호가 있는 마지막 주 {wk}")]


def c_curves():
    d = _j("results/price_curves.json")
    return [chk(_age(d.get("generated")) <= 9, BLOCK, f"generated {d.get('generated')} 9일 초과"),
            chk(len(d.get("curves") or {}) >= 500, BLOCK, f"곡선 {len(d.get('curves') or {})}종 (<500)")]


def c_kr_leaders():
    out = []
    for p in ("results/leaders_kr.json", "results/leaders_kr6.json"):
        d = _j(p)
        out.append(chk(_age(d.get("generated")) <= 9, BLOCK, f"{p} generated {d.get('generated')} 9일 초과"))
    return out


def c_sectors():
    d = _j("data/sectors.json")
    kr = sum(1 for k in d if str(k).isdigit())
    vals = [v for k, v in d.items() if str(k).isdigit()]
    dept = sum(1 for v in vals if str(v).endswith("기업부"))      # 코스닥 소속부가 섞이면 업종이 아니다
    return [chk(kr >= 2000, BLOCK, f"KR 섹터 {kr}종 (<2000)"),
            chk(len(d) - kr >= 400, BLOCK, f"US 섹터 {len(d)-kr}종 (<400)"),
            chk(dept == 0, BLOCK, f"KR 섹터에 '소속부' {dept}건 — 업종(Industry)이 아니다")]


def c_kr_fundq():
    import pandas as pd
    r = pd.read_parquet(os.path.join(BASE, "data/kr_fundamentals_q.parquet"))
    yq = (r.year * 10 + r.q).max()
    yr, q = int(yq // 10), int(yq % 10)
    # 대다수 종목의 최신 분기(꼬리의 이상치에 끌려가지 않게 80% 분위)
    last = (r.year * 10 + r.q).groupby(r.sym).max().quantile(0.8)
    ly, lq = int(last // 10), int(last % 10)
    q_end = date(ly, lq * 3, 1)
    fill = r.net_income.notna().mean()
    # 분기 누락 — 작년 각 분기를 가진 종목 수가 가장 많은 분기의 80% 미만이면 구멍이다
    #   (2026-10-14 실측: 2025Q3 7종·Q4 24종 vs Q1 1,442종 — 적재 코드의 격년 호출 버그)
    py = TODAY.year - 1
    cnt = r[r.year == py].groupby("q").sym.nunique().reindex([1, 2, 3, 4]).fillna(0)
    holes = [f"{py}Q{q}" for q, n in cnt.items() if cnt.max() and n < cnt.max() * 0.8]
    return [chk(not holes, BLOCK, f"분기 누락 {holes} — 최근 4분기 계산이 어긋난다"),chk((TODAY - q_end).days <= 200, BLOCK, f"대다수 종목 최신 분기 {ly}Q{lq} — 200일 초과(export 안 됨)"),
            chk(fill >= 0.8, BLOCK, f"순이익 채움률 {fill:.0%} (<80%)")]


def c_us_marketcap():
    import pandas as pd
    d = pd.read_csv(os.path.join(BASE, "data/us_marketcap.csv"))
    pxd = d["px_date"].dropna().max() if "px_date" in d else None
    return [chk(len(d) >= 1500, BLOCK, f"{len(d)}행 (<1500)"),
            chk(_age(pxd) <= 5, BLOCK, f"가격일 {pxd} 5일 초과")]


def c_report():
    """2026-10-15: 처음엔 latest_daily 만 봤다. 주간 실행이 지수 8개짜리 정상 리포트를 만들었는데
    오래된 일간 시드(지수 2개) 때문에 BLOCK → 파일째 되돌려 **정상 주간 리포트를 버렸다.**
    이제 품질은 '방금 만든(가장 최근 generated) 리포트'로 보고, 일간 신선도는 따로 본다."""
    d = _j("results/market_report.json")
    ld = d.get("latest_daily") or {}
    reps = [r for r in (ld, d.get("latest_weekly") or {}) if r]
    new = max(reps, key=lambda r: str(r.get("generated") or "")) if reps else {}
    idx = [x for x in (new.get("facts") or {}).get("indices", []) if "close" in x]
    k = new.get("kind", "?")
    return [chk(_age(ld.get("date")) <= 4, WARN, f"일간 리포트 {ld.get('date')} 4일 초과"),
            chk(len(idx) >= 4, BLOCK, f"{k} 리포트 지수 {len(idx)}개만 수집 — Yahoo 실패"),
            chk(len(new.get("markdown") or "") >= 300, BLOCK, f"{k} 리포트 본문이 비었다"),
            chk(str(new.get("engine", "")).startswith("gemini"), WARN, f"AI 대신 숫자 템플릿({new.get('engine')}) — 키·한도 확인")]


CONTRACTS = {
    "results/market_report.json": c_report,
    "results/perf_latest.json": c_perf,
    "results/screener_latest.json": c_screener,
    "results/canslim_latest.json": c_canslim_kr,
    "results/canslim_us_latest.json": c_canslim_us,
    "results/value_kr.json": c_value,
    "results/turnaround_latest.json": c_turnaround,
    "results/returns.json": c_profile("results/returns.json", 500, 800),
    "results/mdd.json": c_profile("results/mdd.json", 500, 800),
    "results/seasonality.json": c_profile("results/seasonality.json", 500, 800),
    "results/leaders_accel.json": c_accel,
    "results/price_curves.json": c_curves,
    "results/leaders_kr.json": c_kr_leaders,
    "data/sectors.json": c_sectors,
    "data/kr_fundamentals_q.parquet": c_kr_fundq,
    "data/us_marketcap.csv": c_us_marketcap,
}


def evaluate(paths=None):
    res = {}
    for p, fn in CONTRACTS.items():
        if paths is not None and p not in paths:
            continue
        if not os.path.exists(os.path.join(BASE, p)):
            res[p] = [(BLOCK, "파일 없음")]
            continue
        try:
            res[p] = [x for x in fn() if x]
        except Exception as e:
            res[p] = [(BLOCK, f"검사 중 예외 — 형식이 바뀌었나: {str(e)[:100]}")]
    return res


def _changed():
    """이번 실행에서 바뀐(아직 커밋 안 된) 산출물만 검사 대상으로 한다."""
    try:
        out = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"],
                                      cwd=BASE, text=True)
    except Exception:
        return None
    return {line[3:].strip().strip('"') for line in out.splitlines()}


def _notify(text):
    try:
        import config
        from telegram_notifier import send_message
        if config.TELEGRAM_ENABLED:
            send_message(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, text)
    except Exception as e:
        print("텔레그램 실패:", e)


def guard():
    ch = _changed()
    targets = set(CONTRACTS) if ch is None else (set(CONTRACTS) & ch)
    res = evaluate(targets)
    blocked, warns = {}, {}
    for p, vs in res.items():
        b = [m for s, m in vs if s == BLOCK]
        w = [m for s, m in vs if s == WARN]
        if b:
            blocked[p] = b
            r = subprocess.call(["git", "checkout", "HEAD", "--", p], cwd=BASE)
            print(f"⛔ {p}: {' / '.join(b)} → {'직전 커밋본으로 되돌림' if r == 0 else '되돌리기 실패(신규 파일?)'}")
        if w:
            warns[p] = w
            print(f"⚠️ {p}: {' / '.join(w)}")
    print(f"계약 검사: 대상 {len(targets)}개 · 차단 {len(blocked)} · 경고 {len(warns)}")
    if blocked or warns:
        prev = {}
        if os.path.exists(VIOL):
            try:
                prev = json.load(open(VIOL, encoding="utf-8"))
            except Exception:
                prev = {}
        prev.setdefault("blocked", {}).update(blocked)
        prev.setdefault("warn", {}).update(warns)
        prev["at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        prev["workflow"] = os.environ.get("GITHUB_WORKFLOW", "local")
        json.dump(prev, open(VIOL, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


def fail_if_violated():
    if not os.path.exists(VIOL):
        print("계약 위반 없음")
        return 0
    v = json.load(open(VIOL, encoding="utf-8"))
    os.remove(VIOL)
    lines = [f"⛔ {p}\n   " + "\n   ".join(m) for p, m in v.get("blocked", {}).items()]
    lines += [f"⚠️ {p}\n   " + "\n   ".join(m) for p, m in v.get("warn", {}).items()]
    msg = (f"🧾 [screener] 산출물 계약 위반 — {v.get('workflow')}\n"
           + "\n".join(lines)
           + ("\n\n⛔ 항목은 커밋하지 않고 직전 정상본을 유지했다." if v.get("blocked") else ""))
    print(msg)
    _notify(msg)
    return 1 if v.get("blocked") else 0


def report():
    res = evaluate()
    bad = 0
    for p, vs in res.items():
        tag = "✅" if not vs else ("⛔" if any(s == BLOCK for s, _ in vs) else "⚠️")
        bad += tag == "⛔"
        print(f"{tag} {p}" + ("" if not vs else "\n     " + "\n     ".join(f"[{s}] {m}" for s, m in vs)))
    return 1 if bad else 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--guard" in a:
        sys.exit(guard())
    if "--fail-if-violated" in a:
        sys.exit(fail_if_violated())
    sys.exit(report())
