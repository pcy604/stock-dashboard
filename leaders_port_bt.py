# -*- coding: utf-8 -*-
"""
포트폴리오 백테스트 — results/leaders_port_bt.json

이익 가속 신호를 실제로 돈으로 굴렸다면 어떻게 됐는가.
지금까지의 측정은 전부 "신호 1건당 수익률"이었다. 그건 비중을 무시한 숫자다.
여기서는 **자본이 유한한 계좌**를 주 단위로 굴린다.

⚠️ 과최적화 경계 — 이 파일이 지키려는 규칙
  · 답지를 보고 맞추는 게 아니라 **미래에 벌려는 행위**를 흉내내는 것이 목적이다.
  · 파라미터는 최소로 둔다. 문턱은 문헌에 있는 값(O'Neil +25% 익절,
    Minervini 단일 종목 25% 상한)과 그 주변만 본다.
  · **전 구간 총수익으로 우열을 가리지 않는다.** 연도별로 흩어지는지를 같이 본다.
    한 해가 전체를 끌고 간 전략은 '좋은 전략'이 아니라 '그 해에 맞은 전략'이다.
  · 최고 성적 하나를 고르지 않는다. 비슷한 것들이 뭉쳐 있으면 그 구간이 답이고,
    하나만 튀면 그건 우연일 가능성이 높다고 적는다.

돌리는 방식
  매주(주봉 종가 기준)
    1) 보유 종목의 청산 조건을 검사한다 — 손절 / 부분매도 / 전량청산
    2) 그 주 신호 종목을 진입 후보로 받는다
    3) 현금이 있으면 산다. 현금 부족 시 정책에 따라 넘기거나 최하위를 판다
    4) 피라미딩: 수익이 문턱을 넘은 보유 종목의 비중을 한 칸 올린다
  거래비용 왕복 0.3% 를 뺀다(수수료+슬리피지).

⚠️ 한계
  · 상장폐지 종목이 유니버스에 없다. 모든 결과가 낙관 쪽이다.
  · 주봉 종가에만 체결된다. 장중 손절·급등은 반영되지 않는다.
  · 배당·분할은 가격 시계열에 이미 반영돼 있다고 가정한다.
  · 세금은 계산하지 않는다.

CLI
  python leaders_port_bt.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

import leaders_accel as A

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "results", "leaders_port_bt.json")

COST = 0.003          # 왕복 거래비용
CASH0 = 100_000.0     # 시작 자본(달러). 비율만 보므로 절대값은 의미 없다
LADDER = [1.0, 4.0, 10.0, 20.0]     # 비중 사다리(%) — 아래에서 시작해 올라간다


def _r(v, n=2):
    if v is None or v != v or not np.isfinite(v):
        return None
    return round(float(v), n)


def run(px, g, spy, *, mode, step_thr=None, trim_at=None, stop=None,
        max_pos=25, cap_full=False, ladder=None, regime=None,
        regime_exit=False):
    """계좌 하나를 주 단위로 굴린다.

    mode      'equal'  = 신호마다 같은 비중(1/max_pos)
              'ladder' = 피라미딩 사다리(LADDER)
    step_thr  사다리 승급 문턱(%). 진입가 대비 이만큼 오를 때마다 한 칸 위로
    trim_at   부분매도 문턱(%). 도달 시 보유 수량의 절반을 판다(한 번만)
    stop      손절(%). 진입가 대비 이만큼 빠지면 전량 청산
    cap_full  현금이 없을 때 최하위 수익 종목을 팔아 자리를 만드는가
    regime    시장 필터 — True 인 주에만 **신규 진입**한다.
    regime_exit 필터가 꺼지면 **보유도 전량 정리**한다(Faber 원문 방식).
              ⚠️ 2026-09-11 측정 — 신규 진입만 막는 것으로는 MDD 가 거의 안 줄었다.
                 필터는 낙폭 구간의 90~100% 를 제대로 차단했는데도 그랬다.
                 원인은 '하락장에 산 종목'이 아니라 **이미 들고 있던 종목**이었다.
                 피라미딩으로 20% 까지 키운 자리가 반토막 나면 계좌가 10% 빠진다.
    """
    LAD = ladder or LADDER
    dates = px.index
    cash = CASH0
    pos = {}          # sym -> dict(sh, entry, lvl, trimmed, last)
    hist = []

    # ⚠️ 2026-09-11 버그 — 원래 `p.get(s) or 0` 으로 가격을 읽었다.
    #    파이썬에서 **NaN 은 falsy 가 아니다**(`float('nan') or 0` → nan).
    #    결측 가격이 하나만 섞여도 계좌 전체가 NaN 이 되고, 그 뒤 CAGR·연도수익이
    #    통째로 사라졌다. 실제로 '손절25' 시나리오가 그래서 값 없이 나왔다.
    #    결측은 **마지막 유효가로 캐리**한다(유니버스에 상장폐지가 없으므로
    #    중간 결측은 대개 일시적이다).

    def _q(p, s):
        """유효 가격만 돌려준다. 없으면 마지막으로 본 값을 쓴다."""
        v = p.get(s)
        if v is not None and np.isfinite(v) and v > 0:
            if s in pos:
                pos[s]["last"] = float(v)
            return float(v)
        if s in pos:
            return pos[s].get("last")
        return None

    for i, t in enumerate(dates):
        p = px.loc[t]

        # ── 0) 국면 이탈 시 전량 현금화 ───────────────
        if regime_exit and regime is not None and not bool(regime.get(t, True)):
            for s_ in list(pos):
                c = _q(p, s_)
                if c is not None:
                    cash += pos[s_]["sh"] * c * (1 - COST)
                del pos[s_]

        # ── 1) 청산 검사 ─────────────────────────────
        for s in list(pos):
            c = _q(p, s)
            if c is None:
                continue
            e = pos[s]
            ret = (c / e["entry"] - 1) * 100
            if stop is not None and ret <= -stop:
                cash += e["sh"] * c * (1 - COST)
                del pos[s]
                continue
            if trim_at is not None and not e["trimmed"] and ret >= trim_at:
                half = e["sh"] / 2
                cash += half * c * (1 - COST)
                e["sh"] -= half
                e["trimmed"] = True

        equity = cash + sum(pos[s]["sh"] * (_q(p, s) or 0.0) for s in pos)

        # ── 2) 피라미딩 승급 ─────────────────────────
        if mode == "ladder" and step_thr:
            for s in list(pos):
                c = _q(p, s)
                if c is None:
                    continue
                e = pos[s]
                ret = (c / e["entry"] - 1) * 100
                want_lvl = min(int(ret // step_thr), len(LAD) - 1)
                while e["lvl"] < want_lvl and e["lvl"] < len(LAD) - 1:
                    tgt = equity * LAD[e["lvl"] + 1] / 100
                    cur = e["sh"] * c
                    add = tgt - cur
                    if add <= 0 or add > cash:
                        break
                    e["sh"] += add / c * (1 - COST)
                    cash -= add
                    e["lvl"] += 1

        # ── 3) 신규 진입 ─────────────────────────────
        # 시장 필터가 꺼진 주에는 사지 않는다. 팔지도 않는다 — 보유는 그대로 둔다.
        if regime is not None and not bool(regime.get(t, True)):
            eq = cash + sum(pos[s]["sh"] * (_q(p, s) or 0.0) for s in pos)
            hist.append((t, eq, len(pos), cash / eq * 100 if eq > 0 else 0))
            continue
        hit = g.loc[t]
        cands = [s for s in hit[hit].index
                 if s not in pos and np.isfinite(p.get(s) or np.nan)
                 and (p.get(s) or 0) > 0]
        for s in cands:
            if len(pos) >= max_pos:
                if not cap_full:
                    break
                # 현금이 없으면 가장 성적 나쁜 보유를 정리해 자리를 만든다
                worst = min(pos, key=lambda k: (_q(p, k) or 0.0) / pos[k]["entry"])
                wc = _q(p, worst)
                if wc is None:
                    break
                if (wc / pos[worst]["entry"] - 1) >= 0:
                    break                      # 이긴 종목까지 팔지는 않는다
                cash += pos[worst]["sh"] * wc * (1 - COST)
                del pos[worst]
            w = (LAD[0] if mode == "ladder" else 100.0 / max_pos) / 100
            amt = equity * w
            if amt > cash:
                amt = cash
            if amt <= equity * 0.0005:
                break
            c = float(p.get(s))
            pos[s] = dict(sh=amt / c * (1 - COST), entry=c, lvl=0,
                          trimmed=False, last=c)
            cash -= amt

        eq = cash + sum(pos[s]["sh"] * (_q(p, s) or 0.0) for s in pos)
        hist.append((t, eq, len(pos), cash / eq * 100 if eq > 0 else 0))

    # ⚠️ 컬럼명을 eq 로 두면 DataFrame.eq() 메서드와 부딪혀 h.eq 가 함수가 된다.
    h = pd.DataFrame(hist, columns=["t", "val", "n", "cash%"]).set_index("t")
    yrs = (h.index[-1] - h.index[0]).days / 365.25
    _end = float(h.val.iloc[-1])
    # ⚠️ 계좌가 0 이하로 내려가면 (음수)**(1/8) 이 복소수가 되고 아래 서식에서 죽는다.
    #    실전에서는 그 전에 끝난 것이므로 −100% 로 적는다.
    if _end <= 0 or yrs <= 0:
        cagr = -1.0
    else:
        cagr = (_end / CASH0) ** (1 / yrs) - 1
    dd = (h.val / h.val.cummax() - 1) * 100
    wk = h.val.pct_change().dropna()
    by_year = {}
    for y, gg in h.groupby(h.index.year):
        if len(gg) < 5:
            continue
        by_year[int(y)] = _r((gg.val.iloc[-1] / gg.val.iloc[0] - 1) * 100, 1)
    return dict(
        cagr=_r(cagr * 100, 1), total=_r((h.val.iloc[-1] / CASH0 - 1) * 100, 1),
        mdd=_r(dd.min(), 1), avg_pos=_r(h.n.mean(), 1), avg_cash=_r(h["cash%"].mean(), 1),
        vol=_r(wk.std() * np.sqrt(52) * 100, 1),
        sharpe=_r(wk.mean() / wk.std() * np.sqrt(52), 2) if wk.std() > 0 else None,
        by_year=by_year)



def regimes(spy, spyv=None):
    """시장 필터 후보. 각각 True = 위험자산 보유 허용.

    ⚠️ 2026-09-13 전면 재작업 — 앞선 두 판이 다 좁았다.
       1차는 40주 이평 하나로 때웠고, 2차는 경제 지표만 넣고 이평 길이를 안 바꿨다.
       "5주·10주·20주는 해봤냐, ISM 은, 10년물은" 이라는 지적이 전부 맞다.
       여기서는 **길이를 훑고, 지표군을 넓히고, 전부 한 표에 같이 적는다.**

    ⚠️ 후보가 많아지면 그중 1등은 **우연히도** 좋아 보인다(다중비교).
       그래서 우열은 전 구간 CAGR 이 아니라 **연도별로 흩어지는지**로 본다.
       1등만 보고 고르지 않는다 — 같은 계열이 뭉쳐서 좋으면 그게 신호다.

    ── 가격 (길이를 훑는다) ─────────────────────────────
      ma5/10/20/30/40  SPY 가 N주 이평 위. 40주 = Faber(2007) 10개월 이평.
      mom12            12개월 수익률 > 0. Antonacci 절대 모멘텀.
      tmpl             Minervini 추세 템플릿을 **지수에** 적용 — px>ma10>ma30>ma40.
      dist             O'Neil 분산일(distribution day) 주봉 대용.
                       ⚠️ 원문은 **일봉** 기준(25거래일 중 5일)이다. 주봉 데이터밖에
                          없어 '거래량 늘며 하락한 주'로 바꿔 세었다. 같은 규칙이 아니다.

    ── 금융 상황 ────────────────────────────────────────
      nfci      시카고연준 금융상황지수 < 0 (완화적). 주간 발표, 1971년부터.
      nfci_up   NFCI 가 13주 전보다 크게 오르면(긴축 전환) 회피 — 수준이 아닌 변화.
      anfci     경기로 설명되는 부분을 뺀 조정판 < 0.
      credit2   NFCI 신용 하위지수. 하이일드 OAS(2023-09~)의 장기 대용.
      vix       VIX 가 자기 2년 분포 상위 20% 위면 회피.
      fg        Fear&Greed **대용**. CNN 지수는 무료 히스토리가 없어 공개 구성요소
                4개(모멘텀·VIX·신용·안전자산선호)를 z 합성해 0~100 으로 만든 것이다.
                ⚠️ CNN 원본과 같은 숫자가 아니다.
      fg_ct     같은 지표를 **역발상**으로 — 극단적 공포(<20)일 때만 산다.

    ── 금리 ─────────────────────────────────────────────
      y10       10년물이 13주 만에 0.6%p 넘게 튀면 회피(성장주 할인율 충격).
      curve     10년−2년 역전이 **해소될 때** 회피.
      curve3    같은 규칙을 10년−3개월로. 침체 예측력은 이쪽이 낫다는 연구가 많다.

    ── 실물 (ISM 대용) ──────────────────────────────────
      ⚠️ ISM 제조업 PMI 는 FRED 에서 받을 수 없다(2016년 라이선스 회수).
         아래 셋은 **대용이지 ISM 이 아니다.**
      cfnai     시카고연준 국가활동지수 3개월 평균 > −0.7 (연준이 쓰는 침체 문턱).
      neword    비국방 자본재 신규수주 YoY > 0.
      awh       제조업 주당 근로시간이 1년 전보다 안 줄었으면 허용.
      ip        산업생산 YoY > 0.

    ── 노동 ─────────────────────────────────────────────
      sahm      삼의 법칙 — 실업률이 12개월 최저 대비 +0.5%p.  오탐은 적지만 **느리다.**
      claims    신규실업수당 4주 평균이 52주 최저 대비 +15% — 삼의 법칙의 빠른 판.

    ── 조합 ─────────────────────────────────────────────
      각 계열에서 가장 근거가 분명한 것 하나씩만 뽑아 AND 로 묶는다.
      조합을 훑지 않는 이유는 그게 과최적화가 시작되는 지점이기 때문이다.

    ⚠️ 모든 지표는 그 주차에 알 수 있던 값만 쓴다(발표 지연 반영).
    """
    import os as _os
    out = {}

    # ── 가격 ────────────────────────────────────────────
    mas = {n: spy.rolling(n, min_periods=max(4, n // 2)).mean()
           for n in (5, 10, 20, 30, 40)}
    for n, m in mas.items():
        out[f"ma{n}"] = (spy > m).fillna(True)
    out["mom12"] = (spy / spy.shift(52) - 1 > 0).fillna(True)
    out["tmpl"] = ((spy > mas[10]) & (mas[10] > mas[30])
                   & (mas[30] > mas[40])).fillna(True)
    if spyv is not None:
        dn = (spy.pct_change() <= -0.002) & (spyv > spyv.shift(1))
        out["dist"] = (dn.rolling(10, min_periods=5).sum() < 4).fillna(True)

    mp = _os.path.join(BASE, "data", "macro_hist.parquet")
    if not _os.path.exists(mp):
        print("  [WARN] macro_hist.parquet 없음 — 가격 필터만 쓴다", flush=True)
        return {k: v.fillna(True) for k, v in out.items()}
    m = pd.read_parquet(mp).reindex(spy.index).ffill()

    def _has(*c):
        return all(x in m.columns for x in c)

    # ── 금융 상황 ───────────────────────────────────────
    if _has("NFCI"):
        out["nfci"] = (m["NFCI"] < 0).fillna(True)
        out["nfci_up"] = ((m["NFCI"] - m["NFCI"].shift(13)) < 0.2).fillna(True)
    if _has("ANFCI"):
        out["anfci"] = (m["ANFCI"] < 0).fillna(True)
    if _has("NFCICREDIT"):
        c = m["NFCICREDIT"]
        out["credit2"] = (c < c.rolling(104, min_periods=52)
                          .quantile(0.80)).fillna(True)
    if _has("VIXCLS"):
        vx = m["VIXCLS"]
        out["vix"] = (vx < vx.rolling(104, min_periods=52)
                      .quantile(0.80)).fillna(True)

    # ── Fear & Greed 대용 ───────────────────────────────
    if _has("VIXCLS", "NFCICREDIT"):
        def _z(x):
            return ((x - x.rolling(104, min_periods=52).mean())
                    / x.rolling(104, min_periods=52).std())
        mom = _z(spy / mas[20] - 1)          # 모멘텀
        vol = -_z(m["VIXCLS"])               # 변동성(낮을수록 탐욕)
        cr = -_z(m["NFCICREDIT"])            # 정크본드 수요
        sh = _z(spy.pct_change(20))          # 안전자산 선호의 반대
        comp = pd.concat([mom, vol, cr, sh], axis=1).mean(axis=1)
        fg = (50 + comp * 20).clip(0, 100)
        out["fg"] = (fg > 25).fillna(True)
        out["fg_ct"] = (fg < 20).fillna(False)

    # ── 금리 ────────────────────────────────────────────
    if _has("DGS10"):
        out["y10"] = ((m["DGS10"] - m["DGS10"].shift(13)) < 0.6).fillna(True)
    for k, col in (("curve", "T10Y2Y"), ("curve3", "T10Y3M")):
        if _has(col):
            sp = m[col]
            inv = (sp < 0).rolling(78, min_periods=26).max().fillna(0) > 0
            out[k] = ~(inv & (sp > 0)).fillna(False)

    # ── 실물 (ISM 대용) ─────────────────────────────────
    if _has("CFNAI"):
        out["cfnai"] = (m["CFNAI"].rolling(13, min_periods=8).mean()
                        > -0.7).fillna(True)
    if _has("NEWORDER"):
        out["neword"] = (m["NEWORDER"] / m["NEWORDER"].shift(52) - 1 > 0).fillna(True)
    if _has("AWHMAN"):
        out["awh"] = (m["AWHMAN"] - m["AWHMAN"].shift(52) >= -0.1).fillna(True)
    if _has("INDPRO"):
        out["ip"] = (m["INDPRO"] / m["INDPRO"].shift(52) - 1 > 0).fillna(True)

    # ── 노동 ────────────────────────────────────────────
    if _has("UNRATE"):
        ur = m["UNRATE"]
        out["sahm"] = ((ur - ur.rolling(52, min_periods=26).min()) < 0.5).fillna(True)
    if _has("ICSA"):
        ic = m["ICSA"].rolling(4, min_periods=2).mean()
        out["claims"] = (ic / ic.rolling(52, min_periods=26).min() - 1 < 0.15).fillna(True)

    # ── 조합 ────────────────────────────────────────────
    def _and(name, *ks):
        if all(k in out for k in ks):
            r = out[ks[0]]
            for k in ks[1:]:
                r = r & out[k]
            out[name] = r
    _and("x_금융+추세", "nfci", "ma20")
    _and("x_추세+금리", "tmpl", "y10")
    _and("x_실물+추세", "cfnai", "ma20")
    _and("x_노동+추세", "claims", "ma20")
    _and("x_3중", "nfci", "claims", "ma20")
    return {k: v.reindex(spy.index).fillna(True) for k, v in out.items()}


def build():
    print("데이터 적재…", flush=True)
    d = A.load()
    M = A.matrices(d, ["close", "marcap", "adv_20d", "ret_1w", "ACC"])
    px = M["close"]
    g = A.gate_of(M)
    _sp = pd.read_csv(os.path.join(BASE, "data", "leaders_cache", "px_SPY.csv"),
                      index_col=0, parse_dates=True)
    spy = _sp.Close.reindex(px.index).ffill()
    spyv = _sp.Volume.reindex(px.index).ffill()
    print(f"주차 {len(px)} · 신호 {int(g.sum().sum()):,}건", flush=True)

    # 벤치마크
    sy = {}
    for y, gg in spy.groupby(spy.index.year):
        if len(gg) >= 5:
            sy[int(y)] = _r((gg.iloc[-1] / gg.iloc[0] - 1) * 100, 1)
    yrs = (spy.index[-1] - spy.index[0]).days / 365.25
    sdd = (spy / spy.cummax() - 1) * 100
    swk = spy.pct_change().dropna()
    bench = dict(name="SPY 매수보유",
                 cagr=_r(((spy.iloc[-1] / spy.iloc[0]) ** (1 / yrs) - 1) * 100, 1),
                 total=_r((spy.iloc[-1] / spy.iloc[0] - 1) * 100, 1),
                 mdd=_r(sdd.min(), 1), vol=_r(swk.std() * np.sqrt(52) * 100, 1),
                 sharpe=_r(swk.mean() / swk.std() * np.sqrt(52), 2), by_year=sy)

    # ── 시나리오 ────────────────────────────────────────────────
    # 파라미터를 넓게 훑지 않는다. 문헌 값과 그 주변만 본다.
    scen = []
    # ⚠️ 손절은 **기본으로 켠다.** 앞선 실행에서 손절 없는 조합이 MDD −67% 를
    #    냈는데, 그건 실제 운용(종목 −20% 자동 손절)과 다른 조건이었다.
    #    손절을 빼는 경우는 '비교용'으로만 남긴다.
    STOP = 20

    # ① 기준선 — 손절만 있는 등가중
    scen.append(("등가중25 손절20", dict(mode="equal", max_pos=25, stop=STOP)))
    scen.append(("등가중12 손절20", dict(mode="equal", max_pos=12, stop=STOP)))
    scen.append(("등가중25 손절없음(비교)", dict(mode="equal", max_pos=25)))

    # ② 사다리 승급 문턱 — 한 값만 보지 않는다. 뭉쳐 있으면 구조의 힘이다.
    for thr in (5, 10, 15, 25):
        scen.append((f"사다리{thr}% 손절20",
                     dict(mode="ladder", step_thr=thr, max_pos=25, stop=STOP)))
    scen.append(("사다리10% 손절없음(비교)",
                 dict(mode="ladder", step_thr=10, max_pos=25)))

    # ③ 사다리 상한을 낮추면 — MDD 주범이 최상단 20% 인지 본다
    scen.append(("사다리10 상한10% 손절20",
                 dict(mode="ladder", step_thr=10, max_pos=25, stop=STOP,
                      ladder=[1.0, 3.0, 6.0, 10.0])))
    scen.append(("사다리10 상한12% 손절20",
                 dict(mode="ladder", step_thr=10, max_pos=25, stop=STOP,
                      ladder=[1.0, 4.0, 8.0, 12.0])))

    # ④ 분할매도 — 낙폭을 사는 대신 수익을 얼마나 내주나
    scen.append(("사다리10+분할50 손절20",
                 dict(mode="ladder", step_thr=10, max_pos=25, stop=STOP, trim_at=50)))
    scen.append(("등가중25+분할50 손절20",
                 dict(mode="equal", max_pos=25, stop=STOP, trim_at=50)))

    # ⑤ 자리 교체 — 돈이 없을 때 최하위를 파는가
    scen.append(("등가중25 손절20(자리교체)",
                 dict(mode="equal", max_pos=25, stop=STOP, cap_full=True)))
    scen.append(("사다리10 손절20(자리교체)",
                 dict(mode="ladder", step_thr=10, max_pos=25, stop=STOP, cap_full=True)))

    # ⑥ 손절 폭 자체 — 20 이 특별한 값인지 확인
    for st in (10, 15, 30):
        scen.append((f"사다리10 손절{st}",
                     dict(mode="ladder", step_thr=10, max_pos=25, stop=st)))


    # ⑦ 시장 필터 — **전부** 돌린다. 1등만 보지 않기 위해서다.
    REG = regimes(spy, spyv)
    print("")
    print(f"필터 {len(REG)}종 — 각각 회피 구간 비중", flush=True)
    for rk, v in REG.items():
        print(f"    {rk:<14} 회피 {100 - v.mean() * 100:5.1f}%", flush=True)
    for rk in REG:
        scen.append((f"사다리10 +{rk}",
                     dict(mode="ladder", step_thr=10, max_pos=25, stop=STOP,
                          regime=REG[rk], regime_exit=True)))
    # 진입만 막는 판(보유는 유지) — 현금화와 어느 쪽이 나은지 몇 개만 대조
    for rk in ("ma20", "nfci", "tmpl"):
        if rk in REG:
            scen.append((f"사다리10 +{rk} 진입만차단",
                         dict(mode="ladder", step_thr=10, max_pos=25, stop=STOP,
                              regime=REG[rk])))
    for rk in ("ma20", "ma40", "nfci"):
        if rk in REG:
            scen.append((f"등가중25 +{rk}",
                         dict(mode="equal", max_pos=25, stop=STOP,
                              regime=REG[rk], regime_exit=True)))

    # ⑧ 결선 — 민감도를 통과한 것만 조합한다 (2026-09-13 측정)
    #
    #   민감도 검사 = 문턱을 양옆으로 흔든다. **고원이면 구조, 스파이크면 운.**
    #   후보 25종 중 1등을 그냥 고르면 그 1등은 다중비교로 우연히도 나온다.
    #
    #   ✅ 통과 — 긴 지수 이평 (25~52주)
    #        20주 1.6% / 25주 13.8 / 30주 15.7 / 35주 18.9 / 40주 17.2 /
    #        45주 10.5 / 52주 14.7 / 65주 11.4.  25~52주가 통째로 두 자리다.
    #        **짧은 이평(5·10·20주)은 전멸한다** — 1.8 / 0.4 / 1.6%. 휩소로 죽는다.
    #        회피 사건 13회. 40주가 특별한 게 아니라 '긴 이평' 구간이 통한다.
    #   ✅ 통과(조건부) — 10년물 13주 급등 필터
    #        문턱 0.4~1.0%p × 8·13·26주 12칸 중 10칸이 16%+ 다. 사건 10회.
    #        다만 **MDD 를 못 줄인다**(−46~−61%). 수익만 올린다.
    #        ⚠️ 표본에 금리 인상 사이클이 **한 번**뿐이다. 제로금리 10년엔 안 켜진다.
    #   ⚠️ 보류 — Fear&Greed 대용
    #        문턱 15~40 에서 10.5~22.8% 로 튄다. 고원이 아니다. 사건 6회로 표본도 적다.
    #        단 2024·2025 성적이 유일하게 좋다(+32.6 / +28.3). 근거는 약하고 결과는 좋다.
    #   ❌ 탈락 — 신규실업수당(claims)
    #        +15% 에서만 25.6%, 양옆은 +10% −4.2% / +20% 10.7%. **전형적인 스파이크.**
    #        2차 측정에서 2등이었는데 민감도에서 가짜로 판명됐다. 쓰지 않는다.
    #   ❌ 탈락 — cfnai(MDD −75.4%, 무필터보다 나쁨), tmpl(−7.4%), 조합 AND 4종
    #        (현금 43~72% 로 상승장을 통째로 버린다), fg_ct 역발상(현금 97.7%).
    #   ❌ 탈락 — 삼의 법칙·산업생산·하이일드: 침체 **확인** 지표라 매매엔 느리다.
    #
    #   ⚠️ 이 필터가 치르는 값 — V자 반등에서 반드시 늦는다.
    #      무필터 2020년 +177.2% 가 ma40 에서는 +60.9% 로 깎인다. 3분의 1이다.
    #      낙폭을 줄이는 대가로 바닥 반등의 3분의 2를 내준다. 공짜가 아니다.
    _ma = lambda n: (spy > spy.rolling(n, min_periods=max(4, n // 2)).mean()).fillna(True)
    _y10 = REG.get("y10")
    for n in (35, 40, 52):
        if _y10 is not None:
            scen.append((f"◆결선 ma{n}+y10", dict(mode="ladder", step_thr=10, max_pos=25,
                                                 stop=STOP, regime=_ma(n) & _y10,
                                                 regime_exit=True)))
    if "fg" in REG:
        scen.append(("◆결선 ma40+fg", dict(mode="ladder", step_thr=10, max_pos=25,
                                          stop=STOP, regime=_ma(40) & REG["fg"],
                                          regime_exit=True)))

    rows = []
    for name, kw in scen:
        r = run(px, g, spy, **kw)
        r["name"] = name
        rows.append(r)
        # 과최적화 감시 — 전 구간 총수익이 아니라 **연도별로 흩어지는지**를 같이 본다.
        by = [v for v in r["by_year"].values() if v is not None]
        bench_by = bench["by_year"]
        win = sum(1 for y, v in r["by_year"].items()
                  if v is not None and bench_by.get(y) is not None and v > bench_by[y])
        tot = sum(1 for y, v in r["by_year"].items()
                  if v is not None and bench_by.get(y) is not None)
        r["yr_win"] = f"{win}/{tot}"
        r["yr_med"] = _r(float(np.median(by)), 1) if by else None
        r["yr_worst"] = _r(min(by), 1) if by else None
        _f = lambda k: (f"{r[k]:.1f}" if r.get(k) is not None else "-")
        print(f"  {name:<24} CAGR {_f('cagr'):>6}%  MDD {_f('mdd'):>7}%  "
              f"연중앙 {_f('yr_med'):>6}%  최악해 {_f('yr_worst'):>7}%  "
              f"SPY이긴해 {r['yr_win']:>5}  현금 {_f('avg_cash'):>5}%", flush=True)

    out = dict(generated=str(pd.Timestamp.today().date()),
               cost=COST, ladder=LADDER, bench=bench, scenarios=rows)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n벤치마크 SPY  CAGR {bench['cagr']}%  MDD {bench['mdd']}%")
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(build())
