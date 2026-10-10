"""
health_metrics.py — '파일은 신선한데 내용이 죽은' 고장을 잡는다
─────────────────────────────────────────────────────────────────
왜 만들었나 (2026-10-10):
  하루에 조용한 실패 5건이 한꺼번에 드러났다. 전부 기존 감시(data_freshness)를
  통과한 채였다. 그 감시는 **파일 안의 날짜**만 본다. 그래서 매일 갱신되지만
  내용이 무너진 고장은 원리적으로 못 본다.

    · 이익 가속 universe 2,429 → 242종. 파일은 매일 새로 쓰였고 '정상 3일'이었다.
      신호가 없었던 게 아니라 **볼 종목이 없었다**. 한 달 걸려 사람이 발견했다.
    · us_marketcap 3,095 → 448종. as_of 는 어제 날짜였다.
    · marketcap 수집이 매 실행 같은 600종만 받았다. 4회 연속 결과가 한 종목도
      안 늘었다 — 로그는 매번 정상이었다.

  공통 증상은 하나다: **값이 변하지 않는다.** 날짜만 늙지 않는지 보지 말고,
  내용의 수치가 살아 움직이는지를 봐야 한다.

세 가지로 판정한다.
  ① 하한      — 이 밑이면 무조건 고장 (universe 1,000종 미만 등)
  ② 급감      — 직전 대비 -30%
  ③ 정체      — 변해야 하는 값이 N회 연속 완전히 같다  ← 오늘 5건 중 3건이 이것

기록: results/health_metrics.jsonl (append, 180회 유지)
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import json
from pathlib import Path
from datetime import datetime

HIST = Path('results/health_metrics.jsonl')
KEEP = 180
DROP_PCT = 30          # 직전 대비 이만큼 줄면 급감
STALL_N = 3            # 이만큼 연속 같은 값이면 정체


def _json(path, *keys, default=None):
    try:
        d = json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception:
        return default
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return d


def _csv_rows(path):
    try:
        import pandas as pd
        return len(pd.read_csv(path))
    except Exception:
        return None


def _accel_universe():
    return _json('results/leaders_accel.json', 'universe')


def _accel_last_week():
    w = _json('results/leaders_accel.json', 'weeks', default={}) or {}
    return max(w) if w else None


def _prices_syms():
    try:
        import price_store
        return price_store.stats()['syms']
    except Exception:
        return None


def _prices_last():
    try:
        import price_store
        return price_store.stats()['last']
    except Exception:
        return None


# (키, 라벨, 값 함수, 하한, 정체를 고장으로 볼 것인가)
#   stall=False 는 '안 변해도 정상'인 지표다. 분기재무처럼 원래 가끔 변하는 것.
METRICS = [
    ('marketcap_syms', '미국 시총 종목 수', lambda: _csv_rows('data/us_marketcap.csv'), 1500, False),
    ('shares_rows',    'SEC 주식수 행수',   lambda: _csv_rows('data/us_shares.csv'), 100000, False),
    ('accel_universe', '이익가속 유니버스', _accel_universe, 1000, False),
    ('accel_last_week', '이익가속 최신 주차', _accel_last_week, None, True),
    ('prices_syms',    'prices 종목 수',    _prices_syms, 1000, False),
    ('prices_last',    'prices 최신 주차',  _prices_last, None, True),
    ('screener_total', '주봉 신호 종목 수', lambda: _json('results/screener_latest.json', 'total'), None, True),
]


def collect():
    out = {'_at': datetime.now().strftime('%Y-%m-%d %H:%M')}
    for key, _label, fn, _lo, _stall in METRICS:
        try:
            out[key] = fn()
        except Exception as e:
            out[key] = None
            out.setdefault('_err', {})[key] = str(e)[:80]
    return out


def history():
    if not HIST.exists():
        return []
    rows = []
    for line in HIST.read_text(encoding='utf-8').splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows


def append(rec):
    HIST.parent.mkdir(parents=True, exist_ok=True)
    rows = (history() + [rec])[-KEEP:]
    HIST.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n',
                    encoding='utf-8')


def judge(cur, hist):
    """고장 문구 목록. 빈 리스트면 정상."""
    bad = []
    for key, label, _fn, lo, stall in METRICS:
        v = cur.get(key)
        if v is None:
            bad.append(f"{label}: 값을 못 읽었다 — 생산자가 죽었거나 형식이 바뀌었다")
            continue
        # ① 하한
        if lo is not None and isinstance(v, (int, float)) and v < lo:
            bad.append(f"{label}: {v:,} (하한 {lo:,} 미만) — 유니버스가 무너졌다")
            continue
        prev = [h.get(key) for h in hist if h.get(key) is not None]
        # ② 급감
        if prev and isinstance(v, (int, float)) and isinstance(prev[-1], (int, float)):
            p = prev[-1]
            if p > 0 and (p - v) / p * 100 >= DROP_PCT:
                bad.append(f"{label}: {p:,} → {v:,} ({(v-p)/p*100:+.0f}%) — 급감")
                continue
        # ③ 정체
        if stall and len(prev) >= STALL_N and all(x == v for x in prev[-STALL_N:]):
            bad.append(f"{label}: {v} 에서 {STALL_N}회째 그대로 — "
                       f"매번 갱신된다는 값이 안 움직인다")
    return bad


def main(notify=True):
    cur = collect()
    hist = history()
    bad = judge(cur, hist)
    append(cur)

    shown = ' · '.join(f"{l}={cur.get(k)}" for k, l, _f, _lo, _s in METRICS)
    if bad:
        msg = ("🚨 [screener] 내용 지표 이상\n" + "\n".join(f"· {b}" for b in bad)
               + f"\n\n― 현재값 ―\n{shown}")
    else:
        # ⚠️ 정상일 때도 보낸다. '문제 있을 때만'으로 두면 조용한 날이 '정상'인지
        #    '감시가 죽은 날'인지 구분할 수 없다 — 실제로 17일을 그렇게 보냈다.
        #    침묵을 신호로 쓰지 않는다.
        msg = f"✅ [screener] 지표 정상\n{shown}"
    print(msg)
    if not notify:
        return bad
    try:
        import config
        from telegram_notifier import send_message
        if config.TELEGRAM_ENABLED:
            send_message(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, msg)
            print('(텔레그램 발송됨)')
    except Exception as e:
        print(f'(텔레그램 발송 실패: {e})')
    return bad


if __name__ == '__main__':
    main(notify='--no-notify' not in sys.argv)
