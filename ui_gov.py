# -*- coding: utf-8 -*-
"""🏛️ 경영실 화면 (2026-11-12, 소유자만) — 스코어카드 · 로드맵 · 결정 · 이슈 · 회의록 · 변경 이력 · KPI 정의.

원칙
  - 고치는 곳은 화면 하나, 이력은 DB 트리거(gov_audit). 삭제는 숨김(되살리기 가능).
  - 자동 KPI 는 이 화면을 열 때 계산해 이번 주 칸에 넣는다(source=auto). 손 입력(manual)은 덮지 않는다.
  - 측정할 수 없는 KPI 는 '수동'이라고 드러낸다. 없는 값은 '-'.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pandas as pd

import gov

VERSION = '2026-11-13a'
ROOT = Path(__file__).resolve().parent


# ── 자동 KPI ──────────────────────────────────────────────────────────────
def _lab_perf():
    import sys
    lp = str(ROOT / 'live')
    if lp not in sys.path:
        sys.path.insert(0, lp)
    import perf as _lp
    dep, tr = _lp.load('KR')
    if not dep:
        return None
    start = min(d for d, _ in dep)
    import FinanceDataReader as fdr
    px = {}
    for s in [_lp.BENCH] + _lp.syms_needed(tr):
        try:
            h = fdr.DataReader(s, start)['Close'].dropna()
            h.index = pd.DatetimeIndex([pd.Timestamp(d).date() for d in h.index])
            px[s] = h.astype(float)
        except Exception:
            pass
    if _lp.BENCH not in px:
        return None
    pxd = pd.DataFrame(px)
    df = _lp.build(dep, tr, pxd.drop(columns=[_lp.BENCH]), pxd[_lp.BENCH])
    s, _, _ = _lp.summary(df)
    return s


def _ci_rate():
    import requests
    since = (_dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) - _dt.timedelta(days=7)).strftime('%Y-%m-%d')
    r = requests.get('https://api.github.com/repos/pcy604/stock-dashboard/actions/runs',
                     params={'created': f'>={since}', 'per_page': 100, 'status': 'completed'}, timeout=8)
    runs = r.json().get('workflow_runs', [])
    runs = [x for x in runs if x.get('event') == 'schedule']
    if not runs:
        return None, '정기 실행 0건'
    ok = sum(1 for x in runs if x.get('conclusion') == 'success')
    return ok / len(runs) * 100, f'{ok}/{len(runs)} (정기 실행만, 최근 100건 안)'


def compute_auto(owner_uid: str, items_issue: list[dict], vals: list[dict]) -> dict:
    """{key: (값, 메모)} — 실패한 것은 빼고 돌려준다(없는 값을 만들지 않는다)."""
    out, wk = {}, gov.week_of()
    try:
        s = _lab_perf()
        if s:
            out['lab_excess'] = (round(s['excess'] * 100, 2), f"TWR {s['twr']*100:+.2f}% vs KODEX200 {s['bench_twr']*100:+.2f}% · {s['end']}")
            out['lab_mdd'] = (round(s['mdd'] * 100, 2), f"{s['start']}~{s['end']}")
    except Exception as e:
        out['_err_lab'] = (None, type(e).__name__)
    try:
        L = json.loads((ROOT / 'live' / 'ledger.json').read_text(encoding='utf-8'))
        ym = wk.strftime('%Y-%m')
        amt = sum(float(a) for d, a in L.get('KR', {}).get('deposits', []) if str(d).startswith(ym))
        out['deposit_month'] = (round(amt / 1e4, 1), f'{ym} 입금 합계')
    except Exception:
        pass
    try:
        ka = json.loads((ROOT / 'results' / 'known_answers.json').read_text(encoding='utf-8'))
        if ka.get('total'):
            out['ka_pass'] = (round(ka['passed'] / ka['total'] * 100, 1), f"{ka['passed']}/{ka['total']} · {ka.get('generated', '')}")
    except Exception:
        pass
    try:
        v, note = _ci_rate()
        if v is not None:
            out['ci_success'] = (round(v, 1), note)
    except Exception:
        pass
    try:
        ev = gov.usage(7)
        dash = {e['uid'] for e in ev if e['uid'] != owner_uid}
        bu = gov.bot_users()
        out['wau'] = (len(dash), f'대시보드 7일 고유 방문 {len(dash)}명(소유자 제외) · 봇 사용자 별도 집계 전')
        if bu is not None:
            out['bot_users'] = (bu, 'buza-bot users 표')
    except Exception:
        pass
    # 운영 사고 = 이번 주에 열린 이슈 중 종류 '사고'
    n_inc = 0
    for it in items_issue:
        try:
            c = _dt.date.fromisoformat(str(it.get('created_at'))[:10])
        except Exception:
            continue
        if (it.get('meta') or {}).get('type') == '사고' and gov.week_of(c) == wk:
            n_inc += 1
    out['incidents'] = (n_inc, '이번 주 열린 사고 이슈')
    # 무사고 연속 주 — 지난 주들의 사고·오버라이드 값으로(이번 주 포함, 값 없는 주에서 멈춤)
    by = {}
    for r in vals:
        by.setdefault(r['week'], {})[r['key']] = r.get('value')
    by.setdefault(wk.isoformat(), {})['incidents'] = n_inc
    streak, w = 0, wk
    while True:
        d = by.get(w.isoformat())
        if not d or 'incidents' not in d:
            break
        if (d.get('incidents') or 0) > 0 or (d.get('overrides') or 0) > 0:
            break
        streak += 1
        w -= _dt.timedelta(weeks=1)
    out['clean_streak'] = (streak, '사고 0·오버라이드 0 연속(오버라이드 미입력 주는 0으로 봄)')
    return out


def _fmt(v, unit):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return '-'
    if unit in ('%', '%p'):
        return f'{v:+.2f}{unit}' if unit == '%p' else f'{v:.1f}%'
    return f'{v:,.0f}{unit}' if float(v).is_integer() else f'{v:,.1f}{unit}'


def _ok(v, meta):
    t = meta.get('target')
    if v is None or t is None:
        return None
    return v >= t if meta.get('better', 'up') == 'up' else v <= t


# ── 처리 대기 큐 ───────────────────────────────────────────────────────────
def _d(v):
    try:
        return _dt.date.fromisoformat(str(v)[:10])
    except Exception:
        return None


def _queue(kpis: list[dict], cur: dict, items: list[dict], today: _dt.date) -> list[tuple]:
    """지금 쳐낼 것을 위에서부터 한 줄씩. 반환 = ui_home.steps 형식 (라벨, 톤, 본문, 보조).

    순서는 경영 상식 그대로다. ① 돈과 사고를 먼저 막고 ② 기한이 지난 약속을 치우고
    ③ 남이 기다리는 미결(결정)을 비우고 ④ 마지막에 기록을 남긴다.
    건수만 세지 않고 '가장 급한 한 건'을 같이 적는다 — 열고 나서 또 고르지 않게.
    """
    by = {k: [i for i in items if i['kind'] == k] for k in ('roadmap', 'decision', 'issue', 'meeting')}
    q = []

    # ① 사고 — 운영이 멈추거나 돈이 새는 것
    acc = [i for i in by['issue'] if (i.get('meta') or {}).get('type') == '사고' and i['status'] != '종결']
    if acc:
        q.append(('사고 대응', 'r', f"종결 안 된 사고 {len(acc)}건 — 가장 오래된 것: {acc[0]['title']}",
                  '🚨 이슈 탭 · 원인과 재발 방지를 적고 종결로 바꿉니다'))

    # ② 회사 KPI 미달 — 이사회가 보는 숫자
    miss = [k for k in kpis if (k.get('meta') or {}).get('tier') == '회사'
            and _ok(cur.get(k['meta']['key'], {}).get('value'), k['meta']) is False]
    if miss:
        q.append(('회사 KPI 미달', 'r', ' · '.join(k['title'] for k in miss),
                  '📊 스코어카드 · 미달 원인을 이슈로 열거나 목표를 고칩니다'))

    # ③ 기한 — 지난 것부터, 그다음 일주일 안
    late = sorted([i for i in by['roadmap'] if i['status'] in ('예정', '진행') and (_d(i.get('due')) or today + _dt.timedelta(999)) < today],
                  key=lambda i: _d(i['due']))
    soon = sorted([i for i in by['roadmap'] if i['status'] in ('예정', '진행')
                   and today <= (_d(i.get('due')) or today + _dt.timedelta(999)) <= today + _dt.timedelta(7)],
                  key=lambda i: _d(i['due']))
    if late:
        q.append(('기한 초과', 'r', f"로드맵 {len(late)}건 — {late[0]['title']} ({(today - _d(late[0]['due'])).days}일 지남)",
                  '🗺️ 로드맵 탭 · 기한을 다시 잡거나 보류로 내립니다'))
    if soon:
        q.append(('이번 주 기한', 'y', f"로드맵 {len(soon)}건 — {soon[0]['title']} (D-{(_d(soon[0]['due']) - today).days})",
                  '🗺️ 로드맵 탭 · 진행률을 올립니다'))

    # ④ 미결 — 결정이 안 나서 아래가 멈춰 있는 것
    prop = sorted([i for i in by['decision'] if i['status'] == '제안'], key=lambda i: str(i.get('updated_at')))
    if prop:
        oldest = _d(prop[0].get('updated_at'))
        age = f" · {(today - oldest).days}일째" if oldest else ''
        q.append(('결정 대기', 'y', f"{len(prop)}건 — {prop[0]['title']}{age}",
                  '⚖️ 결정 로그 탭 · 승인 또는 기각으로 닫습니다'))

    # ⑤ 조치 중인 이슈 — 사고는 아니지만 열려 있는 것
    opn = [i for i in by['issue'] if i['status'] in ('열림', '조치 중') and (i.get('meta') or {}).get('type') != '사고']
    if opn:
        q.append(('열린 이슈', 'y', f"{len(opn)}건 — {opn[0]['title']}", '🚨 이슈 탭'))

    # ⑥ 기록 — 주간 리듬을 끊기지 않게
    done_mt = [i for i in by['meeting'] if i['status'] == '예정' and (_d(i.get('due')) or today) < today]
    if done_mt:
        q.append(('회의록 미작성', 'y', f"지난 회의 {len(done_mt)}건 — {done_mt[0]['title']}",
                  '📝 회의록 탭 · 결정은 ⚖️ 결정 로그로 옮깁니다'))
    blank = [k for k in kpis if not (k.get('meta') or {}).get('auto')
             and cur.get((k.get('meta') or {}).get('key'), {}).get('value') is None]
    if blank:
        q.append(('이번 주 값 입력', 'k', f"손 입력 KPI {len(blank)}개 비어 있음 — {', '.join(k['title'] for k in blank[:3])}"
                  + ('…' if len(blank) > 3 else ''), "📊 스코어카드 · '이번 주 값 입력'을 펼쳐 넣습니다"))

    if not q:
        q.append(('처리 대기 없음', 'g', '기한 초과·미결·사고가 없습니다',
                  '다음 주간 리뷰까지 🗺️ 로드맵 진행률만 올리면 됩니다'))
    return [(f'{n}. {lab}', t, body, sub) for n, (lab, t, body, sub) in enumerate(q, 1)]


# ── 화면 ──────────────────────────────────────────────────────────────────
def render(st, actor: str, owner_uid: str):
    st.caption("🏛️ **경영실 — 소유자만 보입니다.** 여기서 고친 모든 내용은 🕘 변경 이력에 전/후 그대로 남습니다(지울 수 없음). "
               "삭제는 숨김이라 되살릴 수 있습니다.")
    if not gov.ready():
        st.error("DB 설정([store])이 없어 경영실을 열 수 없습니다.")
        return
    try:
        n = gov.seed_kpis(actor)
        if n:
            st.toast(f'기본 KPI {n}개를 만들었습니다')
    except Exception as e:
        st.error(f"경영실 표가 아직 없습니다 — docs/sql/gov.sql 을 Supabase 에서 실행해야 합니다. (`{str(e)[:120]}`)")
        return
    # 2026-11-13: 탭 7개를 열어놓고 '뭐부터 손대야 하나'가 안 보인다는 지적 → 들어오자마자 순서가 정해진 큐를 먼저 보여준다.
    try:
        import ui_home as _UH                      # 늦은 임포트: ui_gov 는 streamlit 없이도 임포트돼야 한다(테스트 계약)
        _items = gov.items()
        _kpis = [k for k in _items if k['kind'] == 'kpi' and k.get('status') == '활성']
        _wk = gov.week_of()
        _cur = {r['key']: r for r in gov.kpi_values(2) if r['week'] == _wk.isoformat()}
        _today = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=9)).date()
        st.markdown('#### 지금 쳐낼 것 — 위에서부터 하나씩')
        _UH.steps(_queue(_kpis, _cur, _items, _today))
        st.caption('순서 기준: ① 사고·회사 KPI 미달 → ② 기한 → ③ 미결 → ④ 기록. '
                   '한 건을 닫으면 이 목록에서 사라집니다. 아래 탭은 그 건을 실제로 고치는 곳입니다.')
    except Exception as e:
        st.caption(f'`처리 대기 큐 계산 실패: {str(e)[:120]}`')

    st.markdown('---')
    tabs = st.tabs(['📊 스코어카드', '🗺️ 로드맵', '⚖️ 결정 로그', '🚨 이슈', '📝 회의록', '🕘 변경 이력', '⚙️ KPI 정의'])
    with tabs[0]:
        _scorecard(st, actor, owner_uid)
    for t, kind in zip(tabs[1:5], ['roadmap', 'decision', 'issue', 'meeting']):
        with t:
            st.caption(_GUIDE[kind])
            _items(st, kind, actor)
    with tabs[5]:
        _history(st)
    with tabs[6]:
        st.caption(_GUIDE['kpi'])
        _items(st, 'kpi', actor)


def _scorecard(st, actor, owner_uid):
    kpis = [k for k in gov.items('kpi') if k.get('status') == '활성']
    vals = gov.kpi_values(12)
    wk = gov.week_of()
    # 자동 값 — 한 세션에 한 번 계산해 이번 주 칸에 넣는다(손 입력은 덮지 않음)
    ss = st.session_state
    if ss.get('_gov_auto_wk') != wk.isoformat():
        auto = compute_auto(owner_uid, gov.items('issue'), vals)
        manual = {r['key'] for r in vals if r['week'] == wk.isoformat() and r.get('source') == 'manual'}
        akeys = {(k.get('meta') or {}).get('key') for k in kpis if (k.get('meta') or {}).get('auto')}
        for key, (v, note) in auto.items():
            if key.startswith('_') or key in manual or key not in akeys:
                continue
            try:
                gov.put_kpi(wk, key, v, note, 'auto', 'auto')
            except Exception:
                pass
        ss['_gov_auto_wk'] = wk.isoformat()
        ss['_gov_auto_err'] = {k: n for k, (v, n) in auto.items() if k.startswith('_')}
        vals = gov.kpi_values(12)
    if ss.get('_gov_auto_err'):
        st.caption(f"`자동 KPI 일부 실패: {ss['_gov_auto_err']}`")
    cur = {r['key']: r for r in vals if r['week'] == wk.isoformat()}

    st.markdown(f"#### 이번 주 ({wk.isoformat()} 주) — 회사 KPI")
    comp = [k for k in kpis if (k.get('meta') or {}).get('tier') == '회사']
    cols = st.columns(max(len(comp), 1))
    for c, k in zip(cols, comp):
        m = k['meta']
        r = cur.get(m['key'], {})
        v = r.get('value')
        ok = _ok(v, m)
        c.metric(k['title'], _fmt(v, m.get('unit', '')),
                 delta=None if m.get('target') is None else f"목표 {_fmt(m['target'], m.get('unit', ''))}",
                 delta_color='off', help=f"{k.get('body', '')} · {r.get('note', '')}")
        c.caption({True: '🟢 목표 충족', False: '🔴 미달', None: '⚪ 값 없음'}[ok])

    # 12주 추이 표 — 행 = KPI, 열 = 주
    weeks = sorted({r['week'] for r in vals} | {wk.isoformat()})[-12:]
    piv = {(r['key'], r['week']): r.get('value') for r in vals}
    rows = []
    for k in kpis:
        m = k['meta']
        v = piv.get((m['key'], wk.isoformat()))
        ok = _ok(v, m)
        row = {'부서': k.get('dept'), 'KPI': k['title'], '단위': m.get('unit', ''),
               '목표': m.get('target'), '판정': {True: '🟢', False: '🔴', None: '⚪'}[ok],
               '입력': '자동' if m.get('auto') else '수동'}
        for w in weeks:
            row[w[5:]] = piv.get((m['key'], w))
        rows.append(row)
    st.markdown("#### 주간 스코어카드 — 최근 12주")
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, src='경영실 gov_kpi_weekly(자동 = 이 화면 열 때 계산 · 수동 = 아래 입력)',
                 asof=wk.isoformat(), filters=False, color=False)   # 단위가 섞인 행이라 색은 판정 열(🟢🔴)로만

    with st.expander('✏️ 이번 주 값 입력·수정 (수동 KPI, 또는 자동 값 덮어쓰기)'):
        opts = {k['title']: k['meta']['key'] for k in kpis}
        with st.form('gov_kpi_form', clear_on_submit=False):
            c1, c2 = st.columns(2)
            name = c1.selectbox('KPI', list(opts))
            week = c2.date_input('주(그 주 아무 날)', value=wk)
            c3, c4 = st.columns([1, 2])
            val = c3.number_input('값', value=None, step=1.0, format='%.2f')
            note = c4.text_input('메모(근거·출처)')
            if st.form_submit_button('저장', type='primary'):
                gov.put_kpi(gov.week_of(week), opts[name], val, note, 'manual', actor)
                st.success('저장했습니다 — 변경 이력에 남았습니다'); st.rerun()

    with st.expander('📈 기능 사용률 — 탭별 최근 28일 (대시보드 방문 기록, 소유자 제외)'):
        # 2026-11-13: 표는 비었는데 '🔎 필터·정렬' 패널만 떠서 화면을 덮었다 → filters=False,
        #   그리고 0건일 때 '기록이 없다'로 끝내지 않고 분모(방문자 수)를 같이 적는다.
        try:
            raw = gov.usage(28)
            ev = [e for e in raw if e['event'] == 'tab_view' and e['uid'] != owner_uid]
            visitors = len({e['uid'] for e in raw if e['uid'] != owner_uid})
            if ev:
                u = pd.DataFrame(ev)
                t = (u.groupby('tab').agg(**{'열람(회)': ('uid', 'size'), '사람(명)': ('uid', 'nunique')})
                     .reset_index().rename(columns={'tab': '탭'}).sort_values('열람(회)', ascending=False))
                t['비중(%)'] = (t['열람(회)'] / t['열람(회)'].sum() * 100).round(1)
                st.caption(f"28일간 소유자 외 방문자 {visitors}명 · 탭 열람 {len(ev):,}회 — 아무도 안 여는 탭은 없애거나 앞으로 당깁니다.")
                st.dataframe(t, hide_index=True, filters=False,
                             src='usage_events', asof=_dt.date.today().isoformat())
            elif visitors:
                st.caption(f'방문자 {visitors}명은 있으나 탭 열람 기록이 없습니다 — 기록 코드(access.track)를 확인해야 합니다.')
            else:
                st.caption('소유자 외 방문자가 아직 없습니다. 기록은 2026-11-12 부터 쌓입니다 — 사람이 들어와야 숫자가 생깁니다.')
        except Exception as e:
            st.caption(f'`사용 기록 읽기 실패: {str(e)[:100]}`')


# 탭마다 '여기에 무엇을 넣는 곳인가'를 한 줄로. 쓰는 사람이 나 혼자라도 석 달 뒤의 나는 남이다.
_GUIDE = {
    'roadmap': '무엇을 언제까지 만들 것인가. 기한과 진행률이 있는 일만 넣습니다 — 아이디어는 결정 로그에 제안으로 올립니다.',
    'decision': '되돌리기 어려운 선택과 그 근거. 제안 → 승인·기각으로 닫고, 승인된 것만 로드맵으로 내려보냅니다.',
    'issue': '지금 잘못돼 있는 것. 종류를 사고로 두면 스코어카드 운영 사고·무사고 연속 주에 자동 반영됩니다.',
    'meeting': '주간·월간 리뷰에서 오간 말. 여기서 나온 결정은 반드시 결정 로그에도 남깁니다.',
    'kpi': '무엇을 숫자로 볼 것인가. 자동 KPI 는 화면을 열 때 계산되고, 수동 KPI 는 스코어카드에서 손으로 넣습니다.',
}

_LABELS = {'title': '제목', 'status': '상태', 'dept': '부서', 'owner': '담당', 'period': '기간·종류',
           'due': '기한', 'progress': '진행률(%)', 'updated_at': '마지막 수정', 'updated_by': '수정자'}


def _items(st, kind, actor):
    label, statuses = gov.KINDS[kind]
    show_del = st.toggle('숨긴 항목도 보기', key=f'gov_del_{kind}')
    rows = gov.items(kind, include_deleted=show_del)
    if kind == 'issue':
        st.caption("종류 '사고'로 열린 이슈는 스코어카드 '운영 사고'·'무사고 연속 주'에 자동 반영됩니다.")
    if rows:
        df = pd.DataFrame(rows)
        df['updated_at'] = pd.to_datetime(df['updated_at']).dt.tz_convert('Asia/Seoul').dt.strftime('%m-%d %H:%M')
        if kind == 'issue':
            df['종류'] = [(m or {}).get('type', '') for m in df['meta']]
        if kind == 'kpi':
            df['key'] = [(m or {}).get('key', '') for m in df['meta']]
            df['목표'] = [(m or {}).get('target') for m in df['meta']]
        cols = ['id', 'title', 'status', 'dept', 'owner', 'period', 'due', 'progress', 'updated_at', 'updated_by']
        cols = [c for c in cols if c in df] + [c for c in ('종류', 'key', '목표') if c in df]
        if show_del:
            df['숨김'] = df['deleted'].map({True: '🗑', False: ''}); cols.append('숨김')
        view = df[cols].rename(columns={**_LABELS, 'id': 'ID'})
        view = view.dropna(axis=1, how='all')
        st.dataframe(view, hide_index=True, src=f'경영실 gov_items ({kind})', asof=_dt.date.today().isoformat())
    else:
        st.caption('아직 항목이 없습니다.')

    pick = st.selectbox('편집할 항목', ['➕ 새로 추가'] + [f"#{r['id']} {r['title']}" for r in rows], key=f'gov_pick_{kind}')
    cur = {} if pick.startswith('➕') else next(r for r in rows if f"#{r['id']} {r['title']}" == pick)
    meta = dict(cur.get('meta') or {})
    with st.form(f'gov_form_{kind}_{cur.get("id", "new")}'):
        title = st.text_input('제목', cur.get('title', ''))
        c1, c2, c3 = st.columns(3)
        status = c1.selectbox('상태', statuses, index=statuses.index(cur['status']) if cur.get('status') in statuses else 0)
        dept = c2.selectbox('부서', gov.DEPTS, index=gov.DEPTS.index(cur['dept']) if cur.get('dept') in gov.DEPTS else 0)
        owner = c3.text_input('담당', cur.get('owner') or '')
        c4, c5, c6 = st.columns(3)
        if kind == 'meeting':
            period = c4.selectbox('회의 종류', gov.MEETINGS,
                                  index=gov.MEETINGS.index(cur['period']) if cur.get('period') in gov.MEETINGS else 0)
        else:
            period = c4.text_input('기간(예: 2027-Q1)', cur.get('period') or '')
        due0 = _dt.date.fromisoformat(cur['due']) if cur.get('due') else None
        due = c5.date_input('기한·날짜', value=due0)
        prog = c6.number_input('진행률(%)', 0, 100, value=int(cur['progress']) if cur.get('progress') is not None else 0) \
            if kind == 'roadmap' else None
        if kind == 'issue':
            types = ['사고', '버그', '위험', '개선']
            meta['type'] = st.selectbox('종류', types, index=types.index(meta['type']) if meta.get('type') in types else 0)
        if kind == 'kpi':
            k1, k2, k3, k4 = st.columns(4)
            meta['key'] = k1.text_input('key(영문, 바꾸면 기존 값과 끊김)', meta.get('key', ''))
            meta['tier'] = k2.selectbox('단계', ['회사', '부서'], index=0 if meta.get('tier') == '회사' else 1)
            meta['unit'] = k3.text_input('단위', meta.get('unit', ''))
            meta['target'] = k4.number_input('목표', value=meta.get('target'), format='%.2f')
            k5, k6 = st.columns(2)
            meta['better'] = k5.selectbox('좋은 방향', ['up', 'down'], index=0 if meta.get('better', 'up') == 'up' else 1)
            meta['auto'] = k6.checkbox('자동 계산', value=bool(meta.get('auto')))
        body = st.text_area('내용 (근거·결론·다음 행동 — 마크다운)', cur.get('body') or '', height=160)
        b1, b2 = st.columns([1, 1])
        save = b1.form_submit_button('💾 저장', type='primary')
        hide = b2.form_submit_button('🗑 숨기기' if not cur.get('deleted') else '♻️ 되살리기', disabled=not cur)
    if save:
        if not title.strip():
            st.warning('제목이 비었습니다')
        else:
            gov.save_item({'id': cur.get('id'), 'kind': kind, 'title': title.strip(), 'status': status, 'dept': dept,
                           'owner': owner, 'period': period, 'due': due, 'progress': prog, 'body': body, 'meta': meta}, actor)
            st.success('저장했습니다 — 변경 이력에 남았습니다'); st.rerun()
    if hide and cur:
        (gov.restore_item if cur.get('deleted') else gov.delete_item)(cur['id'], actor)
        st.rerun()
    if cur:
        if cur.get('body'):
            with st.expander('📄 내용 보기', expanded=False):
                st.markdown(cur['body'])
        with st.expander(f"🕘 #{cur['id']} 수정 이력"):
            _history(st, 'gov_items', str(cur['id']))


def _history(st, tbl=None, row_key=None):
    if tbl is None:
        c1, c2 = st.columns([1, 1])
        pickt = c1.selectbox('대상', ['전체', 'gov_items', 'gov_kpi_weekly'], key='gov_h_t')
        hide_auto = c2.toggle('자동 계산 값 숨기기', value=True, key='gov_h_auto')
        tbl = None if pickt == '전체' else pickt
    else:
        hide_auto = False
    try:
        rows = gov.audit(500, tbl, row_key)
    except Exception as e:
        st.caption(f'`이력 읽기 실패: {str(e)[:100]}`'); return
    if hide_auto:
        rows = [r for r in rows if r.get('actor') != 'auto']
    if not rows:
        st.caption('이력이 없습니다.'); return
    out = []
    for r in rows:
        a, b = r.get('before'), r.get('after')
        o = b or a or {}
        what = o.get('title') or (f"{o.get('key')} @ {o.get('week')}" if o.get('key') else r['row_key'])
        out.append({'시각': pd.Timestamp(r['at']).tz_convert('Asia/Seoul').strftime('%Y-%m-%d %H:%M'),
                    '대상': {'gov_items': (o.get('kind') or '항목'), 'gov_kpi_weekly': 'KPI 값'}.get(r['tbl'], r['tbl']),
                    '항목': str(what)[:50], '동작': {'INSERT': '추가', 'UPDATE': '수정', 'DELETE': '삭제'}.get(r['action'], r['action']),
                    '수정자': r.get('actor'), '바뀐 내용': gov.diff(a, b)})
    st.dataframe(pd.DataFrame(out), hide_index=True, src='gov_audit(DB 트리거 — 앱이 지울 수 없음)',
                 asof=out[0]['시각'])
