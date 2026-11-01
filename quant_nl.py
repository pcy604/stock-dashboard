# -*- coding: utf-8 -*-
"""🤖 말로 쓴 전략 → 퀀트 명세(JSON) (2026-11-01, 차니: "자연어로 코딩한 걸 백테스트")

원칙: AI 는 **명세만** 만든다(코드 실행 없음). 결과는 validate() 가 필드·연산자·숫자 범위를 다시 검사하고,
엔진이 못 하는 조건은 버린 뒤 '뺀 조건'으로 화면에 반드시 보여 준다 — 비슷한 걸로 몰래 바꾸지 않는다.
"""
import json
import re

import quant_engine as Q


def _catalog():
    f = '\n'.join(f"  - {k}: {v[0]} ({v[1]}) — {v[2]}" for k, v in Q.FIELDS.items())
    s = '\n'.join(f"  - {k}: {v[0]} [파라미터 {v[1] or '없음'}] — {v[2]}" for k, v in Q.EXIT_SIGNALS.items())
    return f, s


def prompt(text, market):
    f, s = _catalog()
    unit = '원(KRW). 1억원 = 1e8, 1조 = 1e12' if market == 'KR' else '달러(USD). $1B = 1e9'
    return f"""너는 퀀트 백테스트 명세 작성기다. 사용자의 한국어 전략 설명을 아래 JSON 명세 **하나**로만 바꿔라. 설명·코드블록 없이 JSON 만.

시장: {market} · 데이터는 **주봉**(n 은 주 수. '5일선'→1주선, '20일선'→4주선, '60일선'→12주선, '120일선'→24주선, '200일선'→40주선으로 환산하고 notes 에 적어라)
시총 단위: {unit}

쓸 수 있는 필드(field) — ':n' 이 붙은 것은 n 을 숫자로 채움(예 ma_gap:40, ret:13, ma_x:10-40):
{f}

연산자 op: >=, <=, >, <, ==, !=, between(value=[하한,상한]), contains(업종 글자, value='반도체,2차전지')

탈출 신호(exit.signals 의 type):
{s}
  · ma_break {{"type":"ma_break","n":5}} · rsi_down {{"type":"rsi_down","n":14,"level":70}} · macd_neg {{"type":"macd_neg"}}
  · doji_vol {{"type":"doji_vol","vol_x":2}} · bear {{"type":"bear","pct":7}} · rank_out {{"type":"rank_out","m":40}}
  · field {{"type":"field","field":"op_yoy","op":"<","value":0}}

명세 형식(모든 키 선택, 안 쓰면 생략):
{{"start":"2015-01-01","rebalance":4,"max_pos":20,
 "filters":[{{"field":"marcap","op":">=","value":100000000000}}, ...],
 "logic":"1 AND (2 OR 3)",            // 조건 번호(1부터)로 AND·OR·NOT·괄호. 모두 AND 면 생략
 "rank":{{"field":"rs","desc":true}},
 "weight":"equal|rank|mcap|inv_vol", "max_w":0.15,
 "exposure":{{"base":1.0,"index":"SPX|NDX|KOSPI|''","ma":40,"below":0.3,"months":[11,12,1,2,3,4]}},
 "entry":{{"init":0.5,"pyramid":[[20,0.25],[40,0.25]]}},   // [상승%, 목표 비중 대비 추가 비율]
 "exit":{{"stop":15,"trail":[[0,25],[50,20]],"min_hold":0,"cooldown":4,"signals":[...]}},
 "notes":["환산·가정한 것"], "unsupported":["데이터가 없어 뺀 조건(예: 외국인 수급, 뉴스, 일봉 전용 신호)"]}}

규칙: 목록에 없는 데이터·신호는 절대 비슷한 것으로 바꾸지 말고 unsupported 에 원문 그대로 넣어라.
비율(max_w, init, below, base)은 0~1 소수. 퍼센트(stop, trail, pyramid 상승%)는 숫자 그대로.

사용자 전략:
\"\"\"{text}\"\"\""""


def _num(x, lo=None, hi=None):
    v = float(x)
    if lo is not None and v < lo or hi is not None and v > hi:
        raise ValueError
    return v


def _field_ok(k):
    base, _, p = str(k).partition(':')
    keys = {kk.split(':')[0]: (':' in kk) for kk in Q.FIELDS}
    if base not in keys:
        return False
    if keys[base]:
        return bool(re.fullmatch(r'\d+(-\d+)?', p)) and (('-' in p) == (base == 'ma_x'))
    return p == ''


def validate(raw):
    """AI 결과(dict) → (깨끗한 명세, 메모, 뺀 것). 틀린 항목은 고치지 않고 버린다."""
    notes = list(raw.get('notes') or [])
    dropped = list(raw.get('unsupported') or [])
    out = {}
    for k, lo, hi, typ in (('start', None, None, str), ('rebalance', 1, 52, int), ('max_pos', 1, 100, int), ('max_w', 0.005, 1, float)):
        if k in raw:
            try:
                out[k] = raw[k] if typ is str else typ(_num(raw[k], lo, hi))
            except Exception:
                dropped.append(f'{k}={raw[k]} (범위 밖)')
    if raw.get('weight') in ('equal', 'rank', 'mcap', 'inv_vol'):
        out['weight'] = raw['weight']
    keep_idx, filt = [], []
    for i, f in enumerate(raw.get('filters') or []):
        if _field_ok(f.get('field')) and f.get('op') in Q.OPS:
            if f['op'] == 'between' and not (isinstance(f.get('value'), list) and len(f['value']) == 2):
                dropped.append(f'조건 {i + 1}: between 값 형식 오류'); continue
            filt.append(dict(field=f['field'], op=f['op'], value=f.get('value'))); keep_idx.append(i + 1)
        else:
            dropped.append(f"조건 {i + 1}: {f.get('field')} {f.get('op')} {f.get('value')} (모르는 필드·연산자)")
    out['filters'] = filt
    lg = str(raw.get('logic') or '')
    if lg and len(keep_idx) != len(raw.get('filters') or []):
        remap = {old: new for new, old in enumerate(keep_idx, 1)}
        if any(int(n) not in remap for n in re.findall(r'\d+', lg)):
            notes.append('빠진 조건이 결합식에 있어 결합식을 "모두 AND" 로 바꿨습니다'); lg = ''
        else:
            lg = re.sub(r'\d+', lambda m: str(remap[int(m.group())]), lg)
    try:
        Q.parse_logic(lg, len(filt)); out['logic'] = lg
    except Exception as e:
        notes.append(f'결합식 오류로 "모두 AND" 사용: {e}'); out['logic'] = ''
    rk = raw.get('rank') or {}
    if _field_ok(rk.get('field')):
        out['rank'] = dict(field=rk['field'], desc=bool(rk.get('desc', True)))
    ex = raw.get('exposure') or {}
    if ex:
        e2 = {}
        for k in ('base', 'below'):
            if k in ex:
                e2[k] = min(max(float(ex[k]), 0), 1)
        if ex.get('index') in ('SPX', 'NDX', 'KOSPI', ''):
            e2['index'] = ex['index']
        if 'ma' in ex:
            e2['ma'] = int(min(max(int(ex['ma']), 2), 200))
        if ex.get('months'):
            e2['months'] = sorted({int(m) for m in ex['months'] if 1 <= int(m) <= 12})
        out['exposure'] = e2
    en = raw.get('entry') or {}
    if en:
        out['entry'] = dict(init=min(max(float(en.get('init', 1.0)), 0.05), 1.0),
                            pyramid=[[float(a), min(max(float(b), 0), 1)] for a, b in (en.get('pyramid') or [])])
    xe = raw.get('exit') or {}
    if xe:
        sigs = []
        for sg in xe.get('signals') or []:
            if sg.get('type') in Q.EXIT_SIGNALS and (sg['type'] != 'field' or (_field_ok(sg.get('field')) and sg.get('op') in Q.OPS)):
                sigs.append(sg)
            else:
                dropped.append(f"탈출 신호 {sg} (모르는 형식)")
        out['exit'] = dict(stop=float(xe.get('stop') or 0), trail=[[float(a), float(b)] for a, b in (xe.get('trail') or [])],
                           min_hold=int(xe.get('min_hold') or 0), cooldown=int(xe.get('cooldown') or 0), signals=sigs)
    return out, notes, dropped


def to_spec(text, market, key):
    """Gemini 호출 → 검증된 명세. 반환 (spec, notes, dropped, raw_text)."""
    from google import genai
    cl = genai.Client(api_key=key)
    r = cl.models.generate_content(model='gemini-2.5-flash', contents=prompt(text, market),
                                   config={'response_mime_type': 'application/json', 'temperature': 0})
    raw_t = r.text or ''
    m = re.search(r'\{.*\}', raw_t, re.S)
    raw = json.loads(m.group() if m else raw_t)
    spec, notes, dropped = validate(raw)
    spec['market'] = market
    return spec, notes, dropped, raw_t
