# -*- coding: utf-8 -*-
"""최근 5년 상승률 TOP 300 역분석 — 필요조건 → 충분조건 → '언제 꽉 쥐나' (2026-10-28, 차니 설계)

질문(차니): 승자들이 공통으로 가졌던 것(필요조건)을 찾고, 그게 승자를 미리 가려내는지(충분조건)를 따로 본다.
           그러면 급등이 '언제' 오는지, 생로병사에서 '언제 꽉 쥐고 있어야' 하는지 알 수 있다.

시장: 미국(market.db factor_weekly v13y, SEC 공시일 기준 재무) · 한국(FinanceData/marcap 일별 — 상장폐지 포함, 분기 재무는
      data/kr_fundamentals_q.parquet 에 공시일이 없어 '분기말 + 45일(4분기 90일)'에 알게 된 것으로 둔다)
창: 최근 5년(마지막 주 기준 260주). 시작 주에 유동성 통과(미국 시총 $0.3B·거래대금 $5M / 한국 시총 1,000억·거래대금 10억)인 종목만.
승자 = 창 전체 수익률 상위 300(상폐 종목은 마지막 가격 → 자연히 하위).
점화 시점 t0 = 창 안에서 '가장 큰 상승'(저점→고점, 로그 상승폭 최대)의 저점 주.

1) 필요조건: 각 특징이 승자에게 t0 시점(그리고 t0 ±13주 안)에 있었던 비율
2) 충분조건: 창 안 모든 종목·주(유동성 통과)에서 그 특징이 있을 때 '이후 52주 2배 이상' 확률 ÷ 전체 확률(리프트), 이후 52주 중앙
   → 필요조건 비율 ÷ 평소 보유 비율 = 리프트(베이즈). 필요조건이 높아도 평소에 흔하면 리프트 ≈ 1 = 쓸모없음.
   + 특징 두 개 조합 상위(표본 500 이상)
3) 매크로: 점화 주의 국면 분포 vs 창 전체 주의 국면 분포(국면 = 하이일드 스프레드 26주 변화·기준금리 26주 변화·SPY 40주선·VIX)
4) 언제 꽉 쥐나: 점화 후 상승분이 몇 주차에 몰리나(13주 단위 몫) · 상승 도중 최대 낙폭(중앙·상위 25%) ·
   고점 대비 -20/-25/-30% 손절이 상승 도중 몇 %의 승자를 털어냈나 · 점화→고점 기간
결과: results/winners_reverse.json
"""
import os, sys, json, time, glob, subprocess
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
OUT = os.path.join(ROOT, "results", "winners_reverse.json")
WIN = 260
TOP = 300


# ── 공통 분석 ──────────────────────────────────────────────────────────
def stage_of(px):
    ma30 = px.rolling(30, min_periods=24).mean()
    slope = ma30 / ma30.shift(4) - 1
    st2 = (px > ma30) & (slope > 0)
    st4 = (px < ma30) & (slope < 0)
    mid = ~(st2 | st4) & ma30.notna()
    prior2 = st2.astype(float).rolling(52, min_periods=26).mean()
    return st2, st4, mid & (prior2 < 0.5), mid & (prior2 >= 0.5)      # 2, 4, 1(바닥), 3(천장)


def rs_rank(px, liq):
    r = {k: px / px.shift(k) - 1 for k in (13, 26, 39, 52)}
    sc = (0.4 * r[13] + 0.2 * r[26] + 0.2 * r[39] + 0.2 * r[52]).where(liq)
    return sc.rank(axis=1, pct=True) * 99


def macro_regimes(idx, spy):
    m = pd.read_parquet(os.path.join(ROOT, "data", "macro_hist.parquet"))
    m = m.reindex(idx.union(m.index)).ffill().reindex(idx)
    spw = spy.reindex(idx).ffill()
    hy = m["BAMLH0A0HYM2"]; ff = m["FEDFUNDS"]; vix = m["VIXCLS"]
    return {
        "하이일드 스프레드 26주 축소": hy - hy.shift(26) < 0,
        "하이일드 스프레드 26주 확대": hy - hy.shift(26) > 0,
        "기준금리 26주 인하": ff - ff.shift(26) < -0.1,
        "기준금리 26주 인상": ff - ff.shift(26) > 0.1,
        "SPY 40주선 위": spw > spw.rolling(40, min_periods=30).mean(),
        "VIX 25 이상": vix >= 25,
    }


def analyze(px, liq, feats, macro, label):
    idx = px.index
    end = len(idx) - 1
    start = max(0, end - WIN)
    p0, p1 = px.iloc[start], px.ffill().iloc[end]
    elig = liq.iloc[start] & p0.notna()
    tot = (p1 / p0 - 1)[elig].dropna()
    win = tot.sort_values(ascending=False).head(TOP)
    P = px.values
    cols = list(px.columns)
    rows = []
    for s, g in win.items():
        j = cols.index(s)
        v = P[start:end + 1, j]
        ok = ~np.isnan(v)
        if ok.sum() < 30:
            continue
        lv = np.log(np.where(ok, v, np.nan))
        best, bi, bj, mn, mi = -1, 0, 0, np.inf, 0
        for t in range(len(lv)):
            if np.isnan(lv[t]):
                continue
            if lv[t] < mn:
                mn, mi = lv[t], t
            if lv[t] - mn > best:
                best, bi, bj = lv[t] - mn, mi, t
        t0, tp = start + bi, start + bj
        seg = P[t0:tp + 1, j]
        seg = pd.Series(seg).ffill().values
        run_dd = float(np.min(seg / np.maximum.accumulate(seg) - 1)) * 100
        lg = np.log(seg[-1] / seg[0])
        shares = []
        for q in range(0, 104, 13):
            a, b = min(q, len(seg) - 1), min(q + 13, len(seg) - 1)
            shares.append(float(np.log(seg[b] / seg[a]) / lg * 100) if lg > 0 else 0.0)
        stops = {}
        for x in (20, 25, 30, 40):
            pk = seg[0]; hit = False
            for c in seg[1:]:
                pk = max(pk, c)
                if c / pk - 1 <= -x / 100 and c < seg[-1]:
                    hit = True; break
            stops[str(x)] = hit
        rec = dict(sym=s, total=round(float(g) * 100, 1), t0=str(idx[t0].date()), peak=str(idx[tp].date()),
                   run_gain=round(float(np.exp(best) - 1) * 100, 1), run_wk=int(tp - t0), run_dd=round(run_dd, 1),
                   shares=[round(z, 1) for z in shares], stopped=stops)
        for fk, F in feats.items():
            fv = F.values[:, j]
            rec[f"at:{fk}"] = bool(fv[t0]) if t0 < len(fv) else False
            rec[f"near:{fk}"] = bool(np.nanmax(fv[max(0, t0 - 13):t0 + 14])) if t0 < len(fv) else False
        for mk, Mv in macro.items():
            rec[f"m:{mk}"] = bool(Mv.iloc[t0]) if t0 < len(Mv) and Mv.iloc[t0] == Mv.iloc[t0] else False
        rows.append(rec)
    W = pd.DataFrame(rows)
    # 충분조건: 창 안 모든 유동성 통과 종목·주, 이후 52주
    fwd = px.shift(-52) / px - 1
    rng_ = slice(idx[start], idx[max(start, end - 52)])
    L = liq.loc[rng_]
    Fw = fwd.loc[rng_].where(L)
    base_n = int(Fw.notna().values.sum())
    base_p2 = float((Fw >= 1).values.sum()) / max(1, base_n)
    base_med = float(np.nanmedian(Fw.values))
    feat_tab = []
    for fk, F in feats.items():
        Fm = F.loc[rng_].fillna(False).astype(bool) & L
        x = Fw.values[Fm.values]
        x = x[~np.isnan(x)]
        prev = float(Fm.values.sum()) / max(1, float(L.values.sum()))
        feat_tab.append(dict(feat=fk, need_at=round(float(W[f"at:{fk}"].mean()) * 100, 1),
                             need_near=round(float(W[f"near:{fk}"].mean()) * 100, 1),
                             prevalence=round(prev * 100, 1), n=int(len(x)),
                             p2x=round(float((x >= 1).mean()) * 100, 2) if len(x) else None,
                             lift=round(float((x >= 1).mean()) / base_p2, 2) if len(x) and base_p2 else None,
                             med52=round(float(np.median(x)) * 100, 1) if len(x) else None))
    combos = []
    keys = list(feats)
    for a in range(len(keys)):
        for b in range(a + 1, len(keys)):
            Fm = (feats[keys[a]] & feats[keys[b]]).loc[rng_].fillna(False).astype(bool) & L
            x = Fw.values[Fm.values]; x = x[~np.isnan(x)]
            if len(x) < 500:
                continue
            need = float((W[f"near:{keys[a]}"] & W[f"near:{keys[b]}"]).mean())
            combos.append(dict(feat=f"{keys[a]} + {keys[b]}", n=int(len(x)), need_near=round(need * 100, 1),
                               p2x=round(float((x >= 1).mean()) * 100, 2), lift=round(float((x >= 1).mean()) / base_p2, 2),
                               med52=round(float(np.median(x)) * 100, 1)))
    combos = sorted(combos, key=lambda r: -r["lift"])[:15]
    mac = []
    for mk, Mv in macro.items():
        allw = Mv.iloc[start:end + 1].dropna()
        mac.append(dict(regime=mk, at_ignition=round(float(W[f"m:{mk}"].mean()) * 100, 1),
                        all_weeks=round(float(allw.astype(float).mean()) * 100, 1)))
    sh = np.array(W.shares.tolist())
    hold = dict(run_wk=dict(median=float(W.run_wk.median()), p25=float(W.run_wk.quantile(.25)), p75=float(W.run_wk.quantile(.75))),
                run_gain_median=float(W.run_gain.median()),
                run_dd=dict(median=float(W.run_dd.median()), p25=float(W.run_dd.quantile(.25)), worst10=float(W.run_dd.quantile(.1))),
                share_by_13w=[round(float(np.median(sh[:, k])), 1) for k in range(sh.shape[1])],
                share_by_13w_mean=[round(float(np.mean(sh[:, k])), 1) for k in range(sh.shape[1])],
                stopped_out={k: round(float(np.mean([r[k] for r in W.stopped])) * 100, 1) for k in ("20", "25", "30", "40")})
    t0m = pd.to_datetime(W.t0).dt.to_period("Q").astype(str).value_counts().sort_index()
    return dict(label=label, window=[str(idx[start].date()), str(idx[end].date())], eligible=int(elig.sum()), n_winners=len(W),
                winner_total_median=float(W.total.median()), base_p2x=round(base_p2 * 100, 2), base_med52=round(base_med * 100, 1),
                features=sorted(feat_tab, key=lambda r: -(r["lift"] or 0)), combos=combos, macro=mac, hold=hold,
                ignition_by_q=t0m.to_dict(), winners=W[["sym", "total", "t0", "peak", "run_gain", "run_wk", "run_dd"]].to_dict("records"))


# ── 미국 ───────────────────────────────────────────────────────────────
def us():
    os.environ.setdefault("FACTOR_VER", "v13y")
    import portfolio_rules_sim as S
    import rs_accel_bt as B
    A = S.A
    px, _, spy, _, _ = S.load()
    d = A.load()
    M = A.matrices(d, ["adv_20d", "marcap", "ACC", "rev_yoy", "dopm", "dist_52w"])
    liq = ((M["adv_20d"] >= A.MIN_ADV) & (M["marcap"] >= A.MIN_MC)).fillna(False)
    rs = rs_rank(px, liq)
    st2, st4, st1, st3 = stage_of(px)
    acc = (M["ACC"] == 1).fillna(False)
    ta = B.turnaround(d, px)
    roll = lambda F: F.astype(float).rolling(13, min_periods=1).max() > 0
    dist = px / px.rolling(52, min_periods=40).max() - 1
    feats = {
        "이익가속(13주 내)": roll(acc), "영업이익 흑자전환(13주 내)": roll(ta), "RS 80 이상": rs >= 80, "RS 50 미만": rs < 50,
        "2단계(30주선 위·상승)": st2, "1단계(바닥 횡보)": st1, "4단계(하락)": st4,
        "52주 고점 -10% 이내": dist >= -0.10, "52주 고점 -40% 이하": dist <= -0.40,
        "매출 YoY 20%+": M["rev_yoy"] >= 20, "영업이익률 개선(QoQ)": M["dopm"] > 0,
        "시총 $2B 미만": M["marcap"] < 2e9,
    }
    feats = {k: v.fillna(False).astype(bool) for k, v in feats.items()}
    return analyze(px, liq, feats, macro_regimes(px.index, spy), "미국")


# ── 한국 ───────────────────────────────────────────────────────────────
def kr():
    dd = os.path.join(ROOT, "data", "research", "marcap")
    os.makedirs(dd, exist_ok=True)
    yr = pd.Timestamp.today().year
    for y in range(yr - 6, yr + 1):
        f = os.path.join(dd, f"marcap-{y}.parquet")
        if not os.path.exists(f):
            subprocess.run(["curl", "-sSfL", "-o", f,
                            f"https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{y}.parquet"], check=False)
    parts = []
    for f in sorted(glob.glob(os.path.join(dd, "marcap-*.parquet"))):
        try:
            x = pd.read_parquet(f, columns=["Code", "Date", "Close", "Amount", "Marcap", "Market", "MarketId"])
        except Exception:
            x = pd.read_parquet(f)
            x = x[[c for c in ("Code", "Date", "Close", "Amount", "Marcap", "Market", "MarketId") if c in x.columns]]
        parts.append(x)
    if not parts:
        raise RuntimeError("marcap 파일을 못 받았다")
    d = pd.concat(parts)
    if "MarketId" in d.columns:
        d = d[d.MarketId.isin(["STK", "KSQ"])]                            # 코넥스 제외(코스닥 글로벌은 KSQ)
    else:
        d = d[d.Market.isin(["KOSPI", "KOSDAQ", "KOSDAQ GLOBAL"])]
    d["Date"] = pd.to_datetime(d.Date); d["Code"] = d.Code.astype(str).str.zfill(6)
    d = d[d.Close > 0].drop_duplicates(["Code", "Date"], keep="last")
    C = d.pivot(index="Date", columns="Code", values="Close")
    Am = d.pivot(index="Date", columns="Code", values="Amount").rolling(20, min_periods=15).mean()
    Mc = d.pivot(index="Date", columns="Code", values="Marcap")
    W = lambda z: z.resample("W-FRI").last()
    px, adv, mc = W(C), W(Am), W(Mc)
    px.index = px.index - pd.Timedelta(days=4); adv.index = px.index; mc.index = px.index
    # 상폐: 마지막 거래 이후 NaN 유지(ffill 안 함)
    last = C.apply(lambda s: s.last_valid_index())
    for c in px.columns:
        lv = last.get(c)
        if lv is not None:
            px.loc[px.index > lv, c] = np.nan
    liq = ((mc >= 1e11) & (adv >= 1e9)).fillna(False)
    rs = rs_rank(px, liq)
    st2, st4, st1, st3 = stage_of(px)
    q = pd.read_parquet(os.path.join(ROOT, "data", "kr_fundamentals_q.parquet"))
    q["sym"] = q.sym.astype(str).str.zfill(6)
    q = q.sort_values(["sym", "year", "q"])
    q["pe"] = pd.to_datetime(q.year.astype(str) + "-" + (q.q * 3).astype(str) + "-01") + pd.offsets.MonthEnd(0)
    q["avail"] = q.pe + pd.to_timedelta(np.where(q.q == 4, 90, 45), unit="D")
    g = q.groupby("sym")
    q["rev_yoy"] = (q.revenue / g.revenue.shift(4) - 1) * 100
    q.loc[g.revenue.shift(4) <= 0, "rev_yoy"] = np.nan
    q["oi_g"] = (q.op_income - g.op_income.shift(4)) / q.revenue.abs()
    g = q.groupby("sym")
    q["ACC"] = ((q.rev_yoy - g.rev_yoy.shift(1) > 0) & (q.oi_g - g.oi_g.shift(1) > 0)).astype(float)
    q["TA"] = ((q.op_income > 0) & (g.op_income.shift(4) <= 0)).astype(float)
    q["opm"] = q.op_income / q.revenue * 100
    q["dopm"] = q.opm - g.opm.shift(1)

    def asof(col):
        z = q.pivot_table(index="avail", columns="sym", values=col, aggfunc="last").sort_index()
        z = z.reindex(z.index.union(px.index)).ffill().reindex(px.index)
        return z.reindex(columns=px.columns)
    accm, tam = asof("ACC"), asof("TA")
    # '그 주에 새로 알려진 분기' 표시: 공시 가정일이 속한 첫 주
    newq = pd.DataFrame(False, index=px.index, columns=px.columns)
    pos = {c: i for i, c in enumerate(px.columns)}
    NV = newq.values
    for s_, av in zip(q.sym, q.avail):
        j = pos.get(s_)
        if j is None:
            continue
        i = int(np.searchsorted(px.index.values, np.datetime64(av)))
        if i < len(px.index):
            NV[i, j] = True
    newq = pd.DataFrame(NV, index=px.index, columns=px.columns)
    roll = lambda F: (F & newq).astype(float).rolling(13, min_periods=1).max() > 0
    dist = px / px.rolling(52, min_periods=40).max() - 1
    feats = {
        "이익가속(13주 내)": roll(accm == 1), "영업이익 흑자전환(13주 내)": roll(tam == 1), "RS 80 이상": rs >= 80, "RS 50 미만": rs < 50,
        "2단계(30주선 위·상승)": st2, "1단계(바닥 횡보)": st1, "4단계(하락)": st4,
        "52주 고점 -10% 이내": dist >= -0.10, "52주 고점 -40% 이하": dist <= -0.40,
        "매출 YoY 20%+": asof("rev_yoy") >= 20, "영업이익률 개선(QoQ)": asof("dopm") > 0,
        "시총 3,000억 미만": mc < 3e11,
    }
    feats = {k: v.fillna(False).astype(bool) for k, v in feats.items()}
    spy = None
    try:
        import portfolio_rules_sim as S
        spy = S.load_spy(px.index)
    except Exception:
        pass
    macro = macro_regimes(px.index, spy if spy is not None else pd.Series(np.nan, index=px.index))
    ks = d.groupby("Date").Marcap.sum().resample("W-FRI").last()          # 시총 합 = 한국 시장 대리
    ks.index = ks.index - pd.Timedelta(days=4)
    ks = ks.reindex(px.index)
    macro["한국 시총합 40주선 위"] = ks > ks.rolling(40, min_periods=30).mean()
    res = analyze(px, liq, feats, macro, "한국")
    res["note"] = "한국 재무는 공시일 미보유 → 분기말 +45일(4분기 +90일)에 알게 된 것으로 가정 · 시세 FinanceData/marcap(상폐 포함)"
    return res


def main():
    t0 = time.time()
    out = dict(run=time.strftime("%Y-%m-%d %H:%M"), top=TOP, window_weeks=WIN, markets={})
    for nm, fn in (("US", us), ("KR", kr)):
        try:
            out["markets"][nm] = fn()
            m = out["markets"][nm]
            print(nm, m["window"], m["n_winners"], "기저 2배확률", m["base_p2x"], flush=True)
            for r in m["features"]:
                print("  ", r, flush=True)
        except Exception as e:
            import traceback
            out["markets"][nm] = dict(error=str(e)[:300])
            print(traceback.format_exc(), flush=True)
            print(f"::warning title=역분석 {nm} 실패::{str(e)[:200]}")
    out["secs"] = round(time.time() - t0)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print("::notice title=TOP300 역분석::" + " · ".join(
        f"{k} 승자 {v.get('n_winners')} 기저 2배 {v.get('base_p2x')}% 최고 리프트 "
        f"{(v.get('features') or [{}])[0].get('feat')} {(v.get('features') or [{}])[0].get('lift')}" for k, v in out["markets"].items()
        if 'error' not in v) + f" · {out['secs']}초")


if __name__ == "__main__":
    main()
