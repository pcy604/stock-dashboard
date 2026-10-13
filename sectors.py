"""
섹터 맵 구축 — KR(KRX-DESC) + US(S&P500) → data/sectors.json
주도주 발굴(leaders.py)이 '섹터 단위'로 작동하도록 종목→섹터 매핑 제공.
실행:  python sectors.py   (가끔 갱신, 캐시됨)
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import json
from pathlib import Path

OUT = Path('data/sectors.json')


def build():
    import FinanceDataReader as fdr
    m = {}
    # ── KR ──
    try:
        import krx_listing
        krx = krx_listing.desc_listing()
        for _, r in krx.iterrows():
            code = str(r.get('Code', '')).zfill(6) if r.get('Code') else ''
            # 2026-10-14 — KRX-DESC 의 'Sector' 는 업종이 아니라 **코스닥 소속부**(벤처기업부·
            #   우량기업부…)이고 코스피는 비어 있다. 그래서 KR 섹터는 원래부터 코스닥 소속부만
            #   담겼고 삼성전자·하이닉스 같은 코스피 종목은 통째로 빠져 있었다.
            #   (NaN 은 truthy 라 `Sector or Industry` 가 Industry 로 넘어가지도 않았다.)
            #   실제 업종(KSIC)이 든 'Industry' 를 쓴다.
            sec = r.get('Industry')
            if not (isinstance(sec, str) and sec.strip()):
                sec = None
            if code and sec:
                m[code] = str(sec)
        print(f"  KR 섹터: {sum(1 for k in m if k.isdigit())}개")
    except Exception as e:
        print(f"  KR 섹터 실패: {e}")
    # ── US ──
    try:
        sp = fdr.StockListing('S&P500')
        for _, r in sp.iterrows():
            sym = r.get('Symbol')
            sec = r.get('Sector')
            if sym and sec and str(sec) != 'nan':
                m[str(sym)] = str(sec)
        print(f"  US 섹터: {sum(1 for k in m if not k.isdigit())}개")
    except Exception as e:
        print(f"  US 섹터 실패: {e}")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(m, ensure_ascii=False), encoding='utf-8')
    print(f"  ✅ {len(m)}종목 → {OUT}")


_cache = None

def get_sector_map():
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {}
        except Exception:
            _cache = {}
    return _cache


if __name__ == '__main__':
    build()
