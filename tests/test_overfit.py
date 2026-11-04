"""과적합 판정(DSR·PBO) 정답 점검 — 답을 아는 가짜 데이터로."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))
import overfit as of  # noqa: E402


def test_noise_only_is_flagged():
    # 진짜 실력 0 인 조합 200개 → 최고 샤프도 운, PBO 는 0.5 근처, DSR 낮음
    rng = np.random.default_rng(7)
    m = rng.normal(0, 0.02, (600, 200))
    sr = of.sharpe(m)
    best = int(np.argmax(sr))
    d = of.dsr(m[:, best], sr)
    assert d["psr0"] > 0.9            # 보정 전엔 그럴듯해 보인다
    assert d["dsr"] < 0.8             # 보정 후엔 아니다
    p = of.pbo(m, s=8)
    assert 0.3 <= p["pbo"] <= 0.7
    assert of.verdict(d["dsr"], p["pbo"]) == "❌ 과적합 의심"


def test_real_edge_passes():
    # 한 조합만 진짜 우위(주간 SR 0.3) → 보정해도 살아남고 PBO 낮음
    rng = np.random.default_rng(11)
    m = rng.normal(0, 0.02, (600, 100))
    m[:, 5] += 0.006
    sr = of.sharpe(m)
    best = int(np.argmax(sr))
    assert best == 5
    d = of.dsr(m[:, best], sr)
    p = of.pbo(m, s=8)
    assert d["dsr"] > 0.99
    assert p["pbo"] < 0.1
    assert of.verdict(d["dsr"], p["pbo"]) == "✅ 통과"


def test_expected_max_matches_simulation():
    # SR0 공식이 '노이즈 N개 중 최대 샤프'의 평균과 맞는가 (±25%)
    rng = np.random.default_rng(3)
    maxes, sr0s = [], []
    for _ in range(30):
        m = rng.normal(0, 1, (300, 100))
        sr = of.sharpe(m)
        maxes.append(sr.max())
        sr0s.append(of.expected_max_sharpe(sr))
    assert abs(np.mean(sr0s) / np.mean(maxes) - 1) < 0.25


def test_psr_basic():
    rng = np.random.default_rng(1)
    assert of.psr(rng.normal(0.01, 0.02, 500), 0.0) > 0.99
    assert of.psr(rng.normal(-0.01, 0.02, 500), 0.0) < 0.01


def test_verdict_thresholds():
    assert of.verdict(0.95, 0.25) == "✅ 통과"
    assert of.verdict(0.94, 0.10) == "△ 경계"
    assert of.verdict(0.99, 0.51) == "❌ 과적합 의심"
    assert of.verdict(0.79, 0.10) == "❌ 과적합 의심"
