# -*- coding: utf-8 -*-
"""🔍 종목 분석 스냅샷 — 7블록 판정을 **한 번 계산해 dict 로** 돌려준다 (2026-11-13, 통폐합 P1 첫 단계).

왜: 같은 '종목 분석'을 대시보드·봇 /report·봇 /ir 이 따로 계산해 같은 종목에 다른 숫자가 나왔다.
    이 모듈이 돌려준 dict 하나를 화면(dashboard._an_v2_fill)이 그리고, 같은 dict 를 results/snap/{코드}.json 으로
    내보내면 봇은 그림만 그린다(상태 = 대시보드 정본 · 사건 = 봇 정본).

순서(차니 2026-11-13 확정): 결론 → 수급 → 이익 방향 → 가격 → 정체 → 깨지는 조건·촉매 → 매매 계획 → 원자료.
정체(린치 유형)는 읽는 순서는 5번째지만 **계산은 먼저** 한다 — 유형이 가격 블록의 해석(사이클 기업 P/E 보류)을 정한다.

입력: L = 종목 분석 탭이 이미 계산한 locals (여기서 새로 추정하지 않는다 — 없는 값은 '-'·'na' 로 정직하게).
      ctx = 대시보드 전역 도우미(공통 지표표 _CMB, 업종 사전, 컨센서스, 분기 재무 로더). streamlit 은 쓰지 않는다.
출력 계약(v1):
  {'v': 1, 'sym', 'market': 'KR'|'US', 'asof': 'YYYY-MM-DD', 'name',
   'type': {'label', 'sub', 'cyclical'},                      # 정체 — 린치 유형(v1 규칙·참고)
   'blocks': {블록명: {'tone', 'cards': [{'label','value','sub','tone'}…], 'detail': [...], 'error': str|None}},
   'verdict': {'head', 'cards', 'rules': {'pass','total','bot'}|None}}
"""
from __future__ import annotations

import datetime as _dt
import json
import os

import pandas as pd

VERSION = 1
BLOCKS = ['수급', '이익 방향', '가격', '정체', '깨지는 조건·촉매', '매매 계획', '원자료']
SNAP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results', 'snap')


def C(label, value, sub='', tone='na'):
    return {'label': label, 'value': value, 'sub': sub, 'tone': tone}


def _num(v):
    try:
        f = float(v)
        return None if pd.isna(f) else f
    except Exception:
        return None


# ── 정체: 린치 6유형 v1 규칙 ────────────────────────────────────────────────
def lynch_type(cyclical: bool | None, rev_yoy: float | None, state: str | None,
               mcap_usd: float | None) -> dict:
    """대형우량·고성장·경기순환·회생·저성장(+판정 불가). 자산주는 데이터(장부가 대비 숨은 자산)가 없어 v1 에선 안 가른다.
    규칙(참고용 — 백테스트한 것이 아니다): 흑자전환·적자축소 → 회생 / 이익률 사이클 기업 → 경기순환 /
    매출 YoY ≥ 20 → 고성장 / 시총 $50B+ 이고 매출 5~20 → 대형우량 / 매출 < 5 → 저성장."""
    st = str(state or '')
    if '흑자전환' in st or '적자' in st:
        return {'label': '회생(턴어라운드)', 'sub': f"{st} — 피터 린치 분류: 실적 바닥 탈출이 확인되는 국면의 상승폭이 가장 큼", 'cyclical': bool(cyclical)}
    if cyclical:
        return {'label': '경기순환', 'sub': '이익률이 자기 분포 안에서 크게 변동 — P/E 역방향 해석 필요(최저 P/E = 이익 천장)', 'cyclical': True}
    if rev_yoy is None:
        return {'label': '판정 불가', 'sub': '매출 성장률 없음', 'cyclical': False}
    if rev_yoy >= 20:
        return {'label': '고성장', 'sub': f"매출 YoY {rev_yoy:+.0f}% — PEG·성장 지속성이 핵심", 'cyclical': False}
    if rev_yoy < 5:
        return {'label': '저성장', 'sub': f"매출 YoY {rev_yoy:+.0f}% — 배당·자사주 정책이 수익률을 좌우(피터 린치)", 'cyclical': False}
    if mcap_usd is not None and mcap_usd >= 50e9:
        return {'label': '대형우량', 'sub': f"매출 YoY {rev_yoy:+.0f}% · 시총 ${mcap_usd / 1e9:,.0f}B — 린치 분류상 30~50% 구간 차익 실현 대상", 'cyclical': False}
    return {'label': '중간 성장', 'sub': f"매출 YoY {rev_yoy:+.0f}% — 고성장·대형우량 사이", 'cyclical': False}


# ── 깨지는 조건: 실전 v1.9 규칙 + 이익 방향을 '지금 거리'와 함께 ──────────────
def break_conditions(rs: float | None, dd52: float | None, fwd_tone: str | None,
                     gate_on: bool | None) -> dict:
    """각 조건 = (이름, 이미 해당?, 지금 값). 규칙상 손절선(고점 −20%)과 '판단이 깨지는 조건'은 같은 칸에 두되 출처를 적는다."""
    rows = []
    if rs is not None:
        rows.append(('RS 70 아래 (실전 v1.9 탈락 매도)', rs < 70, f"지금 RS {rs:.0f}"))
    if dd52 is not None:
        rows.append(('52주 고점 −20% (실전 손절선 기준은 보유 중 고점)', dd52 <= -20, f"지금 고점 대비 {dd52:+.1f}%"))
    if fwd_tone in ('good', 'mid', 'bad'):
        rows.append(('컨센서스 하향 전환 (이익 방향 악화)', fwd_tone == 'bad', {'good': '지금 상향', 'mid': '지금 혼조', 'bad': '지금 하향'}[fwd_tone]))
    if gate_on is not None:
        rows.append(('소속 지수 주봉 5주선 이탈 (신규 매수 중지)', not gate_on, '지금 ' + ('위' if gate_on else '아래')))
    hit = [r for r in rows if r[1]]
    if not rows:
        return {'value': '-', 'sub': '조건을 잴 데이터 없음', 'tone': 'na', 'rows': rows}
    return {'value': f"{len(rows)}개 중 {len(hit)}개 이미 해당",
            'sub': ' · '.join(r[0].split(' (')[0] for r in hit) if hit else '해당 조건 없음 — 조건별 현재 거리는 아래 근거 참조',
            'tone': 'bad' if len(hit) >= 2 else ('mid' if hit else 'good'), 'rows': rows}


# ── 본체 ─────────────────────────────────────────────────────────────────
def compute(L: dict, ctx: dict) -> dict:
    """L: 탭 locals · ctx: {'A2','CMB','sector_detail','kr_cons_hist','kr_cons_live','sx','q_rows_long','cm'}."""
    A2, CMB, cm = ctx['A2'], ctx['CMB'], ctx['cm']
    sym, is_kr, hist, info = L['sym8_clean'], L['is_kr_sym'], L['hist'], L.get('info') or {}
    pxf = (lambda v: f"₩{v:,.0f}") if is_kr else (lambda v: f"${v:,.2f}")
    snap = {'v': VERSION, 'sym': sym, 'market': 'KR' if is_kr else 'US',
            'asof': _dt.date.today().isoformat(), 'name': str(info.get('shortName') or info.get('longName') or L.get('name') or sym),
            'type': None, 'blocks': {}, 'verdict': None}
    tone = {}
    in_cmb = (CMB is not None) and (not CMB.empty) and (sym in CMB.index)
    row = CMB.loc[sym] if in_cmb else None
    rs = _num(row.get('RS')) if in_cmb else None
    oy = _num(row.get('영업익YoY(%)')) if in_cmb else None
    ry = _num(row.get('매출YoY(%)')) if in_cmb else None
    mcap_usd = _num(row.get('_mc_usd')) if in_cmb else None
    h = None
    try:
        h = A2.high52(hist['Close'])
    except Exception:
        pass

    # ① 수급 ───────────────────────────────────────────────────────────────
    try:
        sd = L.get('_sd') or ctx['sector_detail']()
        gsel, glabel = str(L.get('_gsel') or ''), L.get('_glabel')
        mkt = 'KR' if is_kr else 'US'
        if is_kr and gsel.startswith('테마'):
            fam = sd.get('theme') or {}
        elif is_kr and gsel.startswith('네이버 업종'):
            fam = sd.get('upjong') or {}
        elif not is_kr and gsel.startswith('세부 산업'):
            fam = sd.get('industry') or {}
        else:
            col = '_업종full' if (in_cmb and '_업종full' in CMB.columns) else '업종'
            fam = {k: list(v.index.astype(str)) for k, v in CMB.groupby(col)} if in_cmb else {}
            glabel = str(row[col]) if in_cmb else None
        gh = A2.group_heat(CMB, fam, market=mkt, min_n=5)
        grow = gh[gh['group'] == glabel] if glabel is not None and len(gh) else gh.iloc[0:0]
        gpct = float(grow['pct'].iloc[0]) if len(grow) else None
        vr = A2.volume_ratio(hist.get('Volume'))
        q = A2.flow_quadrant(gpct, rs)
        cards = [
            C('업종 온도 (비교군 RS 중앙값 순위)',
              (f"{glabel} · {int(grow['rank'].iloc[0])}/{int(grow['of'].iloc[0])}위" if len(grow) else (glabel or '업종 미상')),
              (f"비교군 RS 중앙값 {grow['med_rs'].iloc[0]:.0f} · 상위 {gpct:.0f}% · {int(grow['n'].iloc[0])}종" if len(grow)
               else "비교군이 5종 미만이거나 분류 없음 — 아래에서 비교군 범위를 넓혀 주십시오"),
              'na' if gpct is None else ('good' if gpct <= 30 else 'bad' if gpct >= 70 else 'mid')),
            C('종목 강도 (RS · 52주 고점)',
              (f"RS {rs:.0f}" if rs is not None else 'RS -') + (f" · 고점 대비 {h['dd']:+.1f}%" if h else ''),
              (f"52주 고점 {pxf(h['high'])} ({h['date']}, {h['weeks']}주 전) · 종가 기준" if h else '가격 이력 부족'),
              'na' if rs is None else ('good' if rs >= 80 else 'bad' if rs < 50 else 'mid')),
            C('수급 판정', q['label'], q['why'] + (f" · 거래량 {vr:.1f}배(5일÷20일)" if vr else ''), q['tone']),
        ]
        tone['수급'] = q['tone']
        snap['blocks']['수급'] = {'tone': q['tone'], 'cards': cards, 'detail': [], 'error': None}
    except Exception as e:
        tone['수급'] = 'na'
        snap['blocks']['수급'] = {'tone': 'na', 'cards': [], 'detail': [], 'error': f"{type(e).__name__}: {str(e)[:100]}"}

    # ③ 이익 방향 (+ 정체 계산용 사이클 위치) ─────────────────────────────────
    cyc, fwd, state = {}, {'tone': 'na'}, None
    try:
        ed = L.get('_ed') or {}
        if is_kr:
            rows = list(ctx['kr_cons_hist'](sym))
            lv = ctx['kr_cons_live'](sym)
            if lv:
                rows.append({'date': pd.Timestamp.today().strftime('%Y-%m-%d'), 'sym': sym, **lv})
            fwd = A2.forward_kr(rows)
        else:
            fwd = A2.forward_us(ed.get('eps_trend'), ed.get('eps_revisions'))
        cyc = A2.cycle_position(ctx['sx'].quarterly_frame(ctx['q_rows_long'](sym, is_kr)[0]))
        et0, ah0 = L.get('_et0') or {}, L.get('_ah0') or {}
        state = et0.get('state') if is_kr else (f"이익 가속 {ah0['rows'][0]['주차']}" if ah0.get('rows') else '이익 가속 신호 없음')
        past_val = ' · '.join(x for x in (f"영업익 {oy:+.0f}%" if oy is not None else None,
                                          f"매출 {ry:+.0f}%" if ry is not None else None) if x) or '-'
        past_tone = ('na' if oy is None and not state else
                     'good' if (oy is not None and oy > 0) or '흑자전환' in str(state) else
                     'bad' if oy is not None and oy < 0 else 'mid')
        cards = [C('앞으로 (컨센서스·리비전) — 대표', fwd['value'], fwd['sub'], fwd['tone']),
                 C('사이클 위치 (자기 이익률 분포)', cyc['value'], cyc['sub'], cyc['tone']),
                 C('지금까지 (최근 분기 YoY)', past_val, f"{state or '-'} · 사이클 기업은 바닥 국면에서 이 수치가 가장 나쁨", past_tone)]
        t = fwd['tone'] if fwd['tone'] != 'na' else (cyc['tone'] if cyc.get('cyclical') else past_tone)
        peak = bool(cyc.get('cyclical') and (cyc.get('pct') or 0) >= 80 and t == 'good')   # 린치: 최대 이익·최저 P/E 에서 사면 반토막
        if peak:
            t = 'mid'
        tone['이익 방향'], tone['_cyc_peak'] = t, peak
        snap['blocks']['이익 방향'] = {'tone': t, 'cards': cards, 'detail': [], 'error': None}
    except Exception as e:
        tone['이익 방향'] = 'na'
        snap['blocks']['이익 방향'] = {'tone': 'na', 'cards': [], 'detail': [], 'error': f"{type(e).__name__}: {str(e)[:100]}"}

    # 정체 — 유형은 여기서 확정(가격 해석에 쓴다)
    snap['type'] = lynch_type(cyc.get('cyclical'), ry, state, mcap_usd)

    # ④ 가격 ────────────────────────────────────────────────────────────────
    try:
        bm, vb = L.get('_bm') or {}, L.get('_vb') or {}
        peg = _num(L.get('_peg'))
        per = vb.get('per_ttm')
        try:
            pr = cm.peer_rank(CMB, sym, codes=L.get('_gcodes'), label=L.get('_glabel')) or {}
        except Exception:
            pr = {}
        med = next((r['업종중앙'] for r in (pr.get('rows') or []) if r['지표'] == 'PER(배)'), None)
        ratio = (per / med) if (per and med and per > 0 and med > 0) else None
        v = A2.valuation_reading(bm.get('rank'), peg, ratio, cyc.get('cyclical'))
        cards = [C('밸류 종합 (참고 — 매수 판정 미반영)', v['value'], v['sub'], v['tone']),
                 C(f"자기 과거 ({bm.get('kind', 'P/E')} 밴드)",
                   (f"{bm['now']:.1f}배 · {bm['rank']:.0f}% 구간 상회" if bm.get('now') is not None and bm.get('rank') is not None else '-'),
                   (f"과거 중앙값 {bm['pct'][50]:.1f}배 · 사업 구조 변경 시 과거 비교의 설명력 저하" if bm.get('pct') else '밴드 계산 불가'),
                   'na' if bm.get('rank') is None else ('good' if bm['rank'] <= 25 else 'bad' if bm['rank'] >= 75 else 'mid')),
                 C('동종 대비 · 성장 대비',
                   (f"P/E {per:.1f}배 vs 업종 {med:.1f}배" if per and med else 'P/E -'),
                   (f"PEG {peg:.2f} — 1 미만은 성장 대비 저평가(피터 린치)" if peg else 'PEG - (적자·컨센서스 없음)'),
                   'na' if ratio is None else ('good' if ratio <= 0.8 else 'bad' if ratio >= 1.25 else 'mid'))]
        tone['가격'] = v['tone']
        snap['blocks']['가격'] = {'tone': v['tone'], 'cards': cards, 'detail': [], 'error': None, 'peer_rank': pr}
    except Exception as e:
        pr = {}
        tone['가격'] = 'na'
        snap['blocks']['가격'] = {'tone': 'na', 'cards': [], 'detail': [], 'error': f"{type(e).__name__}: {str(e)[:100]}"}

    # ② 정체 (읽는 순서 5번째) ──────────────────────────────────────────────
    try:
        ty = snap['type']
        prr = {r['지표']: r for r in (pr.get('rows') or [])}
        mc = prr.get('시총') or {}
        rsr = prr.get('RS') or {}
        pos_val = (f"{pr.get('sector')} · 시총 {mc['순위']}/{mc['비교수']}위" if mc.get('순위') else (pr.get('sector') or '업종 미상'))
        pos_sub = (f"RS {rsr['순위']}/{rsr['비교수']}위 · 산업 내 1위·과점 여부가 1차 점검 항목" if rsr.get('순위') else '업종 내 순위 계산 불가')
        pos_tone = 'na' if not mc.get('순위') else ('good' if mc['순위'] <= 2 else 'mid' if mc['순위'] <= 5 else 'na')
        prof = L.get('_prof') or {}
        seg = L.get('_seg_ai') or {}
        story = None
        for cand in (seg.get('one_liner') if isinstance(seg, dict) else None,
                     seg.get('summary') if isinstance(seg, dict) else None, prof.get('summary')):
            if isinstance(cand, str) and cand.strip():
                story = cand.strip()
                break
        cards = [C('유형 (피터 린치 6유형 · v1 규칙 — 사이클 여부는 이익률 분포로 자동 판정하며 오분류 가능)', ty['label'], ty['sub'], 'na'),
                 C('업종 내 위치', pos_val, pos_sub, pos_tone),
                 C('이 회사는 무엇인가', (story[:90] + '…') if story and len(story) > 90 else (story or '-'),
                   '사업부문·고객 구성은 아래 상세 · 서사는 숫자로 확인될 때만 근거가 됨(다모다란)', 'na')]
        snap['blocks']['정체'] = {'tone': 'na', 'cards': cards, 'detail': [], 'error': None}
    except Exception as e:
        snap['blocks']['정체'] = {'tone': 'na', 'cards': [], 'detail': [], 'error': f"{type(e).__name__}: {str(e)[:100]}"}

    # ⑤ 깨지는 조건·촉매 ────────────────────────────────────────────────────
    try:
        nx_us, nx = L.get('_next_us'), (L.get('_eq') or {}).get('next') or {}
        now = pd.Timestamp.today().normalize()
        if nx_us is not None:
            nd = pd.Timestamp(nx_us[0])
            nd = nd.tz_localize(None) if getattr(nd, 'tz', None) else nd
            ev = C('다음 실적 발표', f"{nd:%Y-%m-%d}", f"D-{(nd.normalize() - now).days}", 'mid' if (nd - now).days <= 14 else 'na')
        elif nx.get('예상') is not None:
            ev = C('다음 실적 발표', f"{nx['예상']:%m월 %d일} 전후(추정)", '전년 같은 분기 발표일 기준', 'na')
        else:
            ev = C('다음 실적 발표', '-', '일정 미상', 'na')
        try:                                    # 소속 지수 게이트 — 봇 계획표(live/plan_latest.json)와 같은 값
            ix = ((ctx['live_plan']() or {}).get('index') or {}).get('KR' if is_kr else 'US') or {}
            gate = ix.get('ok') if isinstance(ix.get('ok'), bool) else None
        except Exception:
            gate = None
        bc = break_conditions(rs, h['dd'] if h else None, fwd.get('tone'), gate)
        risk, chk = L.get('_risk') or [], L.get('_chk_') or []
        nr = [r for r in risk if r.get('state') == 'warn']
        nc = [r for r in chk if r.get('state') == 'warn']
        cards = [C('판단이 깨지는 조건', bc['value'], bc['sub'], bc['tone']), ev,
                 C('리스크 점검', (f"{len(nr)}개 해당" if risk else '-') + (f" · 데이터 이상 {len(nc)}건" if nc else ''),
                   ' · '.join(r['name'] for r in nr)[:80] or '해당 없음',
                   'na' if not risk else ('good' if not nr and not nc else 'mid' if len(nr) <= 2 and not nc else 'bad'))]
        detail = [{'state': 'warn' if r[1] else 'ok', 'name': r[0], 'detail': r[2]} for r in bc['rows']] + list(risk) + list(chk)
        tone['리스크'] = cards[2]['tone']
        snap['blocks']['깨지는 조건·촉매'] = {'tone': bc['tone'], 'cards': cards, 'detail': detail, 'error': None,
                                        'expand': bool(nc)}
    except Exception as e:
        snap['blocks']['깨지는 조건·촉매'] = {'tone': 'na', 'cards': [], 'detail': [], 'error': f"{type(e).__name__}: {str(e)[:100]}"}

    # ⑥ 매매 계획 · 원자료 — 첫 줄 카드 없음(섹션 본문이 곧 내용). 계약상 자리만 둔다.
    rk, bst = L.get('_rk'), L.get('_bst')
    rules = ({'pass': sum(1 for x in rk if x[1]), 'total': len(rk), 'bot': bst or '-'}
             if isinstance(rk, list) and rk else None)
    snap['blocks']['매매 계획'] = {'tone': 'na', 'cards': [], 'detail': [], 'error': None, 'rules': rules}
    snap['blocks']['원자료'] = {'tone': 'na', 'cards': [], 'detail': [], 'error': None}

    # 결론 (항상) ─────────────────────────────────────────────────────────
    f_t, s_t, p_t = tone.get('이익 방향', 'na'), tone.get('수급', 'na'), tone.get('가격', 'na')
    fw = {'good': '이익 개선 국면', 'mid': '이익 신호 혼조', 'bad': '이익 악화 국면', 'na': '이익 판단 불가'}[f_t]
    if tone.get('_cyc_peak'):
        fw = '이익 사이클 천장권 — 해석 주의'
    fl = {'good': '수급 유입', 'mid': '수급 부분 유입', 'bad': '수급 이탈', 'na': '수급 판단 불가'}[s_t]
    snap['verdict'] = {
        'head': f"{fw}, {fl}",
        'type_chip': snap['type']['label'],
        'cards': [C('🌊 수급·관심', {'good': '강함', 'mid': '보통', 'bad': '약함', 'na': '-'}[s_t], fl, s_t),
                  C('🏭 이익 방향 (앞으로 우선)', {'good': '개선', 'mid': '엇갈림', 'bad': '악화', 'na': '-'}[f_t], fw, f_t),
                  C('⚖️ 가격 (참고)', {'good': '저평가', 'mid': '중립', 'bad': '고평가', 'na': '-'}[p_t], '사이클 기업·적자 종목은 판정 보류', p_t)],
        'rules': rules,
    }
    return snap


# ── 내보내기 (봇이 읽는 정본) ────────────────────────────────────────────
def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items() if not str(k).startswith('_') or k in ('_cyc_peak',)}
    if isinstance(o, (list, tuple)):
        return [_jsonable(x) for x in o]
    if isinstance(o, (pd.Timestamp, _dt.date, _dt.datetime)):
        return str(o)[:10]
    if hasattr(o, 'item'):
        try:
            return o.item()
        except Exception:
            return str(o)
    if isinstance(o, float) and pd.isna(o):
        return None
    return o


def public(snap: dict) -> dict:
    """공개 저장소에 올라가도 되는 부분만 — 매매 계획(봇 규칙 대조·소유자 전용)은 뺀다."""
    out = _jsonable({k: v for k, v in snap.items() if k != 'verdict'})
    out['verdict'] = _jsonable({k: v for k, v in snap['verdict'].items() if k != 'rules'})
    out['blocks'].pop('매매 계획', None)
    for b in out['blocks'].values():
        b.pop('peer_rank', None)
    return out


def save(snap: dict, directory: str = SNAP_DIR) -> str:
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{snap['sym']}.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(public(snap), f, ensure_ascii=False, indent=1)
    return path
