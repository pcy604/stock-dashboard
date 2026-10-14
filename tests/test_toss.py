# -*- coding: utf-8 -*-
"""토스 조회 클라이언트·암호 보관 — 네트워크 없이 가짜 응답으로."""
import json, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pf_vault
from executor.broker_toss import TossReader, TossError


class _R:
    def __init__(self, code, body):
        self.status_code, self._b = code, body
        self.text = json.dumps(body)

    def json(self):
        return self._b


class _S:
    """경로별 응답 큐. 호출 기록을 남긴다."""
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def _pick(self, url, **k):
        self.calls.append((url, k))
        for path, resp in self.routes.items():
            if url.endswith(path):
                return resp.pop(0) if isinstance(resp, list) else resp
        raise AssertionError(url)

    post = get = _pick


HOLD = {"result": {"items": [
    {"symbol": "005930", "name": "삼성전자", "marketCountry": "KR", "currency": "KRW", "quantity": "10",
     "lastPrice": "70000", "averagePurchasePrice": "65000",
     "marketValue": {"purchaseAmount": "650000", "amount": "700000"}, "profitLoss": {"rate": "0.0769"}},
    {"symbol": "SATL", "name": "Satellogic", "marketCountry": "US", "currency": "USD", "quantity": "14200",
     "lastPrice": "3.1", "averagePurchasePrice": "2.5",
     "marketValue": {"purchaseAmount": "35500", "amount": "44020"}, "profitLoss": {"rate": "0.24"}}]}}


def _routes():
    return {"/oauth2/token": _R(200, {"access_token": "T", "token_type": "Bearer", "expires_in": 86400}),
            "/api/v1/accounts": _R(200, {"result": [{"accountNo": "12345678901", "accountSeq": 7, "accountType": "BROKERAGE"}]}),
            "/api/v1/holdings": _R(200, HOLD),
            "/api/v1/buying-power": [_R(200, {"result": {"currency": "KRW", "cashBuyingPower": "1500000"}}),
                                     _R(200, {"result": {"currency": "USD", "cashBuyingPower": "120.5"}})]}


def test_snapshot_parses_strings_and_masks_account(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    s = _S(_routes())
    snap = TossReader("id", "sec", session=s, token_cache=tmp_path / "tok").snapshot()
    a = snap["accounts"][0]
    assert a["no_masked"].endswith("8901") and "1234567" not in a["no_masked"]
    h = {x["sym"]: x for x in a["holdings"]}
    assert h["005930"]["qty"] == 10.0 and h["005930"]["market"] == "KR"
    assert h["SATL"]["currency"] == "USD" and abs(h["SATL"]["pnl_pct"] - 24.0) < 1e-9
    assert a["cash"] == {"KRW": 1500000.0, "USD": 120.5}
    # 계좌 헤더는 accountSeq (accountNo 아님)
    hdrs = [k.get("headers", {}) for u, k in s.calls if "holdings" in u][0]
    assert hdrs["X-Tossinvest-Account"] == "7"
    # 토큰은 form 으로
    tok = [k for u, k in s.calls if u.endswith("/oauth2/token")][0]
    assert tok["data"]["grant_type"] == "client_credentials"


def test_403_explains_ip_allowlist(tmp_path):
    s = _S({"/oauth2/token": _R(200, {"access_token": "T", "expires_in": 60}),
            "/api/v1/accounts": _R(403, {"error": "forbidden"})})
    with pytest.raises(TossError, match="허용 IP"):
        TossReader("id", "sec", session=s, token_cache=tmp_path / "tok").accounts()


def test_vault_roundtrip_and_wrong_password(tmp_path):
    p = tmp_path / "x.enc"
    pf_vault.seal({"asof": "2026-10-14 06:40", "accounts": [{"x": 1}]}, "correct-horse", p)
    raw = p.read_text()
    assert "accounts" not in raw and "correct-horse" not in raw      # 평문 노출 없음
    assert pf_vault.peek(p)["asof"] == "2026-10-14 06:40"
    assert pf_vault.unseal("correct-horse", p)["accounts"] == [{"x": 1}]
    with pytest.raises(ValueError):
        pf_vault.unseal("wrong-password", p)
