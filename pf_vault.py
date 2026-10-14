# -*- coding: utf-8 -*-
"""내 계좌 스냅샷 암호화 보관 — 공개 저장소에 올려도 비밀번호 없이는 못 읽게.

왜 (2026-10-14)
  저장소(github.com/pcy604/stock-dashboard)와 사이트는 **공개**다. 토스 잔고를 그대로
  커밋하면 보유 종목·금액이 전부 공개된다. 그래서 노트북이 암호화해서 올리고,
  사이트는 사용자가 입력한 비밀번호로만 푼다. 사이트·GitHub 어디에도 키를 두지 않는다.

  암호: PBKDF2-HMAC-SHA256(비밀번호, 랜덤 salt, 390,000회) → Fernet(AES-128-CBC + HMAC).
  파일: {"v":1, "salt":b64, "iter":n, "token":fernet토큰, "asof":"YYYY-MM-DD HH:MM"}
        asof 만 평문 — 사이트가 비밀번호 전에 '언제 자료인지'는 보여줄 수 있게.
"""
import base64, json, os
from pathlib import Path

ENC_PATH = Path(__file__).resolve().parent / "data" / "portfolio_toss.enc"
_ITER = 390_000


def _key(password: str, salt: bytes, it: int) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=it)
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def seal(obj: dict, password: str, path: Path = ENC_PATH) -> Path:
    from cryptography.fernet import Fernet
    if not password:
        raise ValueError("비밀번호가 비어 있다")
    salt = os.urandom(16)
    tok = Fernet(_key(password, salt, _ITER)).encrypt(
        json.dumps(obj, ensure_ascii=False).encode("utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"v": 1, "salt": base64.b64encode(salt).decode(), "iter": _ITER,
                                "token": tok.decode(), "asof": obj.get("asof")}), encoding="utf-8")
    return path


def peek(path: Path = ENC_PATH) -> dict | None:
    """비밀번호 없이 보이는 머리말(asof) — 파일이 없으면 None."""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return {"asof": d.get("asof"), "v": d.get("v")}
    except Exception:
        return None


def unseal(password: str, path: Path = ENC_PATH) -> dict:
    """틀린 비밀번호면 ValueError."""
    from cryptography.fernet import Fernet, InvalidToken
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    k = _key(password or "", base64.b64decode(d["salt"]), int(d["iter"]))
    try:
        return json.loads(Fernet(k).decrypt(d["token"].encode()).decode("utf-8"))
    except InvalidToken:
        raise ValueError("비밀번호가 맞지 않습니다")
