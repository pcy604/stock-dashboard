# -*- coding: utf-8 -*-
"""
보고서 증빙용 파라미터 스펙트럼.
규칙⑥(RS13>1.5 & (흑자전환 OR 이익폭증) & OPM>0 · trail-20 · 8종목 12.5%)에서
파라미터를 하나씩만 바꿔가며 전기간 + 워크포워드 6분할을 측정한다.
"""
import numpy as np, pandas as pd
import leaders_boost as B, leaders_sim2 as L2

pd.set_option("display.width", 250)
d = B.build(); d["as_of"] = pd.to_datetime(d.as_of)
P, M = B.matrices(d)
S = L2.spy().reindex(P.index, method="nearest")

SPL = [("2021","2021-01-01","2021-12-31"),("2022","2022-01-01","2022-12-31"),
       ("2023","2023-01-01","2023-12-31"),("2024","2024-01-01","2024-12-31"),
       ("2025","2025-01-01","2025-12-31"),("2025H2~26","2025-07-01",None)]

def spy_cagr(a,b=None):
    s = S.loc[a:] if b is None else S.loc[a:b]
    y=(s.index[-1]-s.index[0]).days/365.25
    return ((s.iloc[-1]/s.iloc[0])**(1/y)-1)*100

# 기본값 — 하나씩만 바꾼다
BASE = dict(rs=1.5, earn="both", opm=0.0, marcap=2e9, adv=5e6, maxpos=8)

def make_sig(cfg):
    def sig(Mx, i, ent):
        ok = ((Mx["rs_13w"].iloc[i] > cfg["rs"]) &
              (Mx["adv_20d"].iloc[i] >= cfg["adv"]) &
              (Mx["marcap"].iloc[i] >= cfg["marcap"]))
        e = cfg["earn"]
        if e == "both":   sub = (Mx["op_turn"].iloc[i]==1) | (Mx["b_any"].iloc[i]==1)
        elif e == "turn": sub = (Mx["op_turn"].iloc[i]==1)
        elif e == "any":  sub = (Mx["b_any"].iloc[i]==1)
        elif e == "none": sub = None
        else:             sub = (Mx[e].iloc[i]==1)          # 개별 플래그
        if sub is not None: ok &= sub
        if cfg["opm"] is not None: ok &= (Mx["opm"].iloc[i] > cfg["opm"])
        return ok[ok.fillna(False)].index
    return sig

def measure(cfg, wf=True):
    B.signal = make_sig(cfg)
    c = dict(trail=.20, maxpos=cfg["maxpos"], weight=1.0/cfg["maxpos"],
             tiers=[1.0], ptrig="hi52", entry={})
    r = B.run(P, M, c)
    w = ""
    if wf:
        n=0
        for _,a,b in SPL:
            rr = B.run(P, M, c, start=a, end=b)
            if rr["CAGR"] > spy_cagr(pd.Timestamp(a), pd.Timestamp(b) if b else None): n+=1
        w = f"{n}/6"
    return dict(CAGR=round(r["CAGR"],1), MDD=round(r["MDD"],1), 회복=round(r["회복"],2),
                거래=r["거래수"], 승률=round(r["승률"],1),
                노출=round(r["평균노출"],1), WF=w)

def table(title, key, values, labels=None, wf=True):
    print("="*104); print(title); print("="*104)
    rows=[]
    for i,v in enumerate(values):
        cfg = {**BASE, key: v}
        lab = labels[i] if labels else str(v)
        m = measure(cfg, wf)
        rows.append(dict(설정=lab, **m))
    df = pd.DataFrame(rows)
    print(df.to_string(index=False)); print()
    return df

table("A. RS13 임계값 — 다른 조건 고정", "rs",
      [1.0,1.2,1.3,1.5,1.7,2.0,2.5],
      ["RS>1.0","RS>1.2","RS>1.3","RS>1.5 ← 현행","RS>1.7","RS>2.0","RS>2.5"])

table("B. 실적 조건 구성 — RS·OPM·비중 고정", "earn",
      ["none","turn","any","both","b_ophigh","b_nihigh","b_opjump","b_opmjump"],
      ["(실적조건 없음)","흑자전환만","이익폭증만(b_any)","흑자전환 OR 이익폭증 ← 현행",
       "영업익 8Q신고점만","순익 8Q신고점만","영업익 QoQ+50%만","OPM QoQ+3%p만"])

table("C. 동시 보유 종목 수 — 균등 비중", "maxpos",
      [4,5,6,8,10,12,16,20],
      ["4종목 25.0%","5종목 20.0%","6종목 16.7%","8종목 12.5% ← 현행",
       "10종목 10.0%","12종목 8.3%","16종목 6.3%","20종목 5.0%"])

table("D. 시총 하한", "marcap",
      [5e8,1e9,2e9,5e9,1e10],
      ["$0.5B 이상","$1B 이상","$2B 이상 ← 현행","$5B 이상","$10B 이상"])

table("E. 거래대금 하한 (20일 평균)", "adv",
      [1e6,2e6,5e6,1e7,2e7],
      ["$1M 이상","$2M 이상","$5M 이상 ← 현행","$10M 이상","$20M 이상"])
