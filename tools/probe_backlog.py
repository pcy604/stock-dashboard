# -*- coding: utf-8 -*-
"""수주 데이터 확보 가능성 점검 (2026-11-10, 차니 "점검하자")

질문: 실적보다 먼저 움직이는 '수주'를 한국 전 종목·과거 분기로 모을 수 있나?
원천 두 가지를 DART 에서 재 본다.
  ① 정기보고서(분기·반기·사업) '매출 및 수주상황' 표 — 수주잔고 합계를 숫자로 뽑을 수 있나, 몇 년치까지
  ② 수시공시 '단일판매ㆍ공급계약체결' — 건수·날짜(구조화된 목록, 금액은 본문)
표본: 2026 주도 장비·전력·조선 13종 + 시총 상위·무작위 30종(고정 시드).
결과: data/research/probe_backlog.json  (클라우드 러너에서 실행 — 작업 환경은 DART 차단)
"""
import io, json, os, re, sys, time, zipfile, random
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import dart_client as D

FOCUS = {'036930': '주성엔지니어링', '031980': '피에스케이홀딩스', '319660': '피에스케이', '240810': '원익IPS',
         '042700': '한미반도체', '039030': '이오테크닉스', '095610': '테스', '267260': 'HD현대일렉트릭',
         '012450': '한화에어로스페이스', '010120': 'LS ELECTRIC', '010140': '삼성중공업', '298040': '효성중공업',
         '010170': '대한광통신'}
NUM = re.compile(r'-?\d{1,3}(?:,\d{3})+|-?\d+(?:\.\d+)?')


def doc_text(rcept_no):
    r = D._get(f"{D.BASE}/document.xml", {'crtfc_key': D._key(), 'rcept_no': rcept_no})
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    best = max(zf.namelist(), key=lambda n: zf.getinfo(n).file_size)
    xml = zf.read(best).decode('utf-8', 'replace')
    t = re.sub(r'<[^>]+>', ' ', xml)
    t = re.sub(r'&[a-zA-Z#0-9]+;', ' ', t)
    return re.sub(r'\s+', ' ', t)


def backlog_from(txt):
    """'수주상황' 절에서 '합계' 줄의 마지막 숫자(=수주잔고 금액 열이 보통 맨 끝)를 뽑는다. 못 뽑으면 이유."""
    i = -1
    for key in ('수주상황', '수주 상황', '수주현황', '수주 현황'):
        i = txt.find(key, txt.find('사업의 내용') if '사업의 내용' in txt else 0)
        if i >= 0:
            break
    if i < 0:
        return dict(section=False)
    seg = txt[i:i + 4000]
    has_bl = '수주잔고' in seg or '수주 잔고' in seg
    unit = next((u for u in ('백만원', '천원', '억원', '원') if f'단위 : {u}' in seg or f'단위: {u}' in seg or f'단위:{u}' in seg), None)
    m = re.search(r'합\s*계(.{0,300})', seg)
    tot = None
    if m:
        nums = [x for x in NUM.findall(m.group(1)) if len(x.replace(',', '').replace('-', '')) >= 2]
        if nums:
            tot = nums[-1]
    return dict(section=True, has_backlog_word=has_bl, unit=unit, total_raw=tot, snippet=seg[:400])


def periodic(corp, bgn='20180101'):
    out, page = [], 1
    while page < 6:
        j = D._get(f"{D.BASE}/list.json", {'crtfc_key': D._key(), 'corp_code': corp, 'pblntf_ty': 'A',
                                         'bgn_de': bgn, 'end_de': time.strftime('%Y%m%d'), 'page_no': page, 'page_count': 100}).json()
        if j.get('status') != '000':
            break
        out += j.get('list', [])
        if page >= int(j.get('total_page', 1)):
            break
        page += 1
    return [x for x in out if any(k in x['report_nm'] for k in ('분기보고서', '반기보고서', '사업보고서')) and '기재정정' not in x['report_nm']]


def contracts(corp, bgn='20240101'):
    j = D._get(f"{D.BASE}/list.json", {'crtfc_key': D._key(), 'corp_code': corp, 'pblntf_ty': 'I',
                                     'bgn_de': bgn, 'end_de': time.strftime('%Y%m%d'), 'page_count': 100}).json()
    lst = j.get('list', []) if j.get('status') == '000' else []
    return [dict(date=x['rcept_dt'], nm=x['report_nm']) for x in lst if '공급계약' in x['report_nm']]


def main():
    cm = D.corp_map()                                     # stock_code → corp_code
    inv = cm
    syms = list(FOCUS)
    try:
        import pandas as pd
        u = pd.read_csv('data/universe_ever.csv', dtype=str)
        col = next(c for c in u.columns if c.lower() in ('sym', 'code', 'symbol', 'ticker'))
        kr = [s for s in u[col].dropna().unique() if len(s) == 6 and s.isdigit()]
        random.Random(20261110).shuffle(kr)
        syms += [s for s in kr if s not in FOCUS][:30]
    except Exception as e:
        print('universe 실패', e)
    res = []
    for s in syms:
        corp = inv.get(s) if isinstance(inv, dict) else None
        if not corp:
            res.append(dict(sym=s, err='corp_code 없음')); continue
        row = dict(sym=s, name=FOCUS.get(s), corp=corp)
        try:
            P = periodic(corp)
            row['n_periodic'] = len(P)
            row['first_periodic'] = P[-1]['rcept_dt'] if P else None
            deep = s in FOCUS
            pick = P if deep else P[:2]                   # 주도주 13종은 2018~ 전부, 나머지는 최근 2개
            hist = []
            for x in pick[:36]:
                try:
                    b = backlog_from(doc_text(x['rcept_no']))
                except Exception as e:
                    b = dict(err=str(e)[:80])
                b.pop('snippet', None) if len(hist) else None
                hist.append(dict(date=x['rcept_dt'], report=x['report_nm'], **b))
                time.sleep(0.3)
            row['periodic'] = hist
            row['contracts_2024_'] = contracts(corp)
        except Exception as e:
            row['err'] = str(e)[:120]
        res.append(row)
        print(s, row.get('name'), row.get('n_periodic'), len(row.get('contracts_2024_', [])), flush=True)
    def ok(h):
        return h.get('section') and h.get('total_raw')
    summ = dict(
        n=len(res),
        latest_has_section=sum(1 for r in res if r.get('periodic') and r['periodic'][0].get('section')),
        latest_parsed=sum(1 for r in res if r.get('periodic') and ok(r['periodic'][0])),
        with_contract_filings=sum(1 for r in res if r.get('contracts_2024_')),
        focus_hist_parse_rate={r['sym']: f"{sum(ok(h) for h in r['periodic'])}/{len(r['periodic'])}"
                               for r in res if r['sym'] in FOCUS and r.get('periodic')})
    os.makedirs('data/research', exist_ok=True)
    json.dump(dict(run=time.strftime('%Y-%m-%d %H:%M'), summary=summ, rows=res),
              open('data/research/probe_backlog.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(summ, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
