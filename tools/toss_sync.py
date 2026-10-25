# -*- coding: utf-8 -*-
"""토스 계좌 → 암호화 스냅샷(data/portfolio_toss.enc) — **노트북에서만** 돈다.

왜 노트북인가 (2026-10-14)
  토스 Open API 는 '허용 IP' 에 등록된 고정 IP 에서만 응답한다(미등록 403).
  Streamlit Cloud·GitHub Actions 는 IP 가 매번 바뀌어 등록할 수 없다.
  그리고 키에 조회 전용 권한이 없어 client_secret 이 새면 주문까지 가능하다 —
  키는 이 PC 의 data/.toss_* (gitignore) 에만 둔다.

흐름  run_update.bat(매일 06:40 KST) → 이 스크립트 → .enc 봉인 → Supabase vaults 업로드 → 사이트가 비밀번호로 해제
      (2026-10-26 전까지는 .enc 를 공개 git 에 커밋했다 — 오프라인 대입 위험으로 중단)

  python tools/toss_sync.py --setup    처음 한 번: 키·비밀번호 입력(화면에 안 보임) 후 저장, 바로 동기화
  python tools/toss_sync.py            동기화 (키 없으면 조용히 건너뜀 — 배치를 멈추지 않는다)
  python tools/toss_sync.py --show     복호화해서 요약만 출력(점검용)
"""
import argparse, getpass, json, os, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pf_vault
from executor.broker_toss import TossReader, TossError

D = ROOT / "data"
F_ID, F_SECRET, F_PW = D / ".toss_client_id", D / ".toss_client_secret", D / ".pf_password"
PLAIN = D / "portfolio_toss.json"          # gitignore — 이 PC 에서만 보는 평문 사본


def _read(env, f):
    v = os.environ.get(env, "").strip()
    if v:
        return v
    try:
        return f.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _setup():
    print("토스증권 앱/WTS › 설정 › Open API 에서 받은 값을 붙여넣으세요 (입력이 화면에 보이지 않습니다).")
    cid = getpass.getpass("client_id: ").strip()
    sec = getpass.getpass("client_secret: ").strip()
    pw = getpass.getpass("사이트에서 쓸 포트폴리오 비밀번호(8자 이상): ").strip()
    if len(pw) < 8:
        sys.exit("비밀번호는 8자 이상으로 해주세요.")
    if pw != getpass.getpass("비밀번호 확인: ").strip():
        sys.exit("비밀번호가 서로 다릅니다.")
    D.mkdir(exist_ok=True)
    for f, v in ((F_ID, cid), (F_SECRET, sec), (F_PW, pw)):
        f.write_text(v, encoding="utf-8")
    print("저장됨: data/.toss_client_id · .toss_client_secret · .pf_password (git 에 올라가지 않음)")


def _summary(snap):
    lines = [f"기준 {snap['asof']}"]
    for a in snap["accounts"]:
        hs = a["holdings"]
        lines.append(f"· 계좌 {a['no_masked']} ({a['type']}) 보유 {len(hs)}종 · 현금 KRW {a['cash'].get('KRW')} / USD {a['cash'].get('USD')}")
        for h in sorted(hs, key=lambda h: -(h.get('value') or 0))[:15]:
            pnl = f"{h['pnl_pct']:+.1f}%" if h.get("pnl_pct") is not None else "-"
            lines.append(f"    {h['market']} {h['sym']:<7} {h['name'][:14]:<14} {h['qty']:>12,.6g}주  {pnl}")
    return "\n".join(lines)


def _alert(msg):
    try:
        import config
        from telegram_notifier import send_message
        if config.TELEGRAM_ENABLED:
            send_message(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, msg)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--setup", action="store_true")
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    if a.setup:
        _setup()
    pw = _read("PF_PASSWORD", F_PW)
    if a.show:
        print(_summary(pf_vault.unseal(pw)))
        return 0
    cid, sec = _read("TOSS_CLIENT_ID", F_ID), _read("TOSS_CLIENT_SECRET", F_SECRET)
    if not (cid and sec and pw):
        print("[toss_sync] 키 또는 비밀번호 없음 → 건너뜀 (처음이면: python tools/toss_sync.py --setup)")
        return 0
    try:
        snap = TossReader(cid, sec).snapshot()
    except TossError as e:
        print("[toss_sync] 실패:", e)
        _alert(f"🔐 [screener] 토스 계좌 동기화 실패\n{str(e)[:300]}")
        return 1
    if not snap["accounts"]:
        print("[toss_sync] 계좌가 0개로 왔다 — 기존 스냅샷 유지")
        return 1
    PLAIN.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    pf_vault.seal(snap, pw)
    print("[toss_sync] 암호화 저장 → data/portfolio_toss.enc (로컬 사본, git 에 안 올라감)")
    # 2026-10-26: 사이트는 git 이 아니라 Supabase vaults 표에서 읽는다(공개 저장소 오프라인 대입 차단)
    try:
        pf_vault.push()
        print("[toss_sync] Supabase 업로드 완료 → vaults/toss")
    except Exception as e:
        print("[toss_sync] Supabase 업로드 실패:", e)
        _alert(f"🔐 [screener] 토스 스냅샷 Supabase 업로드 실패\n{str(e)[:300]}")
        return 1
    print(_summary(snap))
    return 0


if __name__ == "__main__":
    sys.exit(main())
