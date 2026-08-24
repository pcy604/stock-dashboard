# -*- coding: utf-8 -*-
"""
주도주 탈출 (6단계) — 개별 종목 케이스: 트럭은 언제 U턴했나

1단계에서 잡은 런(저점→정점)을 종목별로 펼친다. 사후 서술이다 — 규칙이 아니다.
각 런에 대해 ① 상승중 견뎌야 했던 낙폭들 ② 정점 ③ 정점 이후 붕괴
④ 현행 -30% 트레일이 실제로 언제 잘랐을지, 정점에서 얼마나 늦게 잘랐는지.
"""
import os, sys
import numpy as np
import pandas as pd
import leaders_uturn2 as U2
from leaders_uturn import find_runs, episodes, DD_TRIG

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.abspath(__file__))
pd.set_option("display.width", 300, "display.max_columns", 60)

WATCH = ["NVDA", "TSLA", "AMD", "ENPH", "APP", "CVNA", "SMCI", "PLTR", "CELH",
         "VST", "MSTR", "COIN", "META", "AVGO", "ANET", "DKNG", "RIVN", "SOFI",
         "IONQ", "RKLB", "LLY", "NFLX", "CRWD", "TTD", "ONON", "HIMS", "AXON"]


def trail_exit(v, i0, iend, x):
    """i0 진입, 고점 대비 -x 최초 이탈 인덱스"""
    peak = v[i0]
    for k in range(i0, iend + 1):
        if v[k] != v[k]:
            continue
        peak = max(peak, v[k])
        if v[k] <= peak * (1 - x):
            return k
    return None


def ma_exit(v, ma, i0, iend, k=2):
    below = 0
    for j in range(i0, iend + 1):
        m = ma[j]
        below = below + 1 if (m == m and v[j] == v[j] and v[j] < m) else 0
        if below >= k:
            return j
    return None


def main():
    M, spy = U2.panel()
    px, ma20 = M["close"], M["ma20"]
    runs = find_runs(px)
    d = pd.read_parquet(os.path.join(BASE, "data", "_uturn_panel.parquet"),
                        columns=["sym", "name"]).drop_duplicates("sym").set_index("sym")
    rows = []
    for r in runs.itertuples():
        v = px[r.sym].dropna()
        idx = v.index
        a = v.values
        m = ma20[r.sym].reindex(idx).values
        i0, jpk = idx.get_loc(r.t0), idx.get_loc(r.tpk)
        iend = min(len(a) - 1, jpk + 104)
        eps = episodes(a, i0, jpk)                      # 상승 중 낙폭만
        deep = [e["deep"] for e in eps]
        ke = trail_exit(a, i0, iend, 0.30)
        km = ma_exit(a, m, i0, iend, 2)
        post = a[jpk:iend + 1]
        rows.append(dict(
            sym=r.sym, name=d.name.get(r.sym, ""),
            t0=r.t0.date(), tpk=r.tpk.date(), 배수=r.mult, 주수=r.weeks,
            n20=sum(1 for x in deep if x <= -0.20),
            n30=sum(1 for x in deep if x <= -0.30),
            최대견딤=min(deep) if deep else 0.0,
            정점후MDD=post.min() / a[jpk] - 1,
            트레일청산=idx[ke].date() if ke is not None else None,
            늦은주=(ke - jpk) if ke is not None else None,
            트레일수익=(a[ke] / a[i0] - 1) if ke is not None else None,
            이평청산=idx[km].date() if km is not None else None,
            이평늦은주=(km - jpk) if km is not None else None,
            이평수익=(a[km] / a[i0] - 1) if km is not None else None))
    C = pd.DataFrame(rows).set_index("sym")
    C.to_parquet(os.path.join(BASE, "data", "_uturn_cases.parquet"))

    fmt = dict(배수="{:.1f}x", 최대견딤="{:.0%}", 정점후MDD="{:.0%}",
               트레일수익="{:+.0%}", 이평수익="{:+.0%}")
    show = ["name", "t0", "tpk", "배수", "주수", "n20", "n30", "최대견딤", "정점후MDD",
            "트레일청산", "늦은주", "트레일수익", "이평청산", "이평늦은주", "이평수익"]
    W = C.reindex([s for s in WATCH if s in C.index])[show]
    print("═══ 눈에 익은 주도주들 — 런 해부 ═══")
    print("  n20/n30 = 정점까지 오르는 동안 겪은 -20%/-30% 낙폭 횟수")
    print("  늦은주   = 정점 대비 몇 주 뒤에 청산됐나 (트레일 -30% 기준)\n")
    print(W.to_string(formatters={k: v.format for k, v in fmt.items()}))

    print("\n═══ 배수 상위 20 (전 종목) ═══")
    print(C.nlargest(20, "배수")[show].to_string(
        formatters={k: v.format for k, v in fmt.items()}))

    print("\n═══ 요약 (런 %d개) ═══" % len(C))
    print(f"  상승중 -20% 낙폭 횟수: 중앙 {C.n20.median():.0f} · 평균 {C.n20.mean():.1f} · "
          f"0회인 런 {(C.n20==0).mean():.0%}")
    print(f"  상승중 -30% 낙폭 횟수: 중앙 {C.n30.median():.0f} · 0회인 런 {(C.n30==0).mean():.0%}")
    print(f"  최대 견딤 낙폭: 중앙 {C.최대견딤.median():.0%} · 25%분위 {C.최대견딤.quantile(.25):.0%}")
    print(f"  트레일 -30% 청산이 정점보다 늦은 주: 중앙 {C.늦은주.median():.0f}주")
    print(f"  20주선 2주 이탈 청산이 늦은 주: 중앙 {C.이평늦은주.median():.0f}주")
    both = C.dropna(subset=["트레일수익", "이평수익"])
    print(f"  같은 런에서 실현수익 중앙: 트레일 {both.트레일수익.median():+.0%} · "
          f"20주선 {both.이평수익.median():+.0%}  (n={len(both)})")
    print(f"  20주선이 더 나았던 비율: {(both.이평수익 > both.트레일수익).mean():.0%}")


if __name__ == "__main__":
    main()
