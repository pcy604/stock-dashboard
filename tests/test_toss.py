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


def test_vault_remote_roundtrip(monkeypatch, tmp_path):
    """2026-10-26: 봉인본은 Supabase vaults 표에서 읽는다 — 공개 git 에 두지 않는다."""
    import requests
    monkeypatch.setenv("STORE_URL", "https://x.supabase.co/rest/v1")
    monkeypatch.setenv("STORE_KEY", "sb_secret_test")
    store, seen = {}, []

    class R:
        def __init__(s, code, data=None): s.status_code, s._d, s.text = code, data, ""
        def json(s): return s._d
        def raise_for_status(s):
            if s.status_code >= 300: raise RuntimeError(s.status_code)

    def post(url, json=None, headers=None, timeout=None):
        seen.append(url); store["toss"] = json[0]["blob"]; return R(201)

    def get(url, params=None, headers=None, timeout=None):
        return R(200, [{"blob": store["toss"]}] if "toss" in store else [])

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(pf_vault, "VAULT_PATH", tmp_path / "none.vault")   # v2 파일이 없는 경우의 폴백 경로
    pf_vault._CACHE.update(t=0.0, doc=None)
    assert pf_vault.peek() is None
    p = tmp_path / "t.enc"
    pf_vault.seal({"asof": "2026-10-26 08:00", "accounts": [{"x": 1}]}, "correct-horse", p)
    pf_vault.push(p)
    assert seen == ["https://x.supabase.co/rest/v1/vaults"]          # /rest/v1 중복 없음
    assert pf_vault.peek()["asof"] == "2026-10-26 08:00"
    assert pf_vault.unseal("correct-horse")["accounts"] == [{"x": 1}]
    with pytest.raises(ValueError):
        pf_vault.unseal("wrong-password")


def test_vault_v2_wrap_unwrap(tmp_path):
    """2026-10-26: 공개키 이중 봉인 — 노트북은 공개키만, 개인키 없이는 겉을 못 연다."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub, pem = tmp_path / "pub.pem", k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                    serialization.NoEncryption())
    pub.write_bytes(k.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    inner = tmp_path / "t.enc"
    pf_vault.seal({"asof": "2026-10-26 09:00", "accounts": [{"y": 2}]}, "correct-horse", inner)
    v = pf_vault.wrap(inner, tmp_path / "t.vault", pub)
    doc = json.loads(v.read_text(encoding="utf-8"))
    assert doc["v"] == 2 and doc["asof"] == "2026-10-26 09:00" and "token" not in doc   # 속 봉인본이 겉에 안 보인다
    pf_vault._PRIV["k"] = None
    d1 = pf_vault.unwrap(doc, pem)
    pf_vault._PRIV["k"] = None
    assert d1 == json.loads(inner.read_text(encoding="utf-8"))
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    with pytest.raises(Exception):
        pf_vault.unwrap(doc, other)                                                    # 다른 키로는 못 연다
    pf_vault._PRIV["k"] = None
