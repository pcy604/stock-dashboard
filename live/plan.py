# -*- coding: utf-8 -*-
"""실전 시범 — 다음 주 매매 계획표 (live/PREREG_2026-11.md 규칙 그대로)

입력: 교집합 후보(대시보드와 같은 정의: common_metrics RS ≥ 80 × [미국 이익가속 or 흑자전환 / 한국 흑자전환·시총 1,000억+])
      · 현재가 perf_latest.json(금요일 종가) · 지수 200일선 results/trade_idx.parquet · 원장 live/ledger.json
출력: live/plan_latest.json · live/plan_latest.md (+ 텔레그램, TELEGRAM_TOKEN/CHAT_ID 가 있으면)
주문은 하지 않는다 — 계획표만 만든다. 실제 주문은 차니(첫 3~4주) → 이후 차니가 켜는 토스 봉.
"""
import json
import math
import os
import sys
from datetime import date

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
LEDGER = os.path.join(ROOT, 'live', 'ledger.json')
OUT_J = os.path.join(ROOT, 'live', 'plan_latest.json')
OUT_M = os.path.join(ROOT, 'live', 'plan_latest.md')

RULE = dict(slots=5, first=0.60, add_at=0.10, add=0.40, cap=0.30, stop=0.20, kr_min_mc=1e11, rs_min=80,
            ma_days=50)   # v1.1(2026-11-01): 종가가 50일선(≈10주선) 위인 종목만 — 지난 1년 대박 후 최근 무너지는 종목 배제(차니 지적·AXTI)
START = {'US': 1_000_000, 'KR': 1_000_000}          # 원화. 매달 +50만씩(원장 deposits 로 기록)


def _j(p):
    try:
        return json.load(open(os.path.join(ROOT, p), encoding='utf-8'))
    except Exception:
        return {}


def ledger():
    if os.path.exists(LEDGER):
        return json.load(open(LEDGER, encoding='utf-8'))
    return {'US': {'cash_krw': START['US'], 'positions': {}, 'deposits': [[str(date.today()), START['US']]]},
            'KR': {'cash_krw': START['KR'], 'positions': {}, 'deposits': [[str(date.today()), START['KR']]]},
            'fx_note': '미국 슬리브는 원화로 장부를 두고 체결 때 환율을 기록'}


def usdkrw():
    try:
        s = pd.read_parquet(os.path.join(ROOT, 'data', 'research', 'macro_long_px.parquet'))['USDKRW'].dropna()
        return float(s.iloc[-1]), str(s.index[-1])[:10]
    except Exception:
        return 1350.0, '가정'


def index_ok():
    """S&P500·코스피가 200일선 위인가 (위면 신규 매수 가능)."""
    out = {}
    try:
        ix = pd.read_parquet(os.path.join(ROOT, 'results', 'trade_idx.parquet'))
        # v1.2(2026-11-01 차니): 한국은 종목이 속한 시장 지수로 — 코스닥 종목은 코스닥 200일선, 코스피 종목은 코스피 200일선
        for m, k in (('US', 'SPX'), ('KR', 'KOSPI'), ('KQ', 'KOSDAQ')):
            s = ix[k].dropna()
            ma = s.rolling(200).mean()
            out[m] = dict(ok=bool(s.iloc[-1] > ma.iloc[-1]), last=round(float(s.iloc[-1]), 1), ma200=round(float(ma.iloc[-1]), 1),
                          date=str(s.index[-1])[:10])
    except Exception as e:
        for m in ('US', 'KR', 'KQ'):
            out[m] = dict(ok=True, note=f'지수 자료 없음({type(e).__name__}) — 신규 매수 허용으로 둠')
    return out


def kr_board():
    """코드 → 'KR'(코스피) | 'KQ'(코스닥). data/krx_listing_last.csv(매일 갱신)"""
    try:
        d = pd.read_csv(os.path.join(ROOT, 'data', 'krx_listing_last.csv'), dtype={'Code': str}, usecols=['Code', 'MarketId'])
        return {c.zfill(6): ('KQ' if mi == 'KSQ' else 'KR') for c, mi in zip(d.Code, d.MarketId)}
    except Exception:
        return {}


def candidates(fx):
    import common_metrics as cm
    cmb, _ = cm.build(fx)
    acc = {r['sym'] for r in (_j('results/leaders_accel.json').get('acc_now') or [])}
    ta = {r['sym'] for r in (_j('results/turnaround_latest.json').get('stocks') or []) if r.get('status') == '흑자전환완료'}
    perf = {str(r['sym']): r for r in (_j('results/perf_latest.json').get('stocks') or [])}
    out = {'US': [], 'KR': []}
    for sym, r in cmb[cmb.RS >= RULE['rs_min']].iterrows():
        m = r['시장']
        why = [w for w, ok in (('이익가속', sym in acc and m == 'US'), ('흑자전환', sym in ta)) if ok]
        if not why or m not in out:
            continue
        if m == 'KR' and not (r.get('_mc_local') or 0) >= RULE['kr_min_mc']:
            continue
        px = (perf.get(sym) or {}).get('curr_price')
        if not px:
            continue
        out[m].append(dict(sym=sym, name=r['종목'], rs=float(r['RS']), why='+'.join(why), price=float(px),
                           n=len(why), dist52=(perf.get(sym) or {}).get('dist52')))
    for m in out:
        out[m].sort(key=lambda x: (-x['n'], -x['rs']))
        out[m] = trend_ok(out[m][:40], m)
    return out


def _hist(sym, m):
    import yfinance as yf
    for t in ([sym] if m == 'US' else [f'{sym}.KS', f'{sym}.KQ']):
        try:
            h = yf.Ticker(t).history(period='1y', auto_adjust=True)['Close'].dropna()
            if len(h) >= RULE['ma_days']:
                return h
        except Exception:
            pass
    return None


def trend_ok(cands, m):
    """v1.1 — 최근 추세 확인: 종가 > 50일 이평. 가격을 못 받으면 '확인 불가'로 빼고 건너뜀 목록에 남긴다(있는 척하지 않는다)."""
    keep = []
    for c in cands:
        h = _hist(c['sym'], m)
        if h is None:
            c['trend'] = '확인 불가'; continue
        ma = float(h.rolling(RULE['ma_days']).mean().iloc[-1]); last = float(h.iloc[-1])
        c['ma50'] = round(ma, 2); c['gap50'] = round((last / ma - 1) * 100, 1)
        c['trend'] = 'OK' if last > ma else '50일선 아래'
        keep.append(c)
    return [c for c in keep if c['trend'] == 'OK'] + [dict(c, _excluded=True) for c in keep if c['trend'] != 'OK']


def plan():
    fx, fx_date = usdkrw()
    L = ledger()
    C = candidates(fx)
    IX = index_ok()
    P = dict(made=str(date.today()), price_basis=_j('results/perf_latest.json').get('date'), rs_basis=_j('results/returns.json').get('date'),
             usdkrw=fx, usdkrw_date=fx_date, index=IX, rule=RULE, sleeves={})
    for m in ('US', 'KR'):
        S = L[m]
        pos = S['positions']
        equity = S['cash_krw'] + sum(p['shares'] * p['last_px'] * (fx if m == 'US' else 1) for p in pos.values())
        target = equity / RULE['slots']
        buys, adds, stops, trims, skipped = [], [], [], [], []
        cash = S['cash_krw']
        for sym, p in pos.items():                                    # 보유: 손절선 갱신 · 불타기 조건 · 상한 덜기
            peak = max(p.get('peak', p['avg']), p['last_px'])
            stop = max(p.get('stop', p['avg'] * (1 - RULE['stop'])), peak * (1 - RULE['stop']))
            stops.append(dict(sym=sym, name=p.get('name', sym), stop=round(stop, 2), peak=round(peak, 2)))
            w = p['shares'] * p['last_px'] * (fx if m == 'US' else 1) / equity
            if not p.get('added') and (IX['US']['ok'] if m == 'US' else IX[kr_board().get(sym, 'KR')]['ok']):
                adds.append(dict(sym=sym, name=p.get('name', sym), trigger=round(p['first_px'] * (1 + RULE['add_at']), 2),
                                 krw=round(target * RULE['add'])))
            if w > RULE['cap']:
                trims.append(dict(sym=sym, name=p.get('name', sym), now_w=round(w * 100, 1), to_w=RULE['cap'] * 100))
        free = RULE['slots'] - len(pos)
        BOARD = kr_board() if m == 'KR' else {}
        gate = (lambda sym: IX['US']['ok']) if m == 'US' else (lambda sym: IX[BOARD.get(sym, 'KR')]['ok'])
        if free > 0:
            for c in C[m]:
                if not gate(c['sym']):
                    bd = '코스닥' if BOARD.get(c['sym']) == 'KQ' else '코스피'
                    skipped.append(dict(sym=c['sym'], name=c['name'], why=f"{bd} 200일선 아래 — 신규 중지")); continue
                if c.get('_excluded'):
                    skipped.append(dict(sym=c['sym'], name=c['name'], why=f"50일선 아래({c.get('gap50')}%) — RS 는 높지만 최근 추세 꺾임")); continue
                if len(buys) >= free:
                    break
                if c['sym'] in pos:
                    continue
                krw = target * RULE['first']
                if krw > cash:
                    skipped.append(dict(sym=c['sym'], name=c['name'], why='현금 부족')); continue
                if m == 'US':
                    qty = round(krw / fx / c['price'], 4)                 # 토스 미국 소수점
                    amt_local = round(qty * c['price'], 2)
                else:
                    qty = math.floor(krw / c['price'])
                    amt_local = qty * c['price']
                    if qty < 1:
                        skipped.append(dict(sym=c['sym'], name=c['name'], why=f"1주 {c['price']:,.0f}원 > 배정 {krw:,.0f}원")); continue
                spent = amt_local * (fx if m == 'US' else 1)
                cash -= spent
                buys.append(dict(sym=c['sym'], name=c['name'], why=c['why'], rs=round(c['rs']), ref_px=c['price'], qty=qty,
                                 amount_local=amt_local, krw=round(spent), gap50=c.get('gap50'), add_trigger=round(c['price'] * (1 + RULE['add_at']), 2),
                                 stop=round(c['price'] * (1 - RULE['stop']), 2)))
        P['sleeves'][m] = dict(equity_krw=round(equity), cash_krw=round(S['cash_krw']), cash_after_krw=round(cash), target_krw=round(target),
                               buys=buys, adds=adds, stops=stops, trims=trims, skipped=skipped,
                               candidates_top=[dict(sym=c['sym'], name=c['name'], rs=round(c['rs']), why=c['why']) for c in C[m][:10]])
    json.dump(P, open(OUT_J, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    md = render(P)
    open(OUT_M, 'w', encoding='utf-8').write(md)
    return P, md


def render(P):
    flag = {'US': '🇺🇸 미국', 'KR': '🇰🇷 한국'}
    L = [f"📋 다음 주 매매 계획 ({P['made']} 작성 · 가격 {P['price_basis']} 종가 · RS {P['rs_basis']} · 환율 {P['usdkrw']:,.0f})"]
    for m, S in P['sleeves'].items():
        cur = '$' if m == 'US' else ''
        ix = P['index'][m]
        ixs = [('S&P500', P['index']['US'])] if m == 'US' else [('코스피', P['index']['KR']), ('코스닥', P['index'].get('KQ', {}))]
        L.append(f"\n{flag[m]} 슬리브 — 자산 {S['equity_krw']:,}원 · 종목당 목표 {S['target_krw']:,}원 · 첫 매수 60%")
        for nm, x in ixs:
            L.append(f"  {nm} 200일선: {'위 → 신규 가능' if x.get('ok') else '아래 → 그 시장 종목 신규·불타기 중지'}" + (f" ({x.get('last')} vs {x.get('ma200')}, {x.get('date')})" if 'last' in x else ''))
        if S['buys']:
            L.append("  🟢 월요일 시가 매수:")
            for b in S['buys']:
                q = f"{b['qty']}주" if m == 'US' else f"{b['qty']:,}주"
                L.append(f"   · {b['name']} ({b['sym']}) {q} ≈ {cur}{b['amount_local']:,.2f} ({b['krw']:,}원) · {b['why']} RS{b['rs']}"
                         f" · 50일선 {b.get('gap50'):+}%" + f" | 불타기 조건 {cur}{b['add_trigger']:,}↑ · 손절 스탑 {cur}{b['stop']:,}↓ (체결가 기준으로 다시 계산)")
        for a in S['adds']:
            L.append(f"  🔥 불타기 조건주문: {a['name']} {a['trigger']}↑ 닿으면 {a['krw']:,}원 추가")
        for s in S['stops']:
            L.append(f"  🛑 손절 스탑: {s['name']} {s['stop']} (보유 중 최고 {s['peak']})")
        for t in S['trims']:
            L.append(f"  ✂️ 상한 초과 덜기: {t['name']} {t['now_w']}% → {t['to_w']:.0f}%")
        for k in S['skipped'][:8]:
            L.append(f"  ⏭ 건너뜀: {k['name']} — {k['why']}")
        L.append(f"  남는 현금 ≈ {S['cash_after_krw']:,}원")
    L.append("\n규칙: live/PREREG_2026-11.md · 체결하면 체결가·수량·환율을 알려 주세요(원장 기록).")
    return '\n'.join(L)


if __name__ == '__main__':
    P, md = plan()
    print(md)
    tok, chat = os.environ.get('TELEGRAM_TOKEN'), os.environ.get('TELEGRAM_CHAT_ID')
    if tok and chat and '--send' in sys.argv:
        import telegram_notifier as T
        print('텔레그램:', T.send_message(tok, chat, md))
