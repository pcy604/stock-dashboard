"""tools/known_answers — 정답 점검이 실제 결손을 잡는가 (2026-10-19)"""
import json
import shutil
from datetime import date

import pandas as pd
import pytest

import tools.known_answers as K


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """커밋된 산출물 복사본 위에서 점검을 돌린다 — 일부러 망가뜨려 잡히는지 본다."""
    root = K.BASE
    for rel in ['data/us_marketcap.csv', 'data/us_shares.csv', 'data/krx_listing_last.csv', 'data/sectors.json',
                'data/kr_fundamentals_q.parquet', 'results/leaders_accel.json']:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(f"{root}/{rel}", tmp_path / rel)
    monkeypatch.setattr(K, 'BASE', str(tmp_path))
    return tmp_path


def _one(question_part):
    for area, q, fn in K.CHECKS:
        if question_part in q:
            return fn()
    raise KeyError(question_part)


def test_detects_missing_megacap(repo):
    p = repo / 'data/us_marketcap.csv'
    m = pd.read_csv(p)
    m[~m.Symbol.astype(str).str[0].isin(list('STUVWXYZ'))].to_csv(p, index=False)   # 10-19 사고 재현
    ok, detail = _one('초대형주 20종')
    assert not ok and 'TSLA' in detail
    ok, detail = _one('첫 글자')
    assert not ok and 'S' in detail


def test_detects_future_quarter(repo, monkeypatch):
    p = repo / 'data/kr_fundamentals_q.parquet'
    q = pd.read_parquet(p)
    extra = q.iloc[[0]].copy()
    extra['year'], extra['q'] = date.today().year + 1, 4
    pd.concat([q, extra]).to_parquet(p)
    ok, _ = _one('미래 분기')
    assert not ok


def test_detects_lost_era_leader(repo):
    p = repo / 'results/leaders_accel.json'
    d = json.load(open(p, encoding='utf-8'))
    d['weeks'] = {k: [r for r in v if r['sym'] != 'NVDA'] for k, v in d['weeks'].items()}   # 시총 NULL 사고 재현
    json.dump(d, open(p, 'w', encoding='utf-8'))
    ok, detail = _one('시대의 주도주')
    assert not ok and "'NVDA': 0" in detail


def test_due_quarter():
    K.TODAY = date(2026, 10, 19)
    assert K._q_due() == (2026, 2)      # Q3 분기보고서 마감(11/14) 전
    K.TODAY = date(2026, 3, 1)
    assert K._q_due() == (2025, 3)      # 사업보고서(3/31) 전이면 Q4 를 요구하지 않는다
    K.TODAY = date.today()
