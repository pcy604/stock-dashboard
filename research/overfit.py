"""조합 실험 과적합 판정 — DSR(Deflated Sharpe Ratio) · PBO(CSCV).

사전 등록: research/overfit_prereg_2026-11-04.md
- dsr(): Bailey & López de Prado (2014) "The Deflated Sharpe Ratio"
- pbo(): Bailey, Borwein, López de Prado, Zhu (2017) "The Probability of Backtest Overfitting"
- audit(): 저장된 조합 실험(curves)을 읽어 두 값을 계산 → results/overfit_audit.json

실행: python research/overfit.py
"""
from __future__ import annotations

import itertools
import json
import math
import os
from statistics import NormalDist

import numpy as np

_N = NormalDist()
EULER = 0.5772156649015329
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── 기본 통계 ───────────────────────────────────────────────
def sharpe(r: np.ndarray, axis=0) -> np.ndarray:
    """주간(비연환산) 샤프. 표준편차 0 이면 0."""
    r = np.asarray(r, float)
    mu = r.mean(axis=axis)
    sd = r.std(axis=axis, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(sd > 0, mu / sd, 0.0)
    return out


def _skew_kurt(r: np.ndarray) -> tuple[float, float]:
    r = np.asarray(r, float)
    d = r - r.mean()
    m2 = (d ** 2).mean()
    if m2 <= 0:
        return 0.0, 3.0
    return float((d ** 3).mean() / m2 ** 1.5), float((d ** 4).mean() / m2 ** 2)


def expected_max_sharpe(sr_trials: np.ndarray) -> float:
    """N 개를 시도했을 때 운만으로 기대되는 최대 샤프 SR0."""
    sr = np.asarray(sr_trials, float)
    n = len(sr)
    if n < 2:
        return 0.0
    v = sr.var(ddof=1)
    z1 = _N.inv_cdf(1 - 1.0 / n)
    z2 = _N.inv_cdf(1 - 1.0 / (n * math.e))
    return float(math.sqrt(v) * ((1 - EULER) * z1 + EULER * z2))


def psr(r: np.ndarray, sr_star: float = 0.0) -> float:
    """Probabilistic Sharpe Ratio: 진짜 샤프가 sr_star 보다 클 확률."""
    r = np.asarray(r, float)
    t = len(r)
    sr = float(sharpe(r))
    g3, g4 = _skew_kurt(r)
    den = 1 - g3 * sr + (g4 - 1) / 4 * sr ** 2
    if t < 3 or den <= 0:
        return float("nan")
    return float(_N.cdf((sr - sr_star) * math.sqrt(t - 1) / math.sqrt(den)))


def dsr(r_selected: np.ndarray, sr_trials: np.ndarray) -> dict:
    """고른 전략의 수익률과, 시도한 전체 조합의 샤프 목록으로 DSR 계산."""
    sr0 = expected_max_sharpe(sr_trials)
    return {
        "sr": round(float(sharpe(r_selected)), 4),
        "sr0": round(sr0, 4),
        "n_trials": int(len(sr_trials)),
        "psr0": round(psr(r_selected, 0.0), 4),  # 다중 시도 보정 전
        "dsr": round(psr(r_selected, sr0), 4),   # 보정 후
    }


# ── PBO (CSCV) ──────────────────────────────────────────────
def pbo(m: np.ndarray, s: int = 16) -> dict:
    """m: (T 주 × N 조합) 수익률 행렬. 기간을 s 조각으로 나눠 C(s, s/2) 가지 전부.

    각 경우: 앞 절반 조각(IS)에서 샤프 최고 조합을 고르고, 나머지(OOS)에서
    그 조합의 상대 순위 w(0~1) → logit. PBO = logit ≤ 0 비율(= OOS 중앙값 이하).
    """
    m = np.asarray(m, float)
    t, n = m.shape
    t_use = (t // s) * s
    m = m[t - t_use:]                       # 앞쪽을 잘라 균등 조각
    blocks = np.array_split(np.arange(t_use), s)
    bl = len(blocks[0])
    # 조각별 합·제곱합 → 어떤 조합의 조각도 빠르게 샤프 계산
    s1 = np.stack([m[b].sum(0) for b in blocks])        # (s, n)
    s2 = np.stack([(m[b] ** 2).sum(0) for b in blocks])

    def _sr(idx):
        k = len(idx) * bl
        a, b = s1[list(idx)].sum(0), s2[list(idx)].sum(0)
        mu = a / k
        var = (b - k * mu ** 2) / (k - 1)
        sd = np.sqrt(np.clip(var, 0, None))
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(sd > 0, mu / sd, 0.0)

    logits, oos_of_best, degr = [], [], []
    all_idx = range(s)
    for is_idx in itertools.combinations(all_idx, s // 2):
        oos_idx = tuple(i for i in all_idx if i not in is_idx)
        sr_is, sr_oos = _sr(is_idx), _sr(oos_idx)
        best = int(np.argmax(sr_is))
        # OOS 상대 순위 (1 = 최고). 동률은 평균 순위
        rank = (sr_oos < sr_oos[best]).sum() + 0.5 * ((sr_oos == sr_oos[best]).sum() - 1) + 1
        w = rank / (n + 1)
        logits.append(math.log(w / (1 - w)))
        oos_of_best.append(sr_oos[best])
        degr.append((sr_is[best], sr_oos[best]))
    logits = np.array(logits)
    d = np.array(degr)
    slope = float(np.polyfit(d[:, 0], d[:, 1], 1)[0]) if len(d) > 2 else float("nan")
    return {
        "pbo": round(float((logits <= 0).mean()), 4),
        "splits": len(logits),
        "blocks": s,
        "logit_median": round(float(np.median(logits)), 3),
        "oos_sr_best_median": round(float(np.median(oos_of_best)), 4),
        "oos_sr_best_neg": round(float((np.array(oos_of_best) <= 0).mean()), 4),
        "is_oos_slope": round(slope, 3),   # IS 샤프가 오를 때 OOS 샤프가 따라오는 정도(1 = 그대로, ≤0 = 무관·역행)
    }


# ── 판정 ────────────────────────────────────────────────────
def verdict(dsr_v: float, pbo_v: float) -> str:
    """사전 등록 합격선."""
    if dsr_v >= 0.95 and pbo_v <= 0.25:
        return "✅ 통과"
    if dsr_v >= 0.80 and pbo_v <= 0.50:
        return "△ 경계"
    return "❌ 과적합 의심"


def curves_to_returns(curves: dict, keys: list[str]) -> np.ndarray:
    lv = np.array([curves[k] for k in keys], float).T   # (T+1, N)
    return lv[1:] / lv[:-1] - 1


def judge(curves: dict, keys: list[str], spy_curve: list[float], meta: dict) -> dict:
    r = curves_to_returns(curves, keys)
    spy = np.array(spy_curve, float)
    spy_r = spy[1:] / spy[:-1] - 1
    out = {}
    for name, m in (("excess", r - spy_r[:, None]), ("absolute", r)):
        sr_all = sharpe(m)
        best = int(np.argmax(sr_all))
        dd = dsr(m[:, best], sr_all)
        pp = pbo(m)
        out[name] = {
            # 계열 전체: '어느 조합을 고르든' 우위가 있는가 (고르기 효과와 분리)
            "family_sr_pos_share": round(float((sr_all > 0).mean()), 3),
            "family_sr_median": round(float(np.median(sr_all)), 4),
            "family_avg_psr": round(psr(m.mean(1), 0.0), 4),
            "best_key": keys[best],
            "best_meta": meta.get(keys[best], {}),
            **dd,
            **pp,
            "verdict": verdict(dd["dsr"], pp["pbo"]),
        }
    return out


EXPERIMENTS = [
    ("robust_rs", "RS 강건성 (RS 3 × 슬롯 3 × 청산 16)"),
    ("loss_cut_grid", "래칫·재매수·냉각·불타기"),
    ("pyramid_grid", "불타기 재검증"),
]


def audit(write: bool = True) -> dict:
    res = {"prereg": "research/overfit_prereg_2026-11-04.md", "experiments": {}}
    for f, title in EXPERIMENTS:
        d = json.load(open(os.path.join(ROOT, "results", f + ".json"), encoding="utf-8"))
        keys = [g["key"] for g in d["grid"]]
        meta = {g["key"]: {k: g.get(k) for k in ("CAGR", "MDD", "Sharpe")} for g in d["grid"]}
        j = judge(d["curves"], keys, d["spy"]["curve"], meta)
        res["experiments"][f] = {"title": title, "n": len(keys), "weeks": len(d["dates"]),
                                 "run": d.get("run"), **j}
    if write:
        with open(os.path.join(ROOT, "results", "overfit_audit.json"), "w", encoding="utf-8") as fp:
            json.dump(res, fp, ensure_ascii=False, indent=1)
    return res


if __name__ == "__main__":
    r = audit()
    for f, e in r["experiments"].items():
        x = e["excess"]
        print(f"{f:14s} N={e['n']:4d} | 초과: 최고 {x['best_key']} SR {x['sr']} SR0 {x['sr0']} "
              f"PSR {x['psr0']} DSR {x['dsr']} PBO {x['pbo']} → {x['verdict']}")
        a = e["absolute"]
        print(f"{'':14s}        | 절대: 최고 {a['best_key']} DSR {a['dsr']} PBO {a['pbo']} → {a['verdict']}")
