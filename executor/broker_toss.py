"""토스증권 Open API — 지금은 **읽기 전용**(계좌·보유·현금). 실주문은 P2 에서.

확인된 사양(2026-10, 원칙 v1 §8 + 공개 가이드 대조):
  · 토큰  POST /oauth2/token  form(grant_type=client_credentials, client_id, client_secret)
          → {access_token, token_type:"Bearer", expires_in}   (24시간)
  · 계좌  GET /api/v1/accounts → result[]{accountNo, accountSeq, accountType}
          이후 모든 계좌 요청 헤더 X-Tossinvest-Account: accountSeq (accountNo 아님)
  · 보유  GET /api/v1/holdings → result{items[]{symbol,name,marketCountry,currency,quantity,
          lastPrice,averagePurchasePrice,marketValue{purchaseAmount,amount},profitLoss{rate}},
          krw/usd 요약}. 금액·수량은 **문자열**, rate 는 소수(0.1077=10.77%). 현금 미포함.
  · 현금  GET /api/v1/buying-power?currency=KRW|USD → result{currency, cashBuyingPower}
  · 주문  POST /api/v1/orders … (P2)
  · 요청 한도: 계좌 초당 1건 · 자산 초당 5건 · 주문정보 초당 6건(국내 09:00~09:10 3건)
  · ⚠️ **허용 IP 등록 필수**(미등록 403). 고정 IP 에서만 부를 수 있다 →
       Streamlit Cloud·GitHub Actions(유동 IP)에서는 못 부른다. 노트북에서 부른다.
  · ⚠️ 키에 '조회 전용' 권한 구분이 없다 — client_secret 이 새면 주문까지 가능.
       그래서 키는 노트북 data/.toss_* (gitignore) 에만 둔다.
  · 모의투자 없음 → broker_paper 로 P1 을 대신한다
"""
import json, time
from pathlib import Path

BASE = "https://openapi.tossinvest.com"
_ROOT = Path(__file__).resolve().parent.parent
_TOKEN_CACHE = _ROOT / "data" / ".toss_token"


def _num(x):
    try:
        return float(x) if x not in (None, "") else None
    except (TypeError, ValueError):
        return None


class TossError(RuntimeError):
    pass


class TossReader:
    """읽기 전용 클라이언트. session 주입은 테스트용."""

    def __init__(self, client_id: str, client_secret: str, session=None, token_cache: Path = _TOKEN_CACHE):
        if not client_id or not client_secret:
            raise TossError("토스 client_id / client_secret 이 없습니다")
        import requests
        self.cid, self.secret = client_id, client_secret
        self.s = session or requests.Session()
        self.cache = token_cache
        self._tok = None
        self._last_acct_call = 0.0

    # ── 인증 ──────────────────────────────────────────────────────────
    def token(self) -> str:
        if self._tok:
            return self._tok
        try:
            c = json.loads(self.cache.read_text())
            if c.get("cid") == self.cid and c.get("exp", 0) > time.time() + 300:
                self._tok = c["access_token"]
                return self._tok
        except Exception:
            pass
        r = self.s.post(BASE + "/oauth2/token", timeout=15, data={
            "grant_type": "client_credentials", "client_id": self.cid, "client_secret": self.secret})
        if r.status_code != 200:
            raise TossError(self._why(r, "토큰 발급"))
        d = r.json()
        self._tok = d["access_token"]
        try:
            self.cache.parent.mkdir(parents=True, exist_ok=True)
            self.cache.write_text(json.dumps({"cid": self.cid, "access_token": self._tok,
                                              "exp": time.time() + float(d.get("expires_in") or 3600)}))
        except Exception:
            pass
        return self._tok

    @staticmethod
    def _why(r, what):
        hint = {401: "키가 틀렸거나 만료", 403: "허용 IP 미등록일 가능성 큼 — 토스 설정 › Open API › 허용 IP 에 이 PC 공인 IP 등록",
                429: "요청 한도 초과"}.get(r.status_code, "")
        return f"{what} 실패 HTTP {r.status_code} {hint} · {r.text[:200]}"

    def _get(self, path, account=None, params=None, what=""):
        h = {"Authorization": f"Bearer {self.token()}"}
        if account is not None:
            h["X-Tossinvest-Account"] = str(account)
        for attempt in range(3):
            r = self.s.get(BASE + path, headers=h, params=params, timeout=15)
            if r.status_code == 429 and attempt < 2:
                time.sleep(1.2 * (attempt + 1))
                continue
            if r.status_code == 401 and attempt == 0:      # 캐시 토큰이 죽었으면 1회 재발급
                self._tok = None
                try:
                    self.cache.unlink()
                except Exception:
                    pass
                h["Authorization"] = f"Bearer {self.token()}"
                continue
            if r.status_code != 200:
                raise TossError(self._why(r, what or path))
            return r.json().get("result")
        raise TossError(f"{what or path} 재시도 초과")

    # ── 조회 ──────────────────────────────────────────────────────────
    def accounts(self):
        return self._get("/api/v1/accounts", what="계좌 목록") or []

    def holdings(self, account_seq):
        res = self._get("/api/v1/holdings", account=account_seq, what="보유 종목") or {}
        out = []
        for it in res.get("items") or []:
            mv = it.get("marketValue") or {}
            pl = it.get("profitLoss") or {}
            out.append({
                "sym": str(it.get("symbol") or "").strip(),
                "name": it.get("name") or "",
                "market": (it.get("marketCountry") or "").upper() or ("KR" if it.get("currency") == "KRW" else "US"),
                "currency": it.get("currency") or "",
                "qty": _num(it.get("quantity")) or 0.0,
                "avg_cost": _num(it.get("averagePurchasePrice")),
                "last_price": _num(it.get("lastPrice")),
                "value": _num(mv.get("amount")),
                "cost": _num(mv.get("purchaseAmount")),
                "pnl_pct": (_num(pl.get("rate")) * 100) if _num(pl.get("rate")) is not None else None,
            })
        return out

    def cash(self, account_seq):
        out = {}
        for cur in ("KRW", "USD"):
            try:
                r = self._get("/api/v1/buying-power", account=account_seq,
                              params={"currency": cur}, what=f"현금({cur})") or {}
                out[cur] = _num(r.get("cashBuyingPower")) or 0.0
            except TossError as e:
                out[cur] = None
                out.setdefault("_errors", []).append(str(e)[:160])
        return out

    def snapshot(self) -> dict:
        """전 계좌 보유+현금 한 번에. 계좌 API 는 초당 1건이라 간격을 둔다."""
        snap = {"asof": time.strftime("%Y-%m-%d %H:%M"), "source": "toss_openapi", "accounts": []}
        for a in self.accounts():
            seq = a.get("accountSeq")
            no = str(a.get("accountNo") or "")
            snap["accounts"].append({
                "seq": seq, "type": a.get("accountType"),
                "no_masked": ("*" * max(0, len(no) - 4) + no[-4:]) if no else "",
                "holdings": self.holdings(seq),
                "cash": self.cash(seq),
            })
            time.sleep(1.05)
        return snap


class TossBroker:
    def __init__(self, *a, **k):
        raise NotImplementedError("주문은 P2(소액 실전) 단계에서 구현 — 지금은 TossReader(조회)만")
