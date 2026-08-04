# -*- coding: utf-8 -*-
"""
주도주 공통 특징 프로파일링 — 예측이 아니라 기술(記述)
  주도주 = 그 시점 이후 52주에 +150% 이상 오른 종목 (기계적 정의)
  가설 검증:
    H1 재무에 공통점이 있다
    H2 RS가 시장평균 대비 매우 높다
    H3 지수 신고가 갱신 전/갱신할 때 같이 신고가를 갱신한다
"""
import os, sqlite3
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "market.db")
CACHE = os.path.join(BASE, "data", "leaders_cache")
pd.set_option("display.width", 250, "display.max_columns", 40)
CUT = 1.50          # +150% = 주도주

FIN = ["rev_yoy", "rev_qoq", "gpm", "gpm_qoq", "opm", "opm_qoq", "npm", "npm_qoq",
       "op_turn", "op_pos_streak", "opm_up2", "npm_up2", "gpm_up2", "rev_q_count"]
TEC = ["rs_4w", "rs_13w", "rs_26w", "dist_52w", "days_since_hi52", "above_ma20_52w",
       "break_ma20_52w", "ret_4w", "ret_13w", "mdd_52w", "low_52w_dist",
       "vol_x_20w", "close_gt_ma20", "ma10_gt_ma20", "hi_5w", "hi_20w", "hi_52w"]
VAL = ["psr", "per", "marcap"]


def load():
    c = sqlite3.connect(DB)
    d = pd.read_sql("SELECT * FROM factor_weekly WHERE factor_ver='v1'", c)
    c.close()
    d["as_of"] = pd.to_datetime(d.as_of)
    px = d.pivot(index="as_of", columns="sym", values="close").sort_index()
    fwd = (px.shift(-52) / px - 1).stack().rename("fwd").reset_index()
    d = d.merge(fwd, on=["as_of", "sym"], how="left").dropna(subset=["fwd"])
    # 데이터 왜곡 제거
    bad = set(d.groupby("sym").fwd.max().pipe(lambda s: s[s > 20]).index)
    jump = px.pct_change().abs().gt(1.0).sum()
    bad |= set(jump[jump >= 3].index)
    d = d[~d.sym.isin(bad) & (d.close >= 5) & (d.adv_20d >= 5e6)].copy()
    d["leader"] = (d.fwd >= CUT).astype(int)
    return d, px


def spy_high():
    s = pd.read_csv(os.path.join(CACHE, "px_SPY.csv"), index_col=0, parse_dates=True)["Close"]
    hi = s.rolling(52).max()
    df = pd.DataFrame({"spy": s, "spy_hi52": (s >= hi * 0.999).astype(int)})
    df["spy_dist"] = (s / hi - 1) * 100
    # 지수 신고가까지 남은 주수 (앞으로 26주 내에 신고가가 오는가)
    fut = df.spy_hi52[::-1].rolling(27, min_periods=1).max()[::-1]
    df["spy_hi_within26"] = fut.astype(int)
    return df


def prof(d, cols, title):
    L, R = d[d.leader == 1], d[d.leader == 0]
    rows = []
    for c in cols:
        a, b = L[c].dropna(), R[c].dropna()
        if len(a) < 100 or len(b) < 100:
            continue
        # 주도주가 전체 분포에서 어느 백분위에 있었나
        pct = (d[c].dropna() < a.median()).mean() * 100
        rows.append(dict(팩터=c, 주도주중앙=a.median(), 나머지중앙=b.median(),
                         주도주25=a.quantile(.25), 주도주75=a.quantile(.75),
                         전체내백분위=pct, 배수=(a.median() / b.median()
                                          if b.median() and abs(b.median()) > 1e-6 else np.nan),
                         n=len(a)))
    t = pd.DataFrame(rows)
    t["차이"] = t.주도주중앙 - t.나머지중앙
    print(f"\n{'='*112}\n{title}\n{'='*112}")
    print(t.round(2).to_string(index=False))
    return t


def main():
    d, px = load()
    n_all, n_lead = len(d), int(d.leader.sum())
    print(f"관측 {n_all:,} · 종목 {d.sym.nunique()} · 주도주(+150%↑ in 52w) "
          f"{n_lead:,}건 ({n_lead/n_all*100:.2f}%) · 종목수 {d[d.leader==1].sym.nunique()}")
    print(f"주도주 수익률 중앙 {d[d.leader==1].fwd.median()*100:.0f}% · "
          f"나머지 {d[d.leader==0].fwd.median()*100:.0f}%")

    print(f"\n{'#'*112}\nH1. 재무에 공통점이 있는가\n{'#'*112}")
    prof(d, FIN, "재무 팩터 — 주도주 vs 나머지 (진입 시점)")

    print(f"\n{'#'*112}\nH2. RS가 시장평균 대비 매우 높은가\n{'#'*112}")
    prof(d, TEC, "기술 팩터")
    for c in ["rs_4w", "rs_13w", "rs_26w"]:
        L = d[d.leader == 1][c].dropna()
        A = d[c].dropna()
        print(f"\n  {c}: 주도주 중앙 {L.median():.3f} / 전체 중앙 {A.median():.3f}")
        print(f"    주도주 중 RS>1.0 비율 {(L>1).mean()*100:.0f}%  "
              f">1.2 {(L>1.2).mean()*100:.0f}%  >1.5 {(L>1.5).mean()*100:.0f}%")
        print(f"    (전체:      RS>1.0 {(A>1).mean()*100:.0f}%  "
              f">1.2 {(A>1.2).mean()*100:.0f}%  >1.5 {(A>1.5).mean()*100:.0f}%)")

    print(f"\n{'#'*112}\n밸류에이션\n{'#'*112}")
    prof(d, VAL, "P축")

    # ── H3. 지수 신고가와의 동조 ──
    print(f"\n{'#'*112}\nH3. 지수 신고가 갱신 전/때에 같이 신고가를 갱신하는가\n{'#'*112}")
    sp = spy_high()
    d2 = d.merge(sp, left_on="as_of", right_index=True, how="left")
    L = d2[d2.leader == 1]
    print(f"\n  [지수가 신고가인 주]  전체관측 중 {d2.spy_hi52.mean()*100:.1f}%")
    for lab, sub in [("주도주", L), ("나머지", d2[d2.leader == 0])]:
        a = sub[sub.spy_hi52 == 1]
        b = sub[sub.spy_hi52 == 0]
        print(f"    {lab}: 지수신고가 주에 종목도 신고가 {a.hi_52w.mean()*100:5.1f}%  |  "
              f"지수 비신고가 주엔 {b.hi_52w.mean()*100:5.1f}%")
    print(f"\n  [지수 상태별 주도주 출현율]")
    for lab, m in [("지수 신고가", d2.spy_hi52 == 1),
                   ("지수 −5% 이내", (d2.spy_dist >= -5) & (d2.spy_hi52 == 0)),
                   ("지수 −5~−15%", (d2.spy_dist < -5) & (d2.spy_dist >= -15)),
                   ("지수 −15% 미만", d2.spy_dist < -15)]:
        s = d2[m]
        if len(s) > 500:
            print(f"    {lab:16s} 관측 {len(s):7,}  주도주 출현율 {s.leader.mean()*100:5.2f}%  "
                  f"(전체평균 {d2.leader.mean()*100:.2f}%)")
    print(f"\n  [주도주는 지수보다 먼저 신고가를 내는가]")
    for lab, m in [("종목 신고가 & 지수도 신고가", (d2.hi_52w == 1) & (d2.spy_hi52 == 1)),
                   ("종목 신고가 & 지수는 아직 (선행)", (d2.hi_52w == 1) & (d2.spy_hi52 == 0)),
                   ("종목 신고가 아님 & 지수 신고가", (d2.hi_52w == 0) & (d2.spy_hi52 == 1)),
                   ("둘 다 아님", (d2.hi_52w == 0) & (d2.spy_hi52 == 0))]:
        s = d2[m]
        if len(s) > 300:
            print(f"    {lab:32s} 관측 {len(s):7,}  주도주율 {s.leader.mean()*100:5.2f}%  "
                  f"52주수익 중앙 {s.fwd.median()*100:+6.1f}%")
    print(f"\n  [지수가 26주 내 신고가를 낼 국면인가]")
    for lab, m in [("향후26주 내 지수신고가 有", d2.spy_hi_within26 == 1),
                   ("없음", d2.spy_hi_within26 == 0)]:
        s = d2[m]
        print(f"    {lab:26s} 관측 {len(s):7,}  주도주율 {s.leader.mean()*100:5.2f}%")

    # ── 주도주 진입 시점 궤적 ──
    print(f"\n{'#'*112}\n주도주가 되기 직전, 무엇이 이미 참이었나 (충족률)\n{'#'*112}")
    conds = [
        ("종가 > 20주선", d.close_gt_ma20 == 1),
        ("10주선 > 20주선", d.ma10_gt_ma20 == 1),
        ("52주 신고가", d.hi_52w == 1),
        ("신고가 −10% 이내", d.dist_52w >= -10),
        ("신고가 −25% 이내", d.dist_52w >= -25),
        ("RS26 > 1.0", d.rs_26w > 1.0),
        ("RS26 > 1.2", d.rs_26w > 1.2),
        ("RS13 > 1.2", d.rs_13w > 1.2),
        ("52주 저점 대비 +50%↑", d.low_52w_dist >= 50),
        ("OPM 2분기 연속개선", d.opm_up2 == 1),
        ("NPM 2분기 연속개선", d.npm_up2 == 1),
        ("흑자전환", d.op_turn == 1),
        ("매출 YoY > 20%", d.rev_yoy > 20),
        ("매출 YoY > 50%", d.rev_yoy > 50),
        ("PSR < 3", d.psr < 3),
        ("PSR > 10", d.psr > 10),
        ("시총 < $10B", d.marcap < 10e9),
    ]
    rows = []
    for lab, m in conds:
        L = d[d.leader == 1]
        rows.append(dict(조건=lab,
                         주도주충족=m[d.leader == 1].mean()*100,
                         전체충족=m.mean()*100,
                         리프트=m[d.leader == 1].mean()/max(m.mean(), 1e-9)))
    r = pd.DataFrame(rows).sort_values("리프트", ascending=False)
    print(r.round(1).to_string(index=False))
    print("\n  리프트 = 주도주 충족률 ÷ 전체 충족률. 1.0이면 무관, 높을수록 주도주 특징")


if __name__ == "__main__":
    main()
