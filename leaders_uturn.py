# -*- coding: utf-8 -*-
"""
주도주 탈출 타이밍 연구 (1단계) — 낙폭 해부

질문: 주도주 한 마리를 끝까지 타려면 몇 번의 위기를 견뎌야 하고, 그 위기 중
      어떤 것이 '눌림목'이고 어떤 것이 'U턴(추세 종료)'인가.

정의
  런(run)   주봉 종가 기준. 직전 104주 최저점 대비 +150% 이상 오른 뒤,
            ±26주 구간의 최대값인 주차를 '정점'으로 본다. 종목당 상승배수가
            가장 큰 런 하나만 취한다.
            ⚠️ +26주 미래를 보는 사후 정의다. 서술(해부)에만 쓰고 규칙엔 안 쓴다.
  낙폭이벤트 런 시작 이후 진행 최고가 대비 -15% 를 처음 깬 주 ~ 그 최고가를
            다시 넘는 주. 깊이·소요주수·회복주수를 잰다.
  라벨      52주 안에 직전 최고가를 회복 → '눌림목', 아니면 'U턴'.

⚠️ 생존편향: 유니버스에 상장폐지 종목이 없다. 여기 숫자는 전부 '살아남은
   종목'의 것이라 낙폭은 얕게, 회복률은 높게 나온다.
⚠️ 주봉 종가만 있다 — 장중 낙폭은 이보다 깊다.
"""
import os, sys, sqlite3
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "market.db")
pd.set_option("display.width", 250, "display.max_columns", 50)

LOOKBACK = 104     # 런 시작점(저점)을 찾는 창
RUN_MIN = 1.50     # +150% = 주도주 정의(기존 연구와 동일)
PEAK_WIN = 26      # 정점 확인 창(±주)
DD_TRIG = 0.15     # 낙폭 이벤트 진입 문턱
REC_WIN = 52       # 회복 판정 창


def load():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    d = pd.read_sql("SELECT as_of,sym,name,sector,close,marcap,rs_13w,ma20,psr,"
                    "opm,op_income,op_turn,rev_yoy,dist_52w,adv_20d,period_end "
                    "FROM factor_weekly WHERE factor_ver='v1'", c)
    c.close()
    d["as_of"] = pd.to_datetime(d.as_of)
    px = d.pivot(index="as_of", columns="sym", values="close").sort_index()
    # 분할·데이터오류로 주간 100% 점프가 3회 이상인 종목 제외 (기존 파이프라인과 동일 위생)
    jump = px.pct_change().abs().gt(1.0).sum()
    bad = set(jump[jump >= 3].index)
    return d[~d.sym.isin(bad)].sort_values(["sym", "as_of"]).reset_index(drop=True)


def find_runs(px):
    """종목별 최대 런 1개. 반환: DataFrame(sym, t0, tpk, mult)"""
    rows = []
    for s in px.columns:
        v = px[s].dropna()
        if len(v) < 60:
            continue
        a = v.values
        n = len(a)
        # trough[j] = 직전 LOOKBACK 주 최저
        tr = pd.Series(a).rolling(LOOKBACK, min_periods=12).min().values
        gain = a / tr - 1
        # 정점 조건: ±PEAK_WIN 최대
        ser = pd.Series(a)
        loc_max = ser.rolling(2 * PEAK_WIN + 1, center=True, min_periods=1).max().values
        ok = (gain >= RUN_MIN) & (a >= loc_max * 0.999)
        idx = np.where(ok)[0]
        if len(idx) == 0:
            continue
        j = idx[np.argmax(gain[idx])]           # 상승배수 최대인 정점
        lo = max(0, j - LOOKBACK)
        i = lo + int(np.argmin(a[lo:j + 1]))    # 그 정점의 출발 저점
        rows.append(dict(sym=s, t0=v.index[i], tpk=v.index[j],
                         p0=a[i], ppk=a[j], mult=a[j] / a[i],
                         weeks=j - i))
    return pd.DataFrame(rows)


def episodes(v, i0, iend):
    """v: 종가 ndarray, [i0, iend] 구간의 낙폭 이벤트 목록"""
    out, peak, pk_i, in_dd = [], v[i0], i0, None
    for k in range(i0, iend + 1):
        x = v[k]
        if x > peak:
            if in_dd is not None:                     # 회복 완료
                in_dd.update(t_rec=k, recovered=True,
                             rec_wk=k - in_dd["t_lo"], dd_wk=k - in_dd["t_start"])
                out.append(in_dd); in_dd = None
            peak, pk_i = x, k
            continue
        dd = x / peak - 1
        if in_dd is None:
            if dd <= -DD_TRIG:
                in_dd = dict(t_start=k, t_peak=pk_i, peak=peak,
                             deep=dd, t_lo=k, recovered=False)
        else:
            if dd < in_dd["deep"]:
                in_dd["deep"], in_dd["t_lo"] = dd, k
    if in_dd is not None:
        in_dd.update(t_rec=None, rec_wk=None, dd_wk=iend - in_dd["t_start"])
        out.append(in_dd)
    return out


def main():
    d = load()
    px = d.pivot(index="as_of", columns="sym", values="close").sort_index()
    runs = find_runs(px)
    nm = d.drop_duplicates("sym").set_index("sym")[["name", "sector"]]
    runs = runs.join(nm, on="sym")
    print(f"[런 탐지] 종목 {px.shape[1]}종 중 +{RUN_MIN:.0%} 런 보유 = {len(runs)}종 "
          f"({len(runs)/px.shape[1]:.1%})")
    print(runs.mult.describe(percentiles=[.5, .75, .9, .95]).round(2).to_string())

    # ── 런 전체(시작~정점+104주)의 낙폭 이벤트 ──
    recs = []
    for r in runs.itertuples():
        v = px[r.sym].dropna()
        a = v.values
        i0 = v.index.get_loc(r.t0)
        jpk = v.index.get_loc(r.tpk)
        iend = min(len(a) - 1, jpk + 104)
        for e in episodes(a, i0, iend):
            recs.append(dict(sym=r.sym, name=r.name, mult=r.mult,
                             t_start=v.index[e["t_start"]],
                             phase="상승중" if e["t_start"] <= jpk else "정점후",
                             gain_at=a[e["t_start"]] / a[i0] - 1,
                             from_pk=a[e["t_start"]] / a[jpk] - 1,
                             deep=e["deep"], dd_wk=e["dd_wk"], rec_wk=e["rec_wk"],
                             recovered=bool(e["recovered"]),
                             wk_to_lo=e["t_lo"] - e["t_start"]))
    E = pd.DataFrame(recs)
    E.to_parquet(os.path.join(BASE, "data", "_uturn_ep.parquet"))
    runs.to_parquet(os.path.join(BASE, "data", "_uturn_runs.parquet"))

    print(f"\n[낙폭 이벤트] {len(E)}건 / 런 {len(runs)}개 = 런당 {len(E)/len(runs):.1f}회")
    print("\n── 런 '상승 구간'에서 견뎌야 했던 낙폭 (정점 전) ──")
    up = E[E.phase == "상승중"]
    cnt = up.groupby("sym").size()
    print(f"  런당 -15%+ 낙폭 횟수: 중앙 {cnt.median():.0f}회 · 평균 {cnt.mean():.1f}회 "
          f"· 최대 {cnt.max():.0f}회")
    for th in (0.15, 0.20, 0.25, 0.30, 0.40, 0.50):
        sub = up[up.deep <= -th]
        share = sub.sym.nunique() / len(runs)
        print(f"  {th:.0%} 이상 낙폭: {len(sub):4d}건 · 런의 {share:5.1%} 가 최소 1번 겪음 "
              f"· 그 중 회복 {sub.recovered.mean():.0%}")
    print(f"  회복 소요(주): 중앙 {up[up.recovered].rec_wk.median():.0f} · "
          f"저점까지 {up.wk_to_lo.median():.0f}주")
    print("\n── 정점 이후 ──")
    aft = E[E.phase == "정점후"]
    print(f"  정점 후 첫 -15% 이벤트가 회복된 비율: {aft.groupby('sym').first().recovered.mean():.1%}")
    print(runs.assign(dd_after=[
        (lambda v: (v.loc[r.tpk:].min() / r.ppk - 1))(px[r.sym].dropna())
        for r in runs.itertuples()]).dd_after.describe(
            percentiles=[.1, .25, .5, .75, .9]).round(3).to_string())


if __name__ == "__main__":
    main()
