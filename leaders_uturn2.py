# -*- coding: utf-8 -*-
"""
주도주 탈출 타이밍 연구 (2단계) — 실제 진입 표본에서 'U턴 vs 눌림목' 판별

1단계(leaders_uturn.py)의 '상승중 낙폭은 100% 회복'은 동어반복이었다(정점 전이라
라벨한 이상 정의상 회복한다). 그래서 표본을 **규칙 L/S 가 실제로 낸 신호**로 바꾼다.
사후에 승자를 골라 오지 않으므로 look-ahead 가 없다.

절차
  ① L·S 신호 주차마다 가상 진입(슬롯 무시 — 표본을 살리려고 전 신호를 센다)
  ② 청산 없이 156주 추적, 진입 후 최고가 대비 낙폭 이벤트를 잡는다
  ③ 낙폭이 -TRIG 를 처음 깬 주 = '판단의 순간'. 그 주에 **알 수 있는 값만** 기록
  ④ 결과: 그 시점 이후 26·52주 수익, 직전 고점 회복 여부

⚠️ 생존편향(상장폐지 부재)은 여기서도 그대로다 — 회복률은 과대, 손절가치는 과소.
⚠️ 이벤트는 (sym, 이벤트시작주)로 중복 제거하지만 종목·시기 클러스터링은 남는다.
"""
import os, sys, sqlite3
import numpy as np
import pandas as pd
import leaders_ab as AB

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "market.db")
pd.set_option("display.width", 260, "display.max_columns", 60)

HOLD_MAX = 156          # 추적 상한(주)
TRIG = 0.20             # 판단의 순간 = 고점 대비 -20% 최초 이탈
EXTRA = ["ma10", "op_pos_streak", "weeks_since_earn", "psr_pct5y", "vol_x_20w",
         "opm_qoq", "days_since_hi52", "mdd_52w", "rev_qoq", "earn_react_w0"]


CACHE = os.path.join(BASE, "data", "_uturn_panel.parquet")
COLS = ["close", "ret_1w", "adv_20d", "marcap", "F_HI8", "F_OPM", "op_turn",
        "rs_13w", "rs_26w", "dist_52w", "psr", "opm", "ma20", "ma10", "vw",
        "rev_yoy"] + EXTRA


def panel():
    """캐시된 판넬(1회 생성: leaders_uturn2.build_cache) → 피벗 행렬"""
    d = pd.read_parquet(CACHE)
    M = {k: d.pivot(index="as_of", columns="sym", values=k).sort_index()
         for k in dict.fromkeys(COLS)}
    spy = pd.read_csv(os.path.join(BASE, "data", "leaders_cache", "px_SPY.csv"),
                      index_col=0, parse_dates=True)["Close"]
    spy = spy.reindex(M["close"].index, method="ffill")
    return M, spy


def collect(M, spy, key, trig=TRIG):
    """전부 넘파이로 — 판다스 .get 을 루프 안에서 부르면 분 단위로 느려진다."""
    px = M["close"]
    g = AB.gate_of(M, key).reindex_like(px).fillna(False)
    idx, syms = px.index, list(px.columns)
    col = {s: j for j, s in enumerate(syms)}
    A = {k: M[k].reindex_like(px).values for k in M}
    V = A["close"]
    spy_dd = (spy / spy.rolling(52, min_periods=8).max() - 1).values
    spy_r4 = spy.pct_change(4).values
    seen, rows = set(), []
    gi, gj = np.where(g.values)
    for i0, jc in zip(gi, gj):
        s = syms[jc]
        v = V[:, jc]
        if not (v[i0] == v[i0] and v[i0] > 0):
            continue
        peak, pk_i, armed = v[i0], i0, True
        for k in range(i0 + 1, min(len(idx), i0 + HOLD_MAX + 1)):
            x = v[k]
            if x != x:
                continue
            if x > peak:
                peak, pk_i, armed = x, k, True
                continue
            if not armed or x / peak - 1 > -trig:
                continue
            armed = False                      # 이 고점에 대해 한 번만 기록
            if (s, idx[k]) in seen:
                break
            seen.add((s, idx[k]))
            fw = lambda h: (v[k + h] / x - 1) if k + h < len(v) and v[k + h] == v[k + h] else np.nan
            nxt = v[k + 1:k + 1 + 52]
            nxt = nxt[~np.isnan(nxt)]
            f = lambda c: A[c][k, jc]
            rows.append(dict(
                rule=key, sym=s, t_ent=idx[i0], t=idx[k], wk_held=k - i0,
                px=x, ent=v[i0], peak=peak, wk_pk=k - pk_i,
                gain_ent=x / v[i0] - 1, pk_gain=peak / v[i0] - 1, dd=x / peak - 1,
                c_ma10=x / f("ma10") - 1, c_ma20=x / f("ma20") - 1,
                rs13=f("rs_13w"), rs26=f("rs_26w"), dist52=f("dist_52w"),
                vw=f("vw"), volx=f("vol_x_20w"), psr=f("psr"), psrp=f("psr_pct5y"),
                opm=f("opm"), opmq=f("opm_qoq"), opstk=f("op_pos_streak"),
                revq=f("rev_qoq"), revy=f("rev_yoy"), wse=f("weeks_since_earn"),
                react=f("earn_react_w0"), mcap=f("marcap"), mdd52=f("mdd_52w"),
                spy_dd=spy_dd[k], spy_r4=spy_r4[k],
                fwd13=fw(13), fwd26=fw(26), fwd52=fw(52),
                max52=(nxt.max() / x - 1) if len(nxt) else np.nan,
                min52=(nxt.min() / x - 1) if len(nxt) else np.nan,
                rec52=bool(len(nxt) and nxt.max() >= peak)))
            break                              # 진입당 첫 판단의 순간 1건만
    return pd.DataFrame(rows)


def build_cache():
    """data/_uturn_panel.parquet 재생성 (DB 갱신 후에만 필요)"""
    d = AB.load()
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    x = pd.read_sql(f"SELECT as_of,sym,{','.join(EXTRA)} FROM factor_weekly "
                    "WHERE factor_ver='v1'", c)
    c.close()
    x["as_of"] = pd.to_datetime(x.as_of)
    d.merge(x, on=["as_of", "sym"], how="left").to_parquet(CACHE)


def main():
    M, spy = panel()
    AB.assert_vol_fresh(M)
    out = []
    for key in ("L", "S"):
        E = collect(M, spy, key)
        out.append(E)
        n_sig = int(AB.gate_of(M, key).sum().sum())
        print(f"\n═══ 규칙 {key} ({AB.RULES[key]['name']}) ═══")
        print(f"  신호 {n_sig}건 → 고점 대비 -{TRIG:.0%} 도달 이벤트 {len(E)}건 "
              f"({len(E)/max(n_sig,1):.0%})")
        e = E.dropna(subset=["fwd52"])
        print(f"  [판단의 순간 이후] n={len(e)}  "
              f"52주 중앙 {e.fwd52.median():+.1%} · 평균 {e.fwd52.mean():+.1%} · "
              f"음수비율 {(e.fwd52<0).mean():.0%}")
        print(f"  26주 중앙 {e.fwd26.median():+.1%} · 13주 중앙 {e.fwd13.median():+.1%}")
        print(f"  직전 고점 52주내 회복 {e.rec52.mean():.1%} · "
              f"이후 추가 최대낙폭 중앙 {e.min52.median():+.1%} · 최대반등 중앙 {e.max52.median():+.1%}")
    A = pd.concat(out, ignore_index=True)
    A.to_parquet(os.path.join(BASE, "data", "_uturn_dec.parquet"))
    print(f"\n저장: data/_uturn_dec.parquet  ({len(A)}행)")


if __name__ == "__main__":
    main()
