# -*- coding: utf-8 -*-
"""종목 분석 스냅샷 사전 계산 (2026-11-13, 통폐합 P1) — results/snap/{코드}.json

왜 AppTest 로 도는가: 종목 분석 탭의 입력(L)은 아직 화면 코드 2,500줄이 만든다. 그걸 따로 다시 짜면 '화면과 다른 숫자'가
다시 생긴다. 그래서 **화면 그 자체를 헤드리스로 한 번 돌려** stock_snapshot.compute 가 저장하게 한다(SNAP_SAVE=1).
봇 /report 는 이 파일만 읽어 그린다(상태 = 대시보드 정본).

대상 = 실전 보유(live/ledger.json) ∪ 이번 주 후보(live/plan_latest.json candidates_top) ∪ 인자로 준 코드 ∪ data/snap_watch.txt(봇 감시 종목, 봇이 커밋).
사용: python tools/precompute_snap.py [코드 ...]   환경: SNAP_MAX(기본 40) · SNAP_TIMEOUT(초, 기본 420 — 첫 실행 실측 한국 150~265초/종목)
출력: results/snap/_index.json {made, ok:[...], fail:{코드: 이유}} — 정답 점검이 읽는다.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SNAP_DIR = os.path.join(ROOT, 'results', 'snap')


def targets(extra: list[str]) -> list[str]:
    out: list[str] = []

    def add(c):
        c = str(c or '').strip().upper().replace('.KS', '').replace('.KQ', '')
        if c and c not in out:
            out.append(c)

    try:
        led = json.load(open(os.path.join(ROOT, 'live', 'ledger.json'), encoding='utf-8'))
        for mk in ('KR', 'US'):
            for c in ((led.get(mk) or {}).get('positions') or {}):
                add(c)
    except Exception as e:
        print(f'[targets] ledger 못 읽음: {e}')
    try:
        pl = json.load(open(os.path.join(ROOT, 'live', 'plan_latest.json'), encoding='utf-8'))
        for sl in (pl.get('sleeves') or {}).values():
            for c in (sl.get('candidates_top') or []):
                add(c.get('code') or c.get('sym'))
    except Exception as e:
        print(f'[targets] plan 못 읽음: {e}')
    wp = os.path.join(ROOT, 'data', 'snap_watch.txt')
    if os.path.exists(wp):
        for line in open(wp, encoding='utf-8'):
            add(line.split('#')[0])
    for c in extra:
        add(c)
    return out[: int(os.environ.get('SNAP_MAX', '40'))]


def run_one(code: str, timeout: int) -> tuple[bool, str]:
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(os.path.join(ROOT, 'dashboard.py'), default_timeout=timeout)
    at.query_params['sym'] = code
    at.query_params['layout'] = 'v2'
    try:
        at.run()
    except Exception as e:
        return False, f'run: {type(e).__name__}: {str(e)[:120]}'
    if at.exception:
        return False, f'exception: {str(at.exception[0])[:120]}'
    bad = [c.value for c in at.caption if c.value.startswith('`')]      # guard() 가 삼킨 예외 본문(백틱 캡션)
    errs = [e.value for e in at.error]
    if errs:
        return False, f'error: {errs[0][:80]} · {" / ".join(b[:160] for b in bad[:2]) or "삼킨 예외 없음"}'
    path = os.path.join(SNAP_DIR, f'{code}.json')
    if not os.path.exists(path):
        return False, '파일 없음 — 종목 화면이 끝까지 안 그려짐' + (f' · {bad[0][:80]}' if bad else '')
    try:
        js = json.load(open(path, encoding='utf-8'))
        assert js.get('asof') == dt.date.today().isoformat(), f"asof {js.get('asof')}"
        assert len(js.get('blocks') or {}) >= 6, f"블록 {len(js.get('blocks') or {})}개"
        assert js.get('verdict', {}).get('head'), '결론 없음'
    except Exception as e:
        return False, f'계약 위반: {e}'
    return True, (f'경고 {len(bad)}건' if bad else 'ok')


def main():
    os.environ['SNAP_SAVE'] = '1'
    os.environ.setdefault('ANALYSIS_LAYOUT', 'v2')
    os.makedirs(SNAP_DIR, exist_ok=True)
    codes = targets(sys.argv[1:])
    timeout = int(os.environ.get('SNAP_TIMEOUT', '420'))
    print(f'대상 {len(codes)}종: {" ".join(codes)}')
    ok, fail = [], {}
    t0 = time.time()
    for c in codes:
        t = time.time()
        good, msg = run_one(c, timeout)
        (ok.append(c) if good else fail.__setitem__(c, msg))
        print(f"{'✅' if good else '❌'} {c} {msg} ({time.time() - t:.0f}s)", flush=True)
    idx = {'made': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'ok': ok, 'fail': fail,
           'n_target': len(codes), 'secs': round(time.time() - t0)}
    json.dump(idx, open(os.path.join(SNAP_DIR, '_index.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'완료 {len(ok)}/{len(codes)} · {idx["secs"]}s')
    if codes and len(ok) < max(1, len(codes) // 2):
        print('::error::스냅샷 절반 넘게 실패 — 0건 저장을 성공으로 찍지 않는다')
        sys.exit(1)


if __name__ == '__main__':
    main()
