"""dashboard.py 의 _UH_VER 와 ui_home.VERSION 이 같아야 클라우드 옛 모듈 재적재가 작동한다."""
import re
from pathlib import Path

import ui_home


def test_ui_home_version_matches_dashboard():
    src = Path(__file__).resolve().parents[1].joinpath('dashboard.py').read_text(encoding='utf-8')
    m = re.search(r"_UH_VER = '([^']+)'", src)
    assert m and m.group(1) == ui_home.VERSION
