# -*- coding: utf-8 -*-
"""대가 전략 기계화 백테스트 (2026-10-24, 차니 요청 ③)

책의 규칙을 '빈칸 없는 명세서'(research/spec_engine.py)로 옮겨 같은 엔진·같은 기간·같은 비용으로 비교한다.
책에 없는 값은 명세서 source 의 '추정' 목록에 적는다. 주봉 데이터라 일봉 규칙(장중 -8% 손절 등)은 주봉 종가로 근사한다
→ 실제보다 손절이 늦게 걸려 손실이 커질 수 있다(오닐·미너비니에 불리한 근사).

비교 방법
  · 우선순위 'RS 높은 순'(결정적, 같은 값만 무작위) 1회 + '무작위' 10회 중앙값·하위 10%
  · 평가 시작 = results/rs_accel_bt.json 의 평가 시작(첫 신호 가능 주)과 같게
  · 엔진 검증: 현행 ★(★ = 이익가속 × 주간 +10%, 20칸·고점 -20%)를 기존 시뮬레이터와 이 엔진으로 같은 시드로 돌려 CAGR 이 같은지 확인
결과: results/master_specs.json
"""
import os, sys, json, time
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
import portfolio_rules_sim as S
import rs_accel_bt as B
import rs_accel_detail as D
import spec_engine as E
A = S.A

OUT = os.path.join(ROOT, "results", "master_specs.json")
SEEDS = 10
BASE = dict(freq="W", fill="next_close", full="skip", pyramid=None, rebalance=None, cost=0.003, cash="fedfunds")


def specs():
    return [
        dict(BASE, key="oneil", name="오닐 CAN SLIM (기계화)", entry="oneil", rank="rs_desc", slots=10, weight=0.10,
             market="spy40", exits=[("stop_entry", 8), ("tp_unless_fast", 25, 20, 3), ("below_ma_after", 10, 8)],
             source=dict(book="How to Make Money in Stocks(오닐) · IBD 매도 규칙",
                         rules=["C 분기 순이익 전년동기 +25%↑ & 직전 분기보다 증가율 상승", "A 최근 4분기 합 순이익 전년 대비 +25%↑",
                                "N 52주 신고가 종가 돌파 & 거래량 20주 평균 1.4배↑", "L RS 80↑", "M SPY > 40주선(≈200일선)일 때만 신규",
                                "손절 진입가 -8% · 익절 +25% · 3주 안 +20% 급등주는 익절 면제 → 8주 뒤 10주선(≈50일선) 이탈 시 매도"],
                         assumed=["EPS 대신 순이익(주식수 변화 무시)", "S(수급)·I(기관) 조건 생략 — 데이터 없음",
                                  "컵위드핸들 대신 '52주 신고가 + 거래량 1.4배'", "10종목 10%씩(오닐은 집중 권고, 수 미정)",
                                  "장중 손절 → 주봉 종가 손절", "우선순위 RS 높은 순(오닐: 업종 1~2등)"])),
        dict(BASE, key="minervini", name="미너비니 SEPA·트렌드 템플릿 (기계화)", entry="minervini", rank="rs_desc", slots=10,
             weight=0.10, market="spy40", exits=[("stop_entry", 7), ("below_ma_after", 10, 4)],
             source=dict(book="Trade Like a Stock Market Wizard(미너비니)",
                         rules=["트렌드 템플릿: 종가>30·40주선, 30주선>40주선, 40주선 4주 상승, 10주선>30주선, 종가>10주선, 52주 저점 +30%↑, 52주 고점 -25% 이내, RS 70↑",
                                "SEPA 펀더멘털: 분기 순이익 전년동기 +20%↑", "진입: 10주 신고가 종가 돌파 & 거래량 1.4배↑(피벗 돌파 근사)",
                                "M SPY > 40주선", "손절 진입가 -7% · 4주 보유 뒤 10주선 이탈 시 매도"],
                         assumed=["50/150/200일선 → 10/30/40주선", "VCP(변동성 수축) 패턴 미구현 — 10주 신고가로 근사",
                                  "펀더멘털 문턱 +20%", "4주 뒤 10주선 이탈 매도", "10종목 10%씩"])),
        dict(BASE, key="weinstein", name="웨인스타인 2단계 돌파 (기계화)", entry="weinstein", rank="rs_desc", slots=20,
             weight=0.05, market="spy30", exits=[("stop_entry", 15), ("below_ma", 30)],
             source=dict(book="Secrets for Profiting in Bull and Bear Markets(웨인스타인)",
                         rules=["30주선 기울기 ≥ 0 & 종가 > 30주선", "직전 10주 고점 종가 돌파(저항선 돌파)", "거래량 20주 평균 2배↑",
                                "맨스필드 RS > 0(시장 대비 상대강도가 52주 평균 위)", "M SPY > 30주선", "청산: 주봉 종가 30주선 이탈 · 초기 손절 -15%"],
                         assumed=["저항선 = 직전 10주 최고 종가", "초기 손절 -15%(책: 베이스 저점 아래)", "20종목 5%씩"])),
        dict(BASE, key="inter_trail", name="교집합 (현행 측정: 고점 -20%)", entry="inter", rank="random", slots=20, weight=0.05,
             market=None, exits=[("trail", 20)],
             source=dict(book="우리 규칙(17 문서)", rules=["RS 80↑ × (이익가속 또는 흑자전환)", "고점 대비 -20%"], assumed=[])),
        dict(BASE, key="inter_min26", name="교집합 + 26주 최소보유 뒤 고점 -25%", entry="inter", rank="random", slots=20,
             weight=0.05, market=None, exits=[("trail_after", 25, 26)],
             source=dict(book="우리 규칙 + 오닐 8주·프로젝트 '최소보유 바닥' 발견", rules=["RS 80↑ × (이익가속 또는 흑자전환)",
                         "26주 보유 뒤부터 고점 대비 -25%"], assumed=["26주·-25% 는 생로병사 실측 전 사전 고정"])),
        dict(BASE, key="inter_ma30", name="교집합 + 30주선 이탈 청산", entry="inter", rank="random", slots=20, weight=0.05,
             market=None, exits=[("below_ma", 30)],
             source=dict(book="우리 규칙 + 웨인스타인 청산", rules=["RS 80↑ × (이익가속 또는 흑자전환)", "주봉 종가 30주선 이탈"],
                         assumed=[])),
        dict(BASE, key="inter_rs", name="교집합 (RS 높은 순 우선)", entry="inter", rank="rs_desc", slots=20, weight=0.05,
             market=None, exits=[("trail", 20)],
             source=dict(book="우리 규칙", rules=["교집합 · 동시 신호는 RS 높은 순"], assumed=[])),
    ]


def main():
    t0 = time.time()
    px, star, spy, cr, _ = S.load()
    d = A.load()
    M = A.matrices(d, ["adv_20d", "marcap", "ACC", "vol_x_20w"])
    liq = ((M["adv_20d"] >= A.MIN_ADV) & (M["marcap"] >= A.MIN_MC)).fillna(False)
    acc = (M["ACC"] == 1).fillna(False) & liq
    rs = B.rs_rank(px, liq)
    ta = B.turnaround(d, px) & liq
    vx = M["vol_x_20w"]
    ma = {k: px.rolling(k, min_periods=int(k * .8)).mean() for k in (10, 30, 40)}
    hi52 = px.rolling(52, min_periods=40).max(); lo52 = px.rolling(52, min_periods=40).min()
    hi10p = px.shift(1).rolling(10, min_periods=8).max()
    # 분기 순이익 성장(그 주에 알 수 있던 분기)
    q = (d.dropna(subset=["period_end"]).drop_duplicates(["sym", "period_end"])[["sym", "period_end", "net_income"]]
           .sort_values(["sym", "period_end"]).copy())
    g = q.groupby("sym").net_income
    n4 = g.shift(4)
    q["q_yoy"] = np.where(n4 > 0, (q.net_income - n4) / n4 * 100, np.nan)
    q["q_acc"] = q.q_yoy > q.groupby("sym").q_yoy.shift(1)
    ttm = g.transform(lambda s: s.rolling(4).sum()); ttm4 = ttm.groupby(q.sym).shift(4)
    q["a_yoy"] = np.where(ttm4 > 0, (ttm - ttm4) / ttm4 * 100, np.nan)
    x = d[["as_of", "sym", "period_end"]].merge(q[["sym", "period_end", "q_yoy", "q_acc", "a_yoy"]],
                                                on=["sym", "period_end"], how="left")
    piv = lambda c: x.pivot_table(index="as_of", columns="sym", values=c).reindex(index=px.index, columns=px.columns)
    q_yoy, a_yoy = piv("q_yoy"), piv("a_yoy")
    q_acc = piv("q_acc").fillna(0) == 1
    spw = spy.reindex(px.index).ffill()
    mkt = dict(spy40=spw > spw.rolling(40, min_periods=32).mean(), spy30=spw > spw.rolling(30, min_periods=24).mean())
    rel = px.div(spw, axis=0); mans = rel / rel.rolling(52, min_periods=40).mean() - 1
    newhi = px >= hi52 * 0.999
    SIG = dict(
        oneil=liq & (q_yoy >= 25) & q_acc & (a_yoy >= 25) & (rs >= 80) & newhi & (vx >= 1.4),
        minervini=(liq & (px > ma[30]) & (px > ma[40]) & (ma[30] > ma[40]) & (ma[40] > ma[40].shift(4))
                   & (ma[10] > ma[30]) & (px > ma[10]) & (px >= lo52 * 1.3) & (px >= hi52 * 0.75) & (rs >= 70)
                   & (q_yoy >= 20) & (px > hi10p) & (vx >= 1.4)),
        weinstein=(liq & (px > ma[30]) & (ma[30] >= ma[30].shift(4)) & (px > hi10p) & (vx >= 2) & (mans > 0)),
        inter=(acc | ta) & (rs >= 80))
    SIG = {k: v.fillna(False).astype(bool) for k, v in SIG.items()}
    try:
        t_ev = pd.Timestamp(json.load(open(B.OUT, encoding="utf-8"))["period"][0])
    except Exception:
        t_ev = min(v.index[v.any(axis=1)][0] for v in SIG.values())
    sl = lambda z: z.loc[t_ev:]
    px_, spy_, cr_ = sl(px), sl(spy), sl(cr)
    SIG = {k: sl(v) for k, v in SIG.items()}
    rs_, ma_ = sl(rs), {k: sl(v) for k, v in ma.items()}
    mk_ = {k: sl(v) for k, v in mkt.items()}
    star_ = sl(star)

    spy_w = spy_.dropna()
    out = dict(run=time.strftime("%Y-%m-%d %H:%M"), factor_ver=A.VER, period=[str(px_.index[0].date()), str(px_.index[-1].date())],
               universe=int(px_.shape[1]), spy=dict(stats=S.stats(spy_w)[0], yearly=D.yearly(spy_w), dd5=D.dd_episodes(spy_w)),
               signals={k: round(float(v.sum(axis=1).mean()), 1) for k, v in SIG.items()}, strategies={})
    # 엔진 검증
    chk = []
    for s_ in range(3):
        h1, _ = S.run(px_, star_, slots=20, stop=20, delay=1, cash_r=cr_, order="random", seed=100 + s_)
        h2 = E.run(dict(BASE, name="chk", source={}, entry="star", rank="random", slots=20, weight=0.05, market=None,
                        exits=[("trail", 20)]), px_, star_, None, None, cr_, seed=100 + s_)
        chk.append((S.stats(h1.v)[0]["CAGR"], S.stats(h2.v)[0]["CAGR"]))
    out["engine_check"] = dict(pairs=chk, note="같은 시드 기존 시뮬레이터 vs 명세서 엔진 CAGR — 무작위 순서 구현 차이로 회차별 값은 다를 수 있고 분포가 같아야 한다")
    for sp in specs():
        sig = SIG[sp["entry"]]; mk = mk_.get(sp["market"]) if sp["market"] else None
        rk = rs_ if sp["rank"] == "rs_desc" else None
        L = []
        h = E.run(sp, px_, sig, rk, mk, cr_, ma=ma_, seed=100, log=L)
        st, _ = S.stats(h.v, spy_)
        cag = []
        for s_ in range(SEEDS):
            hh = E.run(dict(sp, rank="random"), px_, sig, None, mk, cr_, ma=ma_, seed=200 + s_)
            cag.append(S.stats(hh.v)[0]["CAGR"])
        closed = [t for t in L if t["why"] != "보유 중"]
        rets = [(t["sell_px"] / t["buy_px"] - 1) * 100 for t in closed]
        whys = pd.Series([t["why"] for t in closed]).value_counts().to_dict()
        out["strategies"][sp["key"]] = dict(
            name=sp["name"], spec={k: sp[k] for k in ("freq", "fill", "rank", "slots", "weight", "full", "exits", "market",
                                                       "pyramid", "rebalance", "cost", "cash")},
            source=sp["source"], stats=st, random=dict(median=float(np.median(cag)), p10=float(np.quantile(cag, .1)),
                                                       all=sorted(cag)),
            yearly=D.yearly(h.v), dd5=D.dd_episodes(h.v),
            trades=dict(n=len(closed), win=round(float(np.mean([r > 0 for r in rets])) * 100, 1) if rets else None,
                        avg_win=round(float(np.mean([r for r in rets if r > 0])), 1) if any(r > 0 for r in rets) else None,
                        avg_loss=round(float(np.mean([r for r in rets if r <= 0])), 1) if any(r <= 0 for r in rets) else None,
                        avg_wk=round(float(np.mean([t["wk"] for t in closed])), 1) if closed else None, why=whys),
            avg_pos=round(float(h.n.mean()), 1), avg_cash=round(float(h.cash.mean()) * 100, 1),
            final=round(float(h.v.iloc[-1] / h.v.iloc[0] * 100), 1))
        print(sp["key"], st, cag, flush=True)
    out["secs"] = round(time.time() - t0)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    S_ = out["strategies"]
    print(f"::notice title=대가 전략 기계화 ({A.VER})::SPY {out['spy']['stats']['CAGR']}% · " + " · ".join(
        f"{v['name']} {v['stats']['CAGR']}%(무작위 중앙 {v['random']['median']}, MDD {v['stats']['MDD']})" for v in S_.values()))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        print(tb)
        print("::error title=대가 전략 기계화 예외::" + tb[-900:].replace("\n", " | "))
        sys.exit(1)
