# -*- coding: utf-8 -*-
"""🧮 퀀트 백테스트용 주봉 패널 — 미국·한국을 같은 열 이름으로 (2026-11-01, 차니 요구 7)

열(공통): sym, name, market, date(주 월요일), open, high, low, close, volume, marcap,
          per, pbr, psr, rev_yoy, op_yoy, op_turn(0/1), acc(이익가속 0/1, 미국만), sector
  · 재무는 그 주에 **알 수 있던 값만**: 미국 = SEC 공시일 기준(factor_weekly), 한국 = 분기말 +45일(4분기 +90일).
  · 기술 지표(이평·RSI·MACD·RS·신고가·캔들)는 엔진(quant_engine.py)이 OHLCV 로 계산한다 — 여기서 굳히지 않는다.
  · 종목 수: 그 주 시총 미국 $0.2B+ / 한국 500억+ 인 행만(보유 중 종목이 이 밑으로 떨어지면 가격이 끊긴다 → 엔진이 마지막 가격으로 정리).
결과: results/quant_panel_US.parquet · quant_panel_KR.parquet (git 이 아니라 GitHub Release 'quant-panel' 에 올린다 — 수십 MB)
"""
import os, sys, glob, json, sqlite3, subprocess
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "results")
COLS = ["sym", "name", "market", "date", "open", "high", "low", "close", "volume", "marcap",
        "per", "pbr", "psr", "rev_yoy", "op_yoy", "op_turn", "acc", "sector",
        "opm", "gpm", "rev_qoq", "roe", "debt", "oi_g"]   # 2026-11-01 확장 — 시장에 없는 열은 빈 값
#   ⚠️ 2026-11-22: oi_g(이익 개선폭)는 kr() 가 줄곧 계산했는데 COLS 에 없어 _f32 가 버렸다.
#      엔진 _BASE 에는 있어 화면에 지표는 뜨고 패널엔 열이 없어 조건이 전부 거짓 → 매매 0건.


def _f32(d):
    for c in ("open", "high", "low", "close", "volume", "marcap", "per", "pbr", "psr", "rev_yoy", "op_yoy",
              "opm", "gpm", "rev_qoq", "roe", "debt", "oi_g"):
        if c not in d:
            d[c] = np.nan
        d[c] = pd.to_numeric(d[c], errors="coerce").astype("float32")
    for c in ("op_turn", "acc"):
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0).astype("int8")
    return d[COLS]


def _keep_once_in(d, floor):
    """2026-11-12 감사 — 시총 하한을 '그 주' 기준으로 자르면 ① 시총이 비는 주(상장 첫해·SEC 주식수 공백·회전율로 비운 칸)와
    ② 하한 아래로 떨어진 보유 종목의 가격이 통째로 사라져, 엔진이 '패널 이탈 = 마지막 종가에 정리'로 처리한다(급락 손실 누락).
    한 번이라도 하한을 넘은 종목은 그 뒤 행을 남긴다(시총 NaN 포함). 매수 필터(marcap ≥ 하한)는 엔진이 그대로 건다."""
    d = d.sort_values(["sym", "date"])
    hit = (d.marcap >= floor).astype(int).groupby(d.sym).cummax().astype(bool)
    return d[hit].copy()


# 2026-11-22 — 그 시장에서 **반드시 값이 있어야 하는** 열. 0% 면 빌드를 실패시킨다.
#   왜: oi_g 는 kr() 가 계산해 놓고도 COLS 에 없어 통째로 버려졌고, 미국 sector·KR rev_qoq 는
#   아무도 채우지 않았다. 셋 다 화면엔 지표로 떠 있어서 '조건을 걸면 매매 0건'으로만 보였다.
#   빠진 열은 조용히 NaN 이 되고, 조건이 전부 거짓이 되며, 백테스트는 오류 없이 0건을 낸다.
MUST = {
    "US": ("per", "psr", "rev_yoy", "op_yoy", "opm", "gpm", "rev_qoq", "oi_g", "sector"),
    "KR": ("per", "pbr", "psr", "rev_yoy", "op_yoy", "opm", "rev_qoq", "oi_g", "roe", "debt", "sector"),
}
#   아직 소스가 없는 열(채우면 MUST 로 옮긴다):
#     US pbr·roe·debt — SEC 자본총계·부채총계 미수집(leaders_build TAGS 에 재무상태표 항목 없음)
#     KR gpm          — kr_fundamentals_q 에 gross_profit 없음(DART 손익계산서 매출총이익 수집 필요)
NOT_YET = {"US": ("pbr", "roe", "debt"), "KR": ("gpm",)}


def report_coverage(d, m):
    """열별 값 있는 비율·첫 값 날짜를 찍고, MUST 열이 비면 SystemExit."""
    rows, dead = [], []
    for c in COLS:
        if c in ("sym", "name", "market", "date"):
            continue
        nn = int(d[c].notna().sum())
        p = nn / max(len(d), 1) * 100
        first = d.loc[d[c].notna(), "date"].min() if nn else None
        tag = "" if c in MUST.get(m, ()) else ("  (소스 없음)" if c in NOT_YET.get(m, ()) else "  (참고)")
        rows.append(f"    {c:9s} {p:6.2f}%  첫값 {str(first.date()) if nn else '-'}{tag}")
        if c in MUST.get(m, ()) and nn == 0:
            dead.append(c)
    print(f"[{m}] 열 커버리지\n" + "\n".join(rows), flush=True)
    if dead:
        #   ::error:: 를 같이 찍는다 — Actions 로그는 비공개 저장소에서 로그인이 필요해
        #   로그를 볼 수 없는 쪽에는 'exit code 1' 만 보인다(11-23 weekly-accel #33 교훈).
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::error title=패널 {m} 빈 열::값이 있어야 하는 열이 0%: {', '.join(dead)}", flush=True)
        raise SystemExit(f"[{m}] 반드시 값이 있어야 하는 열이 0%: {', '.join(dead)} — "
                         f"COLS 에 있는지 · 계산·merge 가 실제로 붙는지 확인하라")


def coverage(d, probes):
    """정답 점검용 — 종목별 첫 주. known_answers 가 읽는다."""
    out = {}
    for s_ in probes:
        x = d.loc[d.sym == s_, "date"]
        out[s_] = str(x.min().date()) if len(x) else None
    return out


# 2026-11-22 — 미국 시계열은 **통째로 쌓은 판을 앞에, 증분 판을 뒤에** 이어 붙인다.
#   v1(증분)은 과거 행을 고치지 않아 분할이 일어난 종목의 과거 가격이 분할 전 값으로 남는다.
#   실측: 겹침 959,977행 중 105,618행(11.0%)·252종이 일봉 원본과 0.5% 넘게 어긋났고,
#   v13y(통째)가 어긋난 종목은 0 이었다 — AAPL·BAC·AMGN·ADM·AEP 가 그 252종에 있다.
#   접합부(2017-12 → 2018-01) 주간 변동률은 중앙 1.018 · 99%분위 1.228 · ×5 초과 0종이라
#   이어 붙여도 가짜 손익이 생기지 않는다.
#   FACTOR_VER 로 하나만 지정하면 그것만 쓴다(기존 동작 유지).
US_VERS = ("v13y", "v1")


def _us_vers():
    """DB 에 있는 ver 만, US_VERS 우선순위로. FACTOR_VER 가 주어지면 그 하나만."""
    env = (os.environ.get("FACTOR_VER") or "").strip()
    c = sqlite3.connect(f"file:{os.path.join(ROOT, 'data', 'market.db')}?mode=ro", uri=True)
    have = {r[0] for r in c.execute("SELECT DISTINCT factor_ver FROM factor_weekly")}
    c.close()
    if env:
        return (env,) if env in have else ()
    got = tuple(v for v in US_VERS if v in have)
    return got or (tuple(sorted(have))[:1] if have else ())


SEAM = {}          # us() 가 접합 상태를 남긴다 → main() 이 info.json 에 기록


def _seam_note(vers):
    """접합에 쓴 ver 별 기간·행수와 **통째 판이 얼마나 낡았나**를 기록한다.

    왜 기록하나: 통째 판(v13y)이 낡으면 그만큼 긴 구간을 증분 판(v1)이 메우고,
    증분 판은 분할을 과거로 전파하지 않으므로 **썩은 구간이 그만큼 늘어난다.**
    데이터는 최신이라 어떤 경보도 울리지 않는다 — 그래서 숫자로 남겨 둔다."""
    c = sqlite3.connect(f"file:{os.path.join(ROOT, 'data', 'market.db')}?mode=ro", uri=True)
    rows = {v: c.execute("SELECT COUNT(*), MIN(as_of), MAX(as_of) FROM factor_weekly WHERE factor_ver=?",
                         (v,)).fetchone() for v in vers}
    c.close()
    out = dict(vers=list(vers),
               by_ver={v: dict(rows=int(n or 0), start=a, end=b) for v, (n, a, b) in rows.items()})
    if len(vers) > 1:
        base, inc = vers[0], vers[-1]
        be, ie = rows[base][2], rows[inc][2]
        if be and ie:
            gap = (pd.Timestamp(ie[:10]) - pd.Timestamp(be[:10])).days
            out["base_stale_days"] = int(gap)
            out["filled_by_incremental"] = f"{be} ~ {ie}"
            out["note"] = (f"통째 판 {base} 가 {gap}일 낡았다 — 그 구간({be}~{ie})은 증분 판 {inc} 이 메운다. "
                           f"증분 판은 분할을 과거로 전파하지 않으므로 이 구간에 분할이 있었던 종목의 "
                           f"가격은 틀릴 수 있다. {base} 를 다시 쌓으면(약 48분) 사라진다.")
            if gap > 56:
                print(f"[US] ⚠️ {out['note']}", flush=True)
    return out


def us():
    vers = _us_vers()
    if not vers:
        raise SystemExit("factor_weekly 가 비어 있다 — 미국 패널을 만들 수 없다")
    SEAM.clear()
    SEAM.update(_seam_note(vers))
    ver = vers[0]
    os.environ["FACTOR_VER"] = ver
    import leaders_accel as A
    d = A.load(vers=vers)                                # ACC 계산 포함 · 여러 ver 접합
    c = sqlite3.connect(os.path.join(ROOT, "data", "market.db"))
    # 2026-11-22: roe·debt 추가(leaders_build 가 SEC 재무상태표를 받기 시작했다). 아직 안 받은 DB 도 돌게 열 존재를 확인한다.
    _fw = {x[1] for x in c.execute("PRAGMA table_info(factor_weekly)")}
    _opt = [x for x in ("roe", "debt") if x in _fw]
    _ph = ", ".join("?" * len(vers))
    extra = pd.read_sql(f"SELECT factor_ver, as_of, sym, sector, pbr, op_turn, op_income, rev_qoq"
                        f"{(', ' + ', '.join(_opt)) if _opt else ''} FROM factor_weekly "
                        f"WHERE factor_ver IN ({_ph})", c, params=vers)
    #   d 와 같은 우선순위로 중복을 걷어야 한다 — 안 그러면 merge 가 행을 불린다
    extra["_pri"] = extra.factor_ver.map({v: i for i, v in enumerate(vers)})
    extra = (extra.sort_values("_pri").drop_duplicates(["sym", "as_of"], keep="first")
                  .drop(columns=["_pri", "factor_ver"]))
    extra["as_of"] = pd.to_datetime(extra.as_of)
    d = d.merge(extra, on=["as_of", "sym"], how="left", suffixes=("", "_x"))
    px = pd.read_sql("SELECT sym, date, open, high, low, volume FROM prices WHERE market='US'", c)
    px["date"] = pd.to_datetime(px.date)
    d = d.rename(columns={"as_of": "date"}).merge(px, on=["sym", "date"], how="left")
    # 2026-11-08 시총 정합(us_capfix) — 분할 직후 주식수 기준 어긋남(TSLA 2022-08 $281B·GOOGL 2022-07 $73B·PER 1.0)·
    #   역분할 초소형주 부풀림(SLS 2017 $35.5B)·단위 ×1,000 오류·ADR 배수, 빈 시총 채움. PER·PBR·PSR 도 같은 배수.
    import us_capfix
    d = us_capfix.fix(d, ratios=("per", "pbr", "psr"))
    print(f"[US] 시총 정합: 1.5배 넘게 고친 칸 {int((np.abs(np.log(d._capfix)) > np.log(1.5)).sum()):,} · "
          f"{d.loc[np.abs(np.log(d._capfix)) > np.log(1.5), 'sym'].nunique()}종 · 회전율로 비운 칸 {int(d._capbad.sum()):,}"
          f"({d.loc[d._capbad, 'sym'].nunique()}종)", flush=True)
    _chk = {("TSLA", "2022-08-29"): (5e11, 1.5e12), ("GOOGL", "2022-07-11"): (8e11, 2.5e12), ("NVDA", "2023-01-02"): (2e11, 6e11),
            ("AAPL", "2020-08-24"): (1.5e12, 2.8e12)}
    for (s_, dt), (lo, hi) in _chk.items():
        v = d.loc[(d.sym == s_) & (d.date == pd.Timestamp(dt)), "marcap"]
        if len(v) and not (lo <= float(v.iloc[0]) <= hi):
            _m = (f"시총 정답 점검 실패: {s_} {dt} = {float(v.iloc[0]) / 1e9:,.0f}B "
                  f"(기대 {lo / 1e9:,.0f}~{hi / 1e9:,.0f}B)")
            if os.environ.get("GITHUB_ACTIONS"):
                print(f"::error title=패널 US 시총::{_m}", flush=True)
            raise SystemExit(f"[US] {_m}")
    # 거래 없는 주(거래량 0 — 비상장 리츠 IVT 처럼 호가만 멈춰 있는 값)는 체결할 수 없다 → 뺀다
    d = d[~(d.volume == 0)]
    d = d.drop(columns=["_capfix", "_capbad"])
    d = _keep_once_in(d, 2e8)
    # 영업이익 YoY: 같은 종목 4분기 전 값(분기 패널에서)
    # 2026-11-22: 이익 개선폭(oi_g)도 같은 분기 패널에서 — 한국만 있던 지표(kr_oi_g)를 미국에도.
    #   정의·하한은 leaders_accel 과 같다(분기 매출 $10M 미만은 발산하므로 빈값), 단위는 %p 로 맞춘다.
    q = (d.dropna(subset=["period_end"]).drop_duplicates(["sym", "period_end"])
          [["sym", "period_end", "op_income", "revenue"]].sort_values(["sym", "period_end"]))
    q["op4"] = q.groupby("sym").op_income.shift(4)
    q["op_yoy"] = np.where(q.op4 > 0, (q.op_income / q.op4 - 1) * 100, np.nan)
    _rev = q.revenue.where(q.revenue.abs() >= A.MIN_QREV)
    q["oi_g"] = ((q.op_income - q.op4) / _rev.abs() * 100).replace([np.inf, -np.inf], np.nan)
    d = d.merge(q[["sym", "period_end", "op_yoy", "oi_g"]], on=["sym", "period_end"], how="left")
    d["market"] = "US"
    # 2026-11-22: 업종 — leaders_build 가 factor_weekly.sector 에 None 을 박아 미국 업종이 0% 였다.
    #   SEC SIC 설명(data/us_domicile.csv)을 쓴다. 대시보드·common_metrics 도 같은 파일을 본다.
    d = d.drop(columns=[c for c in ("sector", "sector_x") if c in d.columns])
    try:
        #   keep_default_na=False — 티커 'NA'(Nabors) 가 NaN 으로 읽혀 매핑에서 사라진다
        dom = pd.read_csv(os.path.join(ROOT, "data", "us_domicile.csv"), usecols=["sym", "sic_desc"],
                          keep_default_na=False, na_values=[""])
        dom = dom[dom.sic_desc.notna() & (dom.sic_desc.astype(str).str.strip() != "")]
        d["sector"] = d.sym.map(dict(zip(dom.sym.astype(str), dom.sic_desc.astype(str).str.strip())))
    except Exception as e:
        print(f"[US] 업종 매핑 실패({e}) — sector 빈 값", flush=True)
        d["sector"] = None
    d["acc"] = d["ACC"]
    for k in ("open", "high", "low"):
        d[k] = d[k].fillna(d["close"])
    # 2026-11-01 가격 정합 — 역분할 보정이 깨진 초소형주(MLMC·BQST·COSG 등)가 주간 ×20~×3,000 으로 튀어
    #   '시총 상위'로 잡히고 할로윈 예시가 ×3,061 이 됐다. ① $1 미만 행 제외 ② 주간 ×5 초과·÷5 미만 급변 행은
    #   그 종목을 통째로 뺀다.
    d = d[d.close >= 1].sort_values(["sym", "date"]).copy()
    r = d.groupby("sym").close.transform(lambda s: s / s.shift(1))
    bad = (r > 5) | (r < 0.2)
    #   급변 행만 비우면 앞뒤 가격 수준 차이(보정 실패)가 그대로 수익으로 잡힌다 → 그런 종목은 통째로 뺀다(수 종목, 영향 미미).
    bad_syms = sorted(d.loc[bad, "sym"].unique())
    d = d[~d.sym.isin(bad_syms)]
    print(f"[US] 주간 ×5↑·÷5↓ 급변 {int(bad.sum())}칸 → {len(bad_syms)}종 제외 {bad_syms[:20]} · $1 미만 행 제외")
    print(f"[US] {'+'.join(vers)} {d.date.min().date()}~{d.date.max().date()} · {d.sym.nunique():,}종 · {len(d):,}행")
    return _f32(d)


def kr():
    dd = os.path.join(ROOT, "data", "research", "marcap")
    os.makedirs(dd, exist_ok=True)
    yr = pd.Timestamp.today().year
    for y in range(2014, yr + 1):
        f = os.path.join(dd, f"marcap-{y}.parquet")
        if not os.path.exists(f):
            subprocess.run(["curl", "-sSfL", "-o", f,
                            f"https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{y}.parquet"], check=False)
    parts = []
    for f in sorted(glob.glob(os.path.join(dd, "marcap-*.parquet"))):
        x = pd.read_parquet(f, columns=["Code", "Name", "Date", "Open", "High", "Low", "Close", "Volume", "Marcap", "Stocks", "ChangesRatio", "MarketId"])
        parts.append(x[x.MarketId.isin(["STK", "KSQ"])])
    d = pd.concat(parts)
    d["Date"] = pd.to_datetime(d.Date); d["Code"] = d.Code.astype(str).str.zfill(6)
    d = d[d.Close > 0].drop_duplicates(["Code", "Date"], keep="last").sort_values(["Code", "Date"])
    # 수정주가(2026-11-08 kr_adjust): 10-31 보정은 '같은 날 주식수 변화'만 잡아 무상증자(주식수 반영 지연)를 놓쳤다
    #   — 메가스터디 2018-06-18 원가격 −68.5%(KRX 등락률 −6.48%)가 '래칫 손절 −64.7%'로 기록되던 것. KRX 등락률 기준으로 바꾼다.
    import kr_adjust
    d = d.reset_index(drop=True)
    d["_f"] = kr_adjust.factor(d).values
    for k in ("Open", "High", "Low", "Close"):
        d[k] = d[k] / d["_f"]
    d["Volume"] = d["Volume"] * d["_f"]
    d["week"] = d.Date - pd.to_timedelta(d.Date.dt.weekday, unit="D")      # 월요일 라벨
    w = d.groupby(["Code", "week"]).agg(name=("Name", "last"), open=("Open", "first"), high=("High", "max"), low=("Low", "min"),
                                        close=("Close", "last"), volume=("Volume", "sum"), marcap=("Marcap", "last"),
                                        mid=("MarketId", "last"), last_day=("Date", "last")).reset_index()
    w = w.rename(columns={"Code": "sym", "week": "date"})
    w = _keep_once_in(w, 5e10)
    # 2026-11-08 정답 점검 — 수정주가가 깨지면 빌드 실패(메가스터디 무상증자·삼성 50:1 분할·에코프로 5:1 분할 주에 −30% 넘는 가짜 폭락이 없어야)
    for s_, a_, b_ in (("072870", "2018-06-11", "2018-06-18"), ("005930", "2018-04-23", "2018-05-07"), ("086520", "2024-04-15", "2024-04-29")):
        x_ = w[(w.sym == s_) & (w.date >= pd.Timestamp(a_)) & (w.date <= pd.Timestamp(b_))].sort_values("date")
        if len(x_) >= 2 and float(x_.close.iloc[-1] / x_.close.iloc[0]) < 0.7:
            raise SystemExit(f"[KR] 수정주가 정답 점검 실패: {s_} {a_}~{b_} {x_.close.iloc[0]:,.0f} → {x_.close.iloc[-1]:,.0f}")
    # 재무: 공시일 없음 → 분기말 + 45일(4분기 90일)에 알게 된 것으로
    q = pd.read_parquet(os.path.join(ROOT, "data", "kr_fundamentals_q.parquet"))
    q["sym"] = q.sym.astype(str).str.zfill(6)
    q["end"] = pd.to_datetime(q.year.astype(int).astype(str) + "-" + (q.q.astype(int) * 3).astype(str) + "-01") + pd.offsets.MonthEnd(0)
    # 2026-11-05: 실제 DART 제출일(다음 날)부터 — 없으면 분기말 +45일(4분기 90일) 가정
    from tools.kr_filing_dates import known as _known
    q["known"], _real = _known(q.sym, q.year, q.q)
    print(f"[KR] 재무 공시일: 실제 제출일 {_real.mean():.0%} · 가정 {1 - _real.mean():.0%}", flush=True)
    q = kr_quarterize(q)
    g = q.groupby("sym")
    for k in ("revenue", "op_income", "net_income"):
        q[f"ttm_{k}"] = g[k].transform(lambda s: s.rolling(4, min_periods=4).sum())
    q["rev_yoy"] = np.where(g.revenue.shift(4) > 0, (q.revenue / g.revenue.shift(4) - 1) * 100, np.nan)
    # 2026-11-22: 매출 QoQ — 열은 COLS 에 있었는데 한국은 계산을 안 해 0% 였다(미국만 91.5%).
    #   kr_quarterize 가 빠진 분기를 채워 둔 뒤라 shift(1) 이 '직전 분기'다(건너뛴 분기를 직전으로 오인하지 않는다).
    _r1 = g.revenue.shift(1)
    q["rev_qoq"] = np.where(_r1 > 0, (q.revenue / _r1 - 1) * 100, np.nan)
    o4 = g.op_income.shift(4)
    q["op_yoy"] = np.where(o4 > 0, (q.op_income / o4 - 1) * 100, np.nan)
    q["op_turn"] = ((q.op_income > 0) & (o4 <= 0)).astype(int)
    q["acc"] = kr_acc(q)                       # 2026-11-07: 한국도 이익가속(대시보드 leaders_accel 과 같은 정의)
    q["oi_g"] = kr_oi_g(q)                     # 2026-11-08: 이익 개선폭(%p of 매출) — 적자 축소·흑자전환·급증
    q["opm"] = (q.ttm_op_income / q.ttm_revenue * 100).where(q.ttm_revenue > 0)
    q["debt"] = (q.liabilities / q.equity * 100).where(q.equity > 0)
    q = q[q._orig & q.known.notna()]
    q = q[["sym", "known", "ttm_revenue", "ttm_net_income", "equity", "rev_yoy", "rev_qoq", "op_yoy",
           "op_turn", "acc", "oi_g", "opm", "debt"]].sort_values("known")
    w = w.sort_values("date")
    w = pd.merge_asof(w, q, left_on="date", right_on="known", by="sym", direction="backward")
    w["per"] = (w.marcap / w.ttm_net_income).where(w.ttm_net_income > 0)
    w["pbr"] = (w.marcap / w.equity).where(w.equity > 0)
    w["psr"] = (w.marcap / w.ttm_revenue).where(w.ttm_revenue > 0)
    w["roe"] = (w.ttm_net_income / w.equity * 100).where(w.equity > 0)
    # 2026-11-05: 'KR' 대신 그 주의 소속 시장 — 퀀트 엔진 지수 게이트를 실전 규칙처럼 소속 시장별로(코스닥 종목 = 코스닥 5주선)
    w["market"] = w.pop("mid").map({"STK": "KOSPI", "KSQ": "KOSDAQ"}).fillna("KR")
    w["acc"] = w["acc"].fillna(0).astype(int)
    try:
        sec = json.load(open(os.path.join(ROOT, "data", "sectors.json"), encoding="utf-8"))
    except Exception:
        sec = {}
    w["sector"] = w.sym.map(sec)
    print(f"[KR] {w.date.min().date()}~{w.date.max().date()} · {w.sym.nunique():,}종 · {len(w):,}행")
    return _f32(w)


def kr_quarterize(q: pd.DataFrame) -> pd.DataFrame:
    """2026-11-16 패널 정합 — 두 가지를 고친다(v1.9 한국 백테스트가 둘 다에 걸려 있었다).
    ① 파일의 q=4 는 **연간 합계**다(dashboard·leader_anatomy 는 변환하는데 패널만 안 했다) → 손익 3열을 연간 − (1~3Q) 로.
       1~3Q 가 하나라도 없으면 빈값. 잔액(자산·부채·자본)은 기말이라 그대로.
    ② shift(4)·rolling(4) 는 '행 4개 전'이라 분기가 빠진 종목은 엉뚱한 분기와 비교했다(행의 5~13%).
       → 종목마다 분기를 빈칸 없이 펼친 뒤 계산하고, 원래 없던 분기는 마지막에 빼도록 _real 표시."""
    q = q.copy()
    flow = [c for c in ("revenue", "op_income", "net_income") if c in q.columns]
    s3 = q[q.q < 4].groupby(["sym", "year"])[flow].agg(["sum", "count"])
    m = q.q == 4
    k = pd.MultiIndex.from_arrays([q.loc[m, "sym"], q.loc[m, "year"]])
    for c in flow:
        sm_, ct_ = s3[(c, "sum")].reindex(k).values, s3[(c, "count")].reindex(k).values
        q.loc[m, c] = np.where(ct_ == 3, q.loc[m, c].values - sm_, np.nan)
    q["pi"] = q.year.astype(int) * 4 + q.q.astype(int) - 1
    rng = q.groupby("sym").pi.agg(["min", "max"])
    full = pd.DataFrame([(s, p) for s, a, b in zip(rng.index, rng["min"], rng["max"]) for p in range(a, b + 1)], columns=["sym", "pi"])
    q = full.merge(q.assign(_orig=True), on=["sym", "pi"], how="left")
    q["_orig"] = q["_orig"].eq(True)
    return q.sort_values(["sym", "pi"]).reset_index(drop=True)


KR_MIN_QREV = 1e10    # 분기 매출 100억원 — 이 아래는 이익가속이 발산(미국 $10M 과 같은 취지)
MAX_OIA = 10.0


def kr_oi_g(q: pd.DataFrame) -> pd.Series:
    """이익 개선폭(%p) = (영업익 − 전년 같은 분기 영업익) ÷ |매출| × 100. 적자 축소·흑자전환·이익 증가가 모두 + 로 같은 자로 잰다
    (차니 2026-11-08: '적자 대폭 감소 · 이익 폭증 · 흑자전환' 셋 다 이익 개선). 분기 매출 100억원 미만은 빈값."""
    o4 = q.groupby("sym").op_income.shift(4)
    rev = q.revenue.where(q.revenue.abs() >= KR_MIN_QREV)
    return ((q.op_income - o4) / rev.abs() * 100).replace([np.inf, -np.inf], np.nan)


def kr_acc(q: pd.DataFrame) -> pd.Series:
    """한국 이익가속(0/1) — leaders_accel.py 와 같은 정의(2026-11-07, 실전 v1.8 후보 '이익가속 OR 흑자전환' 검증용).
    q: sym·분기 순으로 정렬된 분기표(revenue, op_income). 매출 성장률·이익 성장률(영업익 증가 ÷ |매출|)이 직전 분기보다 둘 다 빨라짐."""
    g = q.groupby("sym")
    r4, o4 = g.revenue.shift(4), g.op_income.shift(4)
    rv = pd.Series(np.where(r4 > 0, (q.revenue / r4 - 1) * 100, np.nan), index=q.index)
    rev = q.revenue.where(q.revenue.abs() >= KR_MIN_QREV)
    oi = ((q.op_income - o4) / rev.abs()).replace([np.inf, -np.inf], np.nan)
    rv_a = rv - rv.groupby(q.sym).shift(1)
    oi_a = oi - oi.groupby(q.sym).shift(1)
    return ((rv_a > 0) & (oi_a > 0) & (oi_a.abs() <= MAX_OIA)).astype(int)


def main(markets=("US", "KR")):
    info = {}
    for m, fn in (("US", us), ("KR", kr)):
        if m not in markets:
            continue
        try:
            d = fn()
            report_coverage(d, m)          # MUST 열이 0% 면 여기서 SystemExit — 빈 패널을 올리지 않는다
            d.to_parquet(os.path.join(OUT, f"quant_panel_{m}.parquet"), index=False, compression="zstd")
            info[m] = dict(rows=int(len(d)), syms=int(d.sym.nunique()), start=str(d.date.min().date()), end=str(d.date.max().date()),
                           cap_nan_rows=int(d.marcap.isna().sum()),
                           cover={c: round(float(d[c].notna().mean() * 100), 2) for c in COLS
                                  if c not in ("sym", "name", "market", "date")},
                           first_week=coverage(d, ("NVDA", "PLTR", "TSLA") if m == "US" else ("005930", "086520", "247540")))
            if m == "US" and SEAM:
                info[m]["seam"] = dict(SEAM)
        except Exception as e:
            info[m] = dict(error=f"{type(e).__name__}: {e}")
            print(f"[{m}] 실패: {e}")
            if os.environ.get("GITHUB_ACTIONS"):
                print(f"::error title=패널 {m} 빌드 실패::{type(e).__name__}: {str(e)[:500]}", flush=True)
    info["asof"] = str(pd.Timestamp.today().date())
    json.dump(info, open(os.path.join(OUT, "quant_panel_info.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(info)


if __name__ == "__main__":
    main(tuple(sys.argv[1:]) or ("US", "KR"))
