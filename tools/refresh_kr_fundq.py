# -*- coding: utf-8 -*-
"""KR 분기재무를 러너에서 갱신한다 — market.db 없이.

왜 (2026-10-14)
  data/kr_fundamentals_q.parquet 는 **PC 에서 손으로** `ingest_dart_quarterly.py` →
  `export_kr_fundq.py export` 를 돌려야만 갱신됐다. 10-12 에 순이익 계정명 버그를 PC DB
  에서 고쳤는데 export 를 안 해서, 레포 파일은 08-15 판(순이익 전 행 공란·2026Q1)
  그대로였다. 이 파일을 읽는 KR-U6·흑자전환(KR)이 러너에서 틀린 재무로 돌았다.
  사람이 기억해야 하는 단계는 결국 잊힌다 → 러너가 매주 직접 한다.

순서
  1) 레포 parquet → 임시 sqlite(fundamentals_q) 로 복원
  2) 종목 목록 = 기존 parquet 종목 ∪ 현재 KRX 상장(krx_listing) 중 시총 1,000억+
  3) DART 에서 올해·작년 분기를 받아 INSERT OR REPLACE (ingest_dart_quarterly.ingest 재사용)
  4) universe(상장주식수·시총)는 오늘 KRX 목록으로 갱신
  5) 기존 export() 로 parquet 2개를 다시 쓴다 — 형식이 PC 판과 바이트 단위로 같은 경로
  안전장치: 결과 행 수가 기존의 95% 미만이거나 순이익 채움률이 80% 미만이면 쓰지 않는다.
  (커밋 전 output_contracts.py 가 한 번 더 검사한다)

  python tools/refresh_kr_fundq.py
"""
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import pandas as pd

import export_kr_fundq as E
import ingest_dart_quarterly as Q

TMP = ROOT / "data" / "_fundq_ci.db"


def _dart_reachable(timeout=6) -> bool:
    """2026-10-17 — DART 는 해외 서버(GitHub Actions)의 연결을 받지 않는다. fetch_batch 는 호출마다
    timeout=40 이라 막힌 러너에서 160건 × 40초 = 1시간 47분을 기다리다 잡 전체가 잘린다. 먼저 한 번 두드려 본다."""
    import requests
    try:
        requests.get("https://opendart.fss.or.kr/", timeout=timeout)
        return True
    except Exception as e:
        print(f"DART 연결 불가({type(e).__name__}) — 이 서버에서는 건너뛴다(집 PC run_update.bat 이 월요일에 갱신). "
              "기존 parquet 는 그대로 둔다.", flush=True)
        return False


def main():
    if not _dart_reachable():
        return
    old = pd.read_parquet(E.OUT)
    before_rows, before_fill = len(old), old.net_income.notna().mean()
    print(f"기존 {before_rows:,}행 · 순이익 채움 {before_fill:.0%}", flush=True)

    if TMP.exists():
        TMP.unlink()
    con = sqlite3.connect(TMP)
    con.executescript(Q.DDL)
    old.to_sql("fundamentals_q", con, if_exists="append", index=False)

    import krx_listing
    krx = krx_listing.stock_listing("KRX")
    krx = krx[krx.Code.str.fullmatch(r"\d{6}")]
    uni = pd.DataFrame({"sym": krx.Code, "name": krx.Name.astype(str),
                        "listed_shares": pd.to_numeric(krx.get("Stocks"), errors="coerce"),
                        "marcap": krx.Marcap})
    uni.to_sql("universe", con, if_exists="replace", index=False)
    con.commit(); con.close()

    syms = sorted(set(old.sym.astype(str)) | set(krx.loc[krx.Marcap >= 1e11, "Code"]))
    y1 = date.today().year
    Q.DB = str(TMP)
    Q.ingest(y1 - 1, y1, syms=syms)

    E.DB = TMP
    chk = sqlite3.connect(TMP)
    new = pd.read_sql("SELECT * FROM fundamentals_q", chk); chk.close()
    fill = new.net_income.notna().mean()
    print(f"갱신 후 {len(new):,}행 · 순이익 채움 {fill:.0%}", flush=True)
    if len(new) < before_rows * 0.95 or fill < 0.8:
        TMP.unlink(missing_ok=True)
        raise SystemExit("⛔ 결과가 기존보다 나쁘다 — parquet 를 덮어쓰지 않는다")
    E.export()
    TMP.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
