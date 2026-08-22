# -*- coding: utf-8 -*-
"""주도주 KR 포워드 페이퍼 원장 — 신호를 낸 뒤 실제로 어떻게 됐는지 누적한다.

    python leaders_kr_paper.py update    # 원장 갱신 (주 1회, weekly-profile에서 자동)
    python leaders_kr_paper.py report    # 성과 요약

## 왜 별도 파일인가

`leaders_paper.py`(미국)와 목적은 같지만 합치지 않았다. 규칙(KR-P1·KR-U6)도, 데이터
원천(longcache + DART export)도, 손절폭(-30% vs -20%)도 다르다. 무엇보다 그 파일은
지금 다른 작업으로 전면 개편 중이라 건드리면 양쪽 다 망가진다.

## 백테스트가 이미 있는데 왜 원장이 또 필요한가

`leaders_kr.backtest()`는 **지금 시점에서 과거를 다시 계산**한다. 그래서 생존편향
(현재 상장 종목만)·데이터 개정·규칙 사후조정이 전부 결과에 섞인다. 원장은 반대로
**우리가 실제로 신호를 낸 그날 이후**만 기록하므로 그 오염이 원리적으로 안 들어온다.
표본이 쌓이는 데 오래 걸리는 대신, 쌓인 만큼은 믿을 수 있다.

## 후보 목록으로 청산을 판정하면 안 된다

`live_signals()`는 "최근 8주 내 진입 + 아직 열림"만 준다. 그래서 후보에서 사라지는
이유가 **둘**이다 — ①트레일링 청산(진짜) ②8주 경과(여전히 보유 중인데 목록에서만
빠짐). 목록 이탈을 청산으로 적으면 ②가 전부 가짜 청산이 되어 성과가 통째로 틀린다.
그래서 원장은 **원장에 있는 종목마다 거래를 직접 다시 계산해** 열림/닫힘을 판정한다.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date

BASE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(BASE, 'results', 'leaders_kr_paper.json')
RULES = ('KR-P1', 'KR-U6')


def _load() -> dict:
    if os.path.exists(LEDGER):
        try:
            with open(LEDGER, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'started': str(date.today()), 'updated': None,
            'positions': {r: {} for r in RULES}}


def _save(d: dict):
    d['updated'] = str(date.today())
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print(f'→ {LEDGER}')


def _current(rule: str) -> dict:
    """지금 신호가 열려 있는 종목 {sym: 후보dict}."""
    if rule == 'KR-P1':
        import leaders_kr as K
        return {c['sym']: c for c in K.live_signals()}
    import leaders_kr6 as K6
    return {c['sym']: c for c in K6.live()}


_K6 = {}


def _k6_cache(what: str):
    """KR-U6 판정에 필요한 무거운 준비물(벤치마크·상장주식수·분기재무 플래그)을
    종목마다 다시 만들면 원장 갱신이 몇십 분 단위로 늘어난다 — 한 번만 만든다."""
    if what not in _K6:
        import leaders_kr6 as K6
        _K6[what] = {'bench': K6.benchmark, 'shares': K6.shares_map, 'r6': K6.rule6_map}[what]()
    return _K6[what]


def _restate(rule: str, sym: str, since: str):
    """원장에 있는 종목의 **현재 상태**를 가격에서 다시 계산한다.

    반환 {open, entry_date, entry_px, close, ret, peak_gain, exit_date} 또는 None.
    since(원장 진입일) 이후 첫 거래를 본다 — 그 전 거래는 우리가 신호를 내기 전이라
    포워드 성과가 아니다.
    """
    import pandas as pd
    import leaders_kr as K
    c = K.load_close(sym)
    if c is None or len(c) == 0:
        return None
    if rule == 'KR-P1':
        trades = K.trades_for(c, adv=K.load_adv(sym), min_adv=K.MIN_ADV, start=since)
    else:
        import leaders_kr6 as K6
        # live()와 **같은 임계값**을 써야 한다. 다른 값을 쓰면 원장이 화면의 후보와
        # 다른 규칙을 채점하게 되는데, 그건 눈으로 안 걸린다.
        mc, adv_m = K6.PRESETS['US그대로']
        trades = K6.trades_rule6(sym, c, _k6_cache('bench'), _k6_cache('shares'),
                                 _k6_cache('r6'), mc, adv_m, trail=30.0, start=since)
    if not trades:
        return None
    t = trades[0]                       # since 이후 첫 거래 = 우리가 신호를 낸 그 거래
    entry = float(c.loc[t['entry']])
    seg = c.loc[t['entry']:t['exit']]
    return dict(open=bool(t.get('open')),
                entry_date=str(pd.Timestamp(t['entry']).date()),
                entry_px=round(entry, 0),
                close=round(float(seg.iloc[-1]), 0),
                ret=round(t['ret'] * 100, 1),
                peak_gain=round(float(t.get('peak_gain', seg.max() / entry - 1)) * 100, 1),
                exit_date=(None if t.get('open') else str(pd.Timestamp(t['exit']).date())),
                days=int(t['days']))


def update():
    led = _load()
    for rule in RULES:
        pos = led['positions'].setdefault(rule, {})
        try:
            cur = _current(rule)
        except Exception as e:
            print(f'[{rule}] 신호 조회 실패 — 이번 회차는 건너뜀: {e}')
            continue
        # ① 새 신호 등록. first_seen 은 **우리가 처음 본 날**이지 진입일이 아니다 —
        #    이 구분이 포워드 원장의 전부다.
        for sym, c in cur.items():
            if sym not in pos:
                pos[sym] = {'name': c.get('name', sym), 'first_seen': str(date.today()),
                            'signal_entry': c.get('entry_date'), 'state': 'open'}
                print(f'  [{rule}] 신규 {c.get("name", sym)}({sym}) 진입 {c.get("entry_date")}')
        # ② 원장 전체를 가격에서 다시 판정 (후보 목록 이탈 ≠ 청산)
        for sym, rec in pos.items():
            if rec.get('state') == 'closed':
                continue
            st = _restate(rule, sym, rec.get('signal_entry') or rec['first_seen'])
            if st is None:
                rec['note'] = '가격 데이터 없음 — 판정 보류'
                continue
            rec.update({k: st[k] for k in
                        ('entry_date', 'entry_px', 'close', 'ret', 'peak_gain', 'days')})
            if not st['open']:
                rec['state'] = 'closed'
                rec['exit_date'] = st['exit_date']
                print(f'  [{rule}] 청산 {rec["name"]}({sym}) {st["ret"]:+.1f}% '
                      f'({st["days"]}일, 고점 {st["peak_gain"]:+.1f}%)')
        led['positions'][rule] = pos
    _save(led)
    return led


def summarize(led: dict = None) -> dict:
    led = led or _load()
    out = {'started': led.get('started'), 'updated': led.get('updated'), 'rules': {}}
    for rule in RULES:
        pos = led.get('positions', {}).get(rule, {})
        closed = [r for r in pos.values() if r.get('state') == 'closed' and r.get('ret') is not None]
        openp = [r for r in pos.values() if r.get('state') != 'closed' and r.get('ret') is not None]
        rets = [r['ret'] for r in closed]
        wins = [r for r in rets if r > 0]
        loss = [r for r in rets if r <= 0]
        out['rules'][rule] = {
            'n_total': len(pos), 'n_open': len(openp), 'n_closed': len(closed),
            'avg_closed': round(sum(rets) / len(rets), 1) if rets else None,
            'winrate': round(len(wins) / len(rets) * 100, 1) if rets else None,
            # 손익비는 양쪽 표본이 다 있어야 의미가 있다. 한쪽이 비면 None —
            # 0으로 나눠 inf를 만들거나 한쪽만으로 큰 수를 찍으면 읽는 사람이 오해한다.
            'payoff': (round((sum(wins) / len(wins)) / abs(sum(loss) / len(loss)), 2)
                       if wins and loss else None),
            'avg_open': round(sum(r['ret'] for r in openp) / len(openp), 1) if openp else None,
        }
    return out


def report():
    led = _load()
    s = summarize(led)
    print(f'\n주도주 KR 포워드 원장 — 시작 {s["started"]} · 갱신 {s["updated"]}')
    print('─' * 66)
    for rule, v in s['rules'].items():
        print(f'[{rule}] 누적 {v["n_total"]}종 (보유 {v["n_open"]} · 청산 {v["n_closed"]})')
        if v['n_closed']:
            print(f'    청산 평균 {v["avg_closed"]:+.1f}% · 승률 {v["winrate"]}% · '
                  f'손익비 {v["payoff"] if v["payoff"] is not None else "—(한쪽 표본 없음)"}')
        else:
            print('    청산 표본 없음 — 아직 성과를 말할 수 없다')
        if v['n_open']:
            print(f'    보유 평균 {v["avg_open"]:+.1f}% (미실현)')
    n = sum(v['n_closed'] for v in s['rules'].values())
    if n < 30:
        print(f'\n⚠️ 청산 표본 {n}건 — 30건 미만이면 승률·손익비는 노이즈다. '
              '백테스트(등급 C)를 대체하지 않는다.')
    return s


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'report'
    if cmd == 'update':
        update()
        report()
    else:
        report()
