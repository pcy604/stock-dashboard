# -*- coding: utf-8 -*-
"""내 계좌 스냅샷 암호화 보관 — 공개 저장소에 올려도 비밀번호 없이는 못 읽게.

왜 (2026-10-14)
  저장소(github.com/pcy604/stock-dashboard)와 사이트는 **공개**다. 토스 잔고를 그대로
  커밋하면 보유 종목·금액이 전부 공개된다. 그래서 노트북이 암호화해서 올리고,
  사이트는 사용자가 입력한 비밀번호로만 푼다. 사이트·GitHub 어디에도 키를 두지 않는다.

  암호: PBKDF2-HMAC-SHA256(비밀번호, 랜덤 salt, 390,000회) → Fernet(AES-128-CBC + HMAC).
  파일: {"v":1, "salt":b64, "iter":n, "token":fernet토큰, "asof":"YYYY-MM-DD HH:MM"}
        asof 만 평문 — 사이트가 비밀번호 전에 '언제 자료인지'는 보여줄 수 있게.

2026-10-26 — 저장 위치를 공개 git → Supabase `vaults` 표로 옮겼다
  암호화돼 있어도 공개 저장소에 있으면 누구나 내려받아 비밀번호를 **오프라인으로 무한 대입**할 수 있다.
  그래서 봉인된 문서를 Supabase(BUZA_ALARM 프로젝트) `vaults` 표 name='toss' 행에 둔다.
  표는 RLS 켜고 정책 없음 → anon 키로는 안 보이고 service_role 키로만 읽고 쓴다(user_store 와 같은 [store] 설정).
  - 노트북(toss_sync): seal() 로 로컬 사본(data/portfolio_toss.enc, gitignore) → push() 로 업로드.
  - 사이트: peek()/unseal() 이 Supabase 를 먼저 읽고, 설정이 없을 때만 로컬 파일로 폴백.
  [store] 설정 찾는 순서: 환경변수 STORE_URL/STORE_KEY → st.secrets['store'] → .streamlit/secrets.toml
"""
import base64, json, os, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENC_PATH = ROOT / "data" / "portfolio_toss.enc"
_ITER = 390_000
_TABLE = "vaults"
_NAME = "toss"
_CACHE = {"t": 0.0, "doc": None}      # 화면이 다시 그릴 때마다 DB 를 치지 않게(60초)
_TTL = 60


def _key(password: str, salt: bytes, it: int) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=it)
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


# ── Supabase 설정 ──────────────────────────────────────────────────────────────
def _store_cfg():
    """{'url','key'} 또는 None. 비밀값은 출력하지 않는다."""
    u, k = os.environ.get("STORE_URL", "").strip(), os.environ.get("STORE_KEY", "").strip()
    if u and k:
        return {"url": u, "key": k}
    try:
        import streamlit as st
        s = st.secrets.get("store")
        if s and s.get("url") and s.get("key"):
            return {"url": str(s["url"]), "key": str(s["key"])}
    except Exception:
        pass
    try:
        import tomllib
        p = ROOT / ".streamlit" / "secrets.toml"
        if p.exists():
            s = tomllib.loads(p.read_text(encoding="utf-8")).get("store") or {}
            if s.get("url") and s.get("key"):
                return {"url": str(s["url"]), "key": str(s["key"])}
    except Exception:
        pass
    return None


def remote_ready() -> bool:
    return _store_cfg() is not None


def _h(c, extra=None):
    h = {"apikey": c["key"], "Content-Type": "application/json"}
    if c["key"].startswith("eyJ"):        # 옛 JWT 키만 Bearer — 새 sb_secret_ 키는 apikey 헤더만 (user_store 와 동일)
        h["Authorization"] = f"Bearer {c['key']}"
    h.update(extra or {})
    return h


def _url(c):
    base = c["url"].strip().rstrip("/")
    for suf in ("/rest/v1", "/rest"):
        if base.endswith(suf):
            base = base[: -len(suf)]
    return base + f"/rest/v1/{_TABLE}"


def push(path: Path = ENC_PATH) -> None:
    """로컬 봉인 파일을 Supabase 로 올린다. 설정이 없거나 실패하면 예외(RuntimeError)."""
    import requests
    c = _store_cfg()
    if c is None:
        raise RuntimeError("[store] 설정 없음 — .streamlit/secrets.toml 의 [store] url·key 또는 STORE_URL/STORE_KEY")
    raw = Path(path).read_text(encoding="utf-8")
    asof = json.loads(raw).get("asof")
    r = requests.post(_url(c), json=[{"name": _NAME, "blob": raw, "asof": asof,
                                      "updated_at": datetime.now(timezone.utc).isoformat()}],
                      headers=_h(c, {"Prefer": "resolution=merge-duplicates,return=minimal"}), timeout=10)
    if r.status_code >= 300:
        raise RuntimeError(f"Supabase 업로드 실패 HTTP {r.status_code} {r.text[:120]}")
    _CACHE.update(t=0.0, doc=None)


def _fetch_remote():
    """Supabase 의 봉인 문서(dict) 또는 None(행 없음). 설정 없음도 None."""
    c = _store_cfg()
    if c is None:
        return None
    now = time.time()
    if _CACHE["doc"] is not None and now - _CACHE["t"] < _TTL:
        return _CACHE["doc"]
    import requests
    r = requests.get(_url(c), params={"name": f"eq.{_NAME}", "select": "blob"}, headers=_h(c), timeout=6)
    r.raise_for_status()
    rows = r.json()
    doc = json.loads(rows[0]["blob"]) if rows else None
    _CACHE.update(t=now, doc=doc)
    return doc


def _load_doc(path: Path):
    """원격 우선, 원격 설정이 없을 때만 로컬 파일. 경로를 직접 주면(테스트) 그 파일만 본다."""
    if Path(path) == ENC_PATH and remote_ready():
        return _fetch_remote()
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


# ── 봉인·해제 ─────────────────────────────────────────────────────────────────
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
    """비밀번호 없이 보이는 머리말(asof) — 자료가 없거나 읽기 실패면 None."""
    try:
        d = _load_doc(path)
        return {"asof": d.get("asof"), "v": d.get("v")} if d else None
    except Exception:
        return None


def unseal(password: str, path: Path = ENC_PATH) -> dict:
    """틀린 비밀번호면 ValueError. 자료가 없으면 FileNotFoundError."""
    from cryptography.fernet import Fernet, InvalidToken
    d = _load_doc(path)
    if not d:
        raise FileNotFoundError("저장된 계좌 스냅샷이 없습니다 — 노트북에서 tools/toss_sync.py 실행")
    k = _key(password or "", base64.b64decode(d["salt"]), int(d["iter"]))
    try:
        return json.loads(Fernet(k).decrypt(d["token"].encode()).decode("utf-8"))
    except InvalidToken:
        raise ValueError("비밀번호가 맞지 않습니다")
