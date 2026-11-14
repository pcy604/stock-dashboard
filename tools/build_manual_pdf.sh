#!/usr/bin/env bash
# 사용설명서 PDF — manual.py → docs/manual.html → docs/manual.pdf (헤드리스 크롬). manual-pdf 워크플로와 로컬이 같이 쓴다.
set -euo pipefail
cd "$(dirname "$0")/.."
python manual.py
CHROME="${CHROME:-$(command -v google-chrome || command -v chromium || command -v chromium-browser)}"
"$CHROME" --headless=new --no-sandbox --disable-gpu --no-pdf-header-footer --virtual-time-budget=4000 \
  --print-to-pdf=docs/manual.pdf "file://$PWD/docs/manual.html" 2>/dev/null
python - <<'PY'
import os, sys
n = os.path.getsize('docs/manual.pdf')
print(f'docs/manual.pdf {n:,} bytes')
sys.exit(0 if n > 30_000 else 1)       # 빈 문서(글꼴·렌더 실패)면 실패
PY
