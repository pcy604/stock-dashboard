# -*- coding: utf-8 -*-
"""주도주 생로병사 실측 (2026-10-24, 차니 질문 ①)

질문 1) 촉매 → 베이스 → 돌파 → 추세 → 클라이맥스 → 붕괴 중 수익이 가장 큰 구간은 어디인가
질문 2) 붕괴로 넘어갈 때 공통으로 먼저 뜨는 탈출 신호는 무엇이고, 각 신호로 팔면 얼마를 지켰나

데이터: market.db factor_weekly(FACTOR_VER, 기본 v13y) — 주봉 종가 · 그 주에 알 수 있던 재무만.
      유니버스 = 한 번 들어온 종목을 빼지 않는 universe_ever(상폐 종목 포함, 단 가격 이력 없는 15종은 빠짐).

세 가지 측정 — 뒤의 것일수록 '사후 선택' 편향이 작다
 A. 대박 구간 해부(사후 선택): 저점 L → 고점 P 가 +100% 이상이고 P 이후 -30% 이상 무너진 구간만.
    각 촉발 지점(촉매=이익가속/흑자전환 첫 발생, 30주선 상향 돌파, 52주 신고가, RS 80+)에서 샀다면
    L→P 상승의 몇 %를 먹었나, 구간별(촉매 전 / 촉매→신고가 / 신고가 후 26주 / 그 뒤~고점) 상승 몫과 주당 속도.
    고점 이후: 탈출 신호마다 '고점 대비 몇 % 빠진 뒤, 고점 몇 주 뒤에' 떴나 + 고점 전에 뜬 비율(조기 이탈).
 B. 단계별 이후 수익(선택 없음): 매주 모든 종목을 Weinstein 4단계로 분류 → 이후 13·26·52주 수익 분포.
 C. 돌파 매수 거래 실험(선택 없음): '52주 신고가 + 30주선 위·상승 + 유동성' 첫 돌파에 산 모든 거래에
    탈출 규칙을 하나씩 적용 → 거래당 평균·중앙·승률·보유 주수·2배 이상 비율. 기준: 52주 그냥 보유.
결과: results/lifecycle_study.json
"""
import os, sys, json, time
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("FACTOR_VER", "v13y")
import leaders_accel as A

OUT = os.path.join(ROOT, "results", "lifecycle_study.json")


def q(x, p):
    x = pd.Series(x, dtype=float).dropna()
    return round(float(x.quantile(p)), 1) if len(x) else None


def summ(x):
    x = pd.Series(x, dtype=float).dropna()
    if not len(x):
        return dict(n=0)
    return dict(n=int(len(x)), median=round(float(x.median()), 1), mean=round(float(x.mean()), 1),
                p25=q(x, .25), p75=q(x, .75))


def main():
    t0 = time.time()
    d = A.load()
    M = A.matrices(d, ["close", "adv_20d", "marcap", "ACC", "vol_x_20w", "rv_a", "oi_a", "op_income"])
    px = M["close"]
    idx = px.index
    liq = ((M["adv_20d"] >= A.MIN_ADV) & (M["marcap"] >= A.MIN_MC)).fillna(False)
    ma10 = px.rolling(10, min_periods=8).mean()
    ma30 = px.rolling(30, min_periods=26).mean()
    slope = ma30 / ma30.shift(4) - 1
    hi52 = px.rolling(52, min_periods=40).max()
    newhi = px >= hi52 * 0.999
    r = {k: px / px.shift(k) - 1 for k in (13, 26, 39, 52)}
    rs = (0.4 * r[13] + 0.2 * r[26] + 0.2 * r[39] + 0.2 * r[52]).where(liq).rank(axis=1, pct=True) * 99
    acc = (M["ACC"] == 1)
    # 흑자전환: 분기 영업이익 > 0 이고 4분기 전 ≤ 0 (period_end 기준, 그 주에 알 수 있던 값)
    qd = (d.dropna(subset=["period_end"]).drop_duplicates(["sym", "period_end"])[["sym", "period_end", "op_income"]]
            .sort_values(["sym", "period_end"]))
    qd["TA"] = ((qd.op_income > 0) & (qd.groupby("sym").op_income.shift(4) <= 0)).astype(int)
    ta = (d[["as_of", "sym", "period_end"]].merge(qd[["sym", "period_end", "TA"]], on=["sym", "period_end"], how="left")
            .pivot_table(index="as_of", columns="sym", values="TA").reindex(index=idx, columns=px.columns).fillna(0) == 1)
    catalyst = acc | ta
    decel = (M["rv_a"] < 0) & (M["oi_a"] < 0)
    vx = M["vol_x_20w"]
    wret = px / px.shift(1) - 1
    ext = px / ma30 - 1

    # 단계 분류 (Weinstein, 주봉 30주선)
    st2 = (px > ma30) & (slope > 0)
    st4 = (px < ma30) & (slope < 0)
    st_1or3 = ~(st2 | st4) & ma30.notna()
    # 1 과 3 구분: 직전 52주 중 2단계 비중이 높았으면 3(천장권), 아니면 1(바닥권)
    prior2 = st2.astype(float).rolling(52, min_periods=26).mean()
    stage = pd.DataFrame(np.nan, index=idx, columns=px.columns)
    stage[st2] = 2; stage[st4] = 4
    stage[st_1or3 & (prior2 >= 0.5)] = 3; stage[st_1or3 & (prior2 < 0.5)] = 1

    P = px.values; cols = px.columns; n = len(idx)
    MA10, MA30, SL, RS, DEC, VX, WR, EXT = (ma10.values, ma30.values, slope.values, rs.values,
                                            decel.fillna(False).values.astype(bool), vx.values, wret.values, ext.values)
    # ── 탈출 규칙 (모두 주봉 종가 기준, 그 주에 알 수 있는 값만) ──
    def exits(j, i0, peak_track=True):
        """i0 주 매수 → 각 규칙의 첫 발동 주(없으면 None)."""
        pk = P[i0, j]
        first = dict.fromkeys(["trail20", "trail25", "trail30", "ma10", "ma30", "ma30_2w", "slope_neg",
                               "rs_lt50", "decel", "climax", "hold52"])
        for i in range(i0 + 1, n):
            c = P[i, j]
            if not (c == c and c > 0):
                continue
            if c > pk:
                pk = c
            dd = c / pk - 1
            w = i - i0
            for k, cond in (("trail20", dd <= -.20), ("trail25", dd <= -.25), ("trail30", dd <= -.30),
                            ("ma10", c < MA10[i, j]), ("ma30", c < MA30[i, j]),
                            ("ma30_2w", c < MA30[i, j] and P[i - 1, j] < MA30[i - 1, j]),
                            ("slope_neg", SL[i, j] < 0),
                            ("rs_lt50", RS[i, j] < 50),
                            ("decel", DEC[i, j]),
                            # 클라이맥스: 30주선보다 70% 이상 위 + 주간 +15% 이상 + 거래량 20주 평균의 2배 이상
                            ("climax", EXT[i, j] >= .70 and WR[i, j] >= .15 and (VX[i, j] == VX[i, j]) and VX[i, j] >= 2),
                            ("hold52", w >= 52)):
                if first[k] is None and cond:
                    first[k] = i
            if all(v is not None for v in first.values()):
                break
        return first

    # ── A. 대박 구간 해부 ──
    eps = []
    for j in range(len(cols)):
        s = px.iloc[:, j]
        v = s.values
        ok = np.where(v == v)[0]
        if len(ok) < 120:
            continue
        i = ok[0]
        while i < n - 30:
            # i 이후 104주 안에서 고점 후보
            win = v[i:min(n, i + 104)]
            if np.all(np.isnan(win)):
                break
            p_rel = int(np.nanargmax(win)); ip = i + p_rel
            lo_seg = v[max(ok[0], ip - 104):ip + 1]
            il = max(ok[0], ip - 104) + int(np.nanargmin(lo_seg))
            after = v[ip:min(n, ip + 78)]
            if ip == i or np.isnan(v[ip]) or np.isnan(v[il]):
                i = ip + 1; continue
            # 고점 확정: 이후 26주 동안 더 높은 값이 없어야
            fut = v[ip + 1:min(n, ip + 27)]
            if len(fut) and np.nanmax(fut) > v[ip]:
                i = ip + 1; continue
            gain = v[ip] / v[il] - 1
            crash = np.nanmin(after) / v[ip] - 1 if len(after) > 1 else 0
            if gain >= 1.0 and crash <= -0.30 and liq.iat[ip, j]:
                eps.append((j, il, ip))
            i = ip + 1
    A_rows = []
    for j, il, ip in eps:
        L, Pk = P[il, j], P[ip, j]
        lg = np.log(Pk / L)
        rec = dict(sym=str(cols[j]), low=str(idx[il].date()), peak=str(idx[ip].date()), gain=round((Pk / L - 1) * 100, 1),
                   wk=int(ip - il))
        trig = {}
        for k, m in (("catalyst", catalyst), ("ma30_up", st2), ("newhi52", newhi), ("rs80", rs >= 80)):
            col = m.iloc[il:ip + 1, j].values
            hit = np.where(col == True)[0]  # noqa: E712
            trig[k] = il + int(hit[0]) if len(hit) else None
        for k, ti in trig.items():
            if ti is None:
                rec[f"{k}_capt"] = None; rec[f"{k}_wk"] = None; rec[f"{k}_pos"] = None
            else:
                rec[f"{k}_capt"] = round(np.log(Pk / P[ti, j]) / lg * 100, 1)       # L→P 로그상승 중 먹은 몫
                rec[f"{k}_gain"] = round((Pk / P[ti, j] - 1) * 100, 1)              # 그 지점에서 사서 고점까지
                rec[f"{k}_wk"] = int(ti - il)
        # 구간별 상승 몫: L→촉매, 촉매→신고가, 신고가→+26주, 그 뒤→고점
        c_i = trig["catalyst"]; h_i = trig["newhi52"]
        if c_i is not None and h_i is not None and c_i <= h_i:
            cuts = [il, c_i, h_i, min(ip, h_i + 26), ip]
            seg = []
            for a, b in zip(cuts[:-1], cuts[1:]):
                seg.append((round(np.log(P[b, j] / P[a, j]) / lg * 100, 1) if b > a else 0.0, int(b - a)))
            rec["seg"] = seg
        # 고점 이후 탈출 신호: 돌파(신고가) 때 샀다고 보고 발동 시점
        if h_i is not None:
            ex = exits(j, h_i)
            for k, ei in ex.items():
                if ei is None:
                    continue
                rec[f"x_{k}_wk_vs_peak"] = int(ei - ip)                              # 음수 = 고점 전에 팔림
                rec[f"x_{k}_from_peak"] = round((P[ei, j] / Pk - 1) * 100, 1)        # 고점 대비 위치
                rec[f"x_{k}_ret"] = round((P[ei, j] / P[h_i, j] - 1) * 100, 1)       # 돌파 매수 대비 수익
        A_rows.append(rec)
    Adf = pd.DataFrame(A_rows)
    A_out = dict(n=len(Adf), gain=summ(Adf.gain) if len(Adf) else {}, wk=summ(Adf.wk) if len(Adf) else {}, trig={}, seg={},
                 exits={})
    for k in ("catalyst", "ma30_up", "newhi52", "rs80"):
        if f"{k}_capt" in Adf:
            A_out["trig"][k] = dict(found=round(float(Adf[f"{k}_capt"].notna().mean()) * 100, 1),
                                    capt=summ(Adf[f"{k}_capt"]), gain_to_peak=summ(Adf.get(f"{k}_gain")),
                                    wk_from_low=summ(Adf[f"{k}_wk"]))
    if "seg" in Adf:
        S = Adf.seg.dropna()
        names = ["저점→촉매", "촉매→52주 신고가", "신고가 후 26주", "26주 뒤→고점"]
        for t, nm in enumerate(names):
            sh = [s[t][0] for s in S]; wk = [s[t][1] for s in S]
            rate = [a / b for a, b in zip(sh, wk) if b > 0]
            A_out["seg"][nm] = dict(share=summ(sh), weeks=summ(wk), share_per_wk=summ(rate), n=len(S))
    for k in ("trail20", "trail25", "trail30", "ma10", "ma30", "ma30_2w", "slope_neg", "rs_lt50", "decel", "climax", "hold52"):
        c = f"x_{k}_wk_vs_peak"
        if c in Adf:
            fired = Adf[c].notna()
            A_out["exits"][k] = dict(fired=round(float(fired.mean()) * 100, 1),
                                     before_peak=round(float((Adf.loc[fired, c] < 0).mean()) * 100, 1),
                                     wk_vs_peak=summ(Adf[c]), from_peak=summ(Adf[f"x_{k}_from_peak"]),
                                     ret_from_breakout=summ(Adf[f"x_{k}_ret"]))

    # ── B. 단계별 이후 수익 (모든 종목·모든 주, 유동성 통과) ──
    B_out = {}
    for h in (13, 26, 52):
        fwd = px.shift(-h) / px - 1
        for sv in (1, 2, 3, 4):
            m = (stage == sv) & liq & fwd.notna()
            x = fwd[m].stack()
            B_out.setdefault(str(sv), {})[str(h)] = dict(n=int(len(x)), median=round(float(x.median()) * 100, 1),
                                                         mean=round(float(x.mean()) * 100, 1),
                                                         p2x=round(float((x >= 1).mean()) * 100, 2),
                                                         p_half=round(float((x <= -.5).mean()) * 100, 2))
    # 2단계 안에서도 '언제' — 2단계 진입 후 경과 주수별 이후 26주 수익
    S2 = st2.values
    AG = np.zeros(S2.shape)
    a = np.zeros(len(cols))
    for i in range(n):
        a = np.where(S2[i], a + 1, 0); AG[i] = a
    age = pd.DataFrame(AG, index=idx, columns=cols)
    fwd26 = px.shift(-26) / px - 1
    B_age = {}
    for lo, hi in ((1, 4), (5, 13), (14, 26), (27, 52), (53, 104), (105, 9999)):
        m = (age >= lo) & (age <= hi) & liq & fwd26.notna()
        x = fwd26[m].stack()
        B_age[f"{lo}-{hi if hi < 9999 else '+'}"] = dict(n=int(len(x)), median=round(float(x.median()) * 100, 1),
                                                        mean=round(float(x.mean()) * 100, 1),
                                                        p2x=round(float((x >= 1).mean()) * 100, 2))
    # 30주선 이격도별 이후 26주(클라이맥스 구간 확인)
    B_ext = {}
    for lo, hi in ((-1, 0), (0, .2), (.2, .4), (.4, .7), (.7, 1.0), (1.0, 99)):
        m = (ext >= lo) & (ext < hi) & liq & fwd26.notna()
        x = fwd26[m].stack()
        B_ext[f"{int(lo*100)}~{int(hi*100) if hi < 99 else '+'}%"] = dict(
            n=int(len(x)), median=round(float(x.median()) * 100, 1), mean=round(float(x.mean()) * 100, 1),
            p_dd30=round(float((x <= -.3).mean()) * 100, 1))

    # ── C. 돌파 매수 거래 실험 ──
    brk = newhi & st2 & liq & ~(newhi.shift(1).astype('boolean').fillna(False).astype(bool))
    # 같은 종목 재진입은 직전 거래가 끝난 뒤(52주 간격)로 제한 — 겹침 과대계상 방지
    trades = {k: [] for k in ("trail20", "trail25", "trail30", "ma10", "ma30", "ma30_2w", "slope_neg", "rs_lt50",
                              "decel", "climax", "hold52", "ma30_or_decel", "trail25_min26")}
    for j in range(len(cols)):
        hits = np.where(brk.values[:, j])[0]
        last = -999
        for i0 in hits:
            if i0 - last < 52 or i0 + 1 >= n:
                continue
            last = i0
            e0 = i0 + 1                                 # 1주 지연 매수
            if not (P[e0, j] == P[e0, j] and P[e0, j] > 0):
                continue
            ex = exits(j, e0)
            def ret(ei):
                if ei is None:                          # 기간 끝 또는 가격 소멸 → 마지막 가격
                    lv = np.where(P[e0:, j] == P[e0:, j])[0]
                    ei = e0 + int(lv[-1])
                return (P[ei, j] / P[e0, j] * (1 - 0.003) ** 2 - 1) * 100, int(ei - e0)
            for k in trades:
                if k == "ma30_or_decel":
                    cands = [x for x in (ex["ma30"], ex["decel"]) if x is not None]
                    ei = min(cands) if cands else None
                elif k == "trail25_min26":              # 26주 최소보유 뒤 고점 -25%
                    ei = None
                    pk = P[e0, j]
                    for i in range(e0 + 1, n):
                        c = P[i, j]
                        if not (c == c and c > 0):
                            continue
                        pk = max(pk, c)
                        if i - e0 >= 26 and c / pk - 1 <= -.25:
                            ei = i; break
                else:
                    ei = ex[k]
                rr, w = ret(ei)
                trades[k].append((rr, w, str(idx[e0].date())))
    C_out = {}
    for k, tr in trades.items():
        x = pd.Series([t[0] for t in tr]); w = pd.Series([t[1] for t in tr])
        yr = pd.Series([t[2][:4] for t in tr])
        C_out[k] = dict(n=int(len(x)), mean=round(float(x.mean()), 1), median=round(float(x.median()), 1),
                        win=round(float((x > 0).mean()) * 100, 1), p2x=round(float((x >= 100).mean()) * 100, 2),
                        avg_wk=round(float(w.mean()), 1),
                        per_wk=round(float(x.mean() / max(1e-9, w.mean())), 2),
                        avg_win=round(float(x[x > 0].mean()), 1), avg_loss=round(float(x[x <= 0].mean()), 1),
                        top5_share=round(float(x.sort_values(ascending=False).head(max(1, len(x) // 20)).sum()
                                               / max(1e-9, x.sum())) * 100, 1),
                        by_year={y: round(float(x[yr == y].mean()), 1) for y in sorted(yr.unique())})

    out = dict(run=time.strftime("%Y-%m-%d %H:%M"), factor_ver=A.VER,
               period=[str(idx[0].date()), str(idx[-1].date())], universe=int(px.shape[1]),
               defs=dict(
                   episode="저점 L→고점 P +100% 이상(104주 안), P 이후 26주간 신고점 없음, P 이후 78주 안 -30% 이상 하락, P 시점 유동성 통과",
                   catalyst="이익가속(매출·영업이익 성장률 동시 가속) 또는 흑자전환(분기 영업이익 적자→흑자) 첫 발생",
                   stage="Weinstein 주봉: 2단계 = 종가>30주선 & 30주선 4주 기울기>0 · 4단계 = 종가<30주선 & 기울기<0 · 그 사이는 직전 52주 2단계 비중≥50%면 3(천장), 아니면 1(바닥)",
                   breakout="52주 신고가(종가) 첫 주 & 2단계 & 유동성, 같은 종목은 52주 간격, 다음 주 종가 매수, 비용 편도 0.3%",
                   climax="30주선 대비 +70% 이상 & 주간 +15% 이상 & 거래량 20주 평균 2배 이상",
                   exits=dict(trail20="고점 대비 -20%", trail25="고점 대비 -25%", trail30="고점 대비 -30%",
                              ma10="종가 < 10주선", ma30="종가 < 30주선", ma30_2w="2주 연속 30주선 아래",
                              slope_neg="30주선 기울기 하락 전환", rs_lt50="RS 50 미만", decel="매출·영업이익 성장률 동시 감속",
                              climax="클라이맥스 주에 매도", hold52="52주 보유", ma30_or_decel="30주선 이탈 또는 이익 감속 중 먼저",
                              trail25_min26="26주 최소보유 뒤 고점 -25%")),
               A=A_out, B=dict(stage=B_out, stage2_age=B_age, ext30=B_ext), C=C_out, secs=round(time.time() - t0))
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"::notice title=생로병사 실측 ({A.VER})::대박 구간 {A_out['n']}개 · 돌파 거래 {C_out['hold52']['n']}건 · {out['secs']}초")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        print(tb)
        print("::error title=생로병사 실측 예외::" + tb[-900:].replace("\n", " | "))
        sys.exit(1)
