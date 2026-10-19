# -*- coding: utf-8 -*-
"""KR 분기재무 주간 갱신 — 네이버 기업분석(FnGuide) 경로 · 2026-10-19

왜
  DART 는 해외 서버(GitHub Actions·Streamlit Cloud)의 연결을 받지 않는다(2026-10-15 전후~).
  그래서 data/kr_fundamentals_q.parquet 는 집 PC 가 돌 때만 갱신됐고, 10-14 이후 멈췄다.
  네이버 기업분석은 해외에서 닿고, 공시와 대조해 일치를 확인한 모듈(kr_fin_naver)이 이미 있다.

원칙
  · **과거는 DART 가 기준이다.** 이미 있는 DART 값(매출·영업이익·순이익)은 덮어쓰지 않는다.
    네이버는 ① 비어 있는 칸 ② 새 분기 ③ 대차 잔액(자산·부채·자본 — DART 저장본에 없던 열)만 채운다.
  · 겹치는 분기는 매출을 대조한다. 어긋나는 종목이 많으면 **쓰지 않고 실패**한다
    (페이지 구조가 바뀌어 숫자가 엉뚱하게 읽히는 고장을 조용히 저장하지 않게).
  · 결산월이 12월이 아닌 회사는 건너뛴다 — 네이버 분기 표기(달력 월)와 DART 분기(회계 분기)가
    어긋나 같은 칸에 다른 분기가 들어간다.

  python kr_fundq_naver.py            # 전 종목
  python kr_fundq_naver.py --limit 30 # 시험
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import kr_fin_naver as N  # noqa: E402

OUT = ROOT / 'data' / 'kr_fundamentals_q.parquet'
FLOWS = ('revenue', 'op_income', 'net_income')
BAL = ('assets', 'liabilities', 'equity')
MISMATCH_TOL = 0.03          # 매출 3% 넘게 다르면 불일치
MAX_MISMATCH_RATE = 0.10     # 겹치는 종목의 10% 넘게 불일치면 쓰지 않는다
MIN_OK_RATE = 0.70           # 시도 종목의 70% 미만만 받아지면 쓰지 않는다


def _yq(period: str):
    """'2026.2Q' → (2026, 2) / '2025' → (2025, 4)"""
    if '.' in period:
        return int(period[:4]), int(period[5])
    return int(period[:4]), 4


def fetch_one(code: str) -> list[dict]:
    """한 종목 → parquet 행(dict) 목록. 결산월이 12월이 아니면 [] (호출부가 '건너뜀'으로 센다)."""
    code = str(code).zfill(6)
    s, enc, ref = N._session(code)
    got = {}
    for frq in (1, 0):                                   # 1=분기, 0=연간
        freq = 'quarter' if frq == 1 else 'annual'
        for rpt in (0, 1):                               # 0=손익, 1=재무상태
            js = N._report(s, enc, ref, code, frq, rpt)
            if frq == 0 and rpt == 0:
                ym = [str(y) for y in js.get('YYMM') or []]
                ends = {y[5:7] for y in ym if len(y) >= 7 and y[:4].isdigit() and y[4] == '/'}
                if ends and ends != {'12'}:
                    return []                            # 12월 결산 아님
            for p, kv in N.parse(js, rpt, freq).items():
                got.setdefault((freq, p), {}).update(kv)
            time.sleep(0.1)
    rows = {}
    for (freq, p), kv in got.items():
        y, q = _yq(p)
        if freq == 'quarter' and q == 4:
            # 4분기 '흐름'은 3개월치다. 저장본의 q=4 는 **연간 합계** 규칙이므로 연간 표에서 받는다.
            kv = {k: v for k, v in kv.items() if k in BAL}
        if freq == 'annual':
            kv = {k: v for k, v in kv.items() if k in FLOWS + BAL}
        r = rows.setdefault((y, q), {'sym': code, 'year': y, 'q': q})
        for k in FLOWS + BAL:
            if kv.get(k) is not None and r.get(k) is None:
                r[k] = kv[k]
    return [r for r in rows.values() if any(r.get(k) is not None for k in FLOWS + BAL)]


def merge(old: pd.DataFrame, new_rows: list[dict], today: str):
    """DART 값 우선 병합. 반환 (df, stats)."""
    df = old.copy()
    for c in BAL:
        if c not in df:
            df[c] = float('nan')
    key = ['sym', 'year', 'q']
    nw = pd.DataFrame(new_rows)
    if nw.empty:
        return df, dict(new=0, filled=0, overlap_syms=0, mismatch_syms=0, mismatch=[], detail=pd.DataFrame())
    for c in FLOWS + BAL:
        if c not in nw:
            nw[c] = float('nan')
    m = df.merge(nw, on=key, how='left', suffixes=('', '_n'), indicator=False)
    # 대조 — 매출이 둘 다 있는 겹치는 칸
    both = m[m.revenue.notna() & m.revenue_n.notna() & (m.revenue.abs() > 0)]
    bad = both[((both.revenue_n - both.revenue).abs() / both.revenue.abs()) > MISMATCH_TOL]
    ov_syms = set(both.sym)
    bad_syms = set(bad.sym)
    detail = (bad.assign(ratio=bad.revenue_n / bad.revenue)
                 [['sym', 'year', 'q', 'revenue', 'revenue_n', 'ratio']]
                 .sort_values(['sym', 'year', 'q']))
    # 2026-10-19 — 통화가 다른 DART 값(USD·CNY 공시를 원화로 저장한 것). 겹치는 분기의 매출 비율이
    #   전부 50배를 넘으면 단위가 다른 것이다(실측: 잉글우드랩 1,144~1,484 = 원/달러, 오가닉티 ~197 = 원/위안).
    #   이 종목들은 네이버(원화 환산) 값으로 덮고, 네이버가 없는 과거 칸은 단위를 모르므로 비운다.
    _r = both.assign(_x=both.revenue_n / both.revenue).groupby('sym')._x.agg(['min', 'count'])
    fx_syms = set(_r[(_r['min'] > 50) & (_r['count'] >= 2)].index)
    fx_cells = 0
    if fx_syms:
        sel = m.sym.isin(fx_syms)
        for c in FLOWS:
            has_n = sel & m[f'{c}_n'].notna()
            m.loc[has_n, c] = m.loc[has_n, f'{c}_n']
            no_n = sel & m[f'{c}_n'].isna()
            fx_cells += int(no_n.sum())
            m.loc[no_n, c] = float('nan')
        m.loc[sel, 'fs_div'] = m.loc[sel, 'fs_div'].astype(str).str.replace('-NAVERFX', '') + '-NAVERFX'
        bad_syms = bad_syms - fx_syms
    filled = 0
    for c in FLOWS + BAL:
        fill = m[c].isna() & m[f'{c}_n'].notna()
        filled += int(fill.sum())
        m.loc[fill, c] = m.loc[fill, f'{c}_n']
    m = m.drop(columns=[f'{c}_n' for c in FLOWS + BAL])
    # 새 분기
    have = set(map(tuple, df[key].astype({'sym': str}).values.tolist()))
    add = nw[[tuple(x) not in have for x in nw[key].astype({'sym': str}).values.tolist()]].copy()
    add['fs_div'] = 'NAVER'
    add['updated'] = today
    out = pd.concat([m, add[m.columns.intersection(add.columns)]], ignore_index=True)
    out = out.sort_values(key).reset_index(drop=True)
    return out, dict(new=len(add), filled=filled, overlap_syms=len(ov_syms),
                     mismatch_syms=len(bad_syms), mismatch=sorted(bad_syms)[:20], detail=detail,
                     fx_syms=sorted(fx_syms), fx_cleared=fx_cells)


def main(limit: int | None = None, workers: int = 4):
    old = pd.read_parquet(OUT)
    old['sym'] = old.sym.astype(str)
    syms = sorted(old.sym.unique())
    try:
        k = pd.read_csv(ROOT / 'data' / 'krx_listing_last.csv', dtype={'Code': str})
        syms = sorted(set(syms) | set(k.loc[(k.Marcap >= 1e11) & k.Code.str.fullmatch(r'\d{6}'), 'Code']))
    except Exception:
        pass
    if limit:
        syms = syms[:limit]
    print(f"네이버 분기재무 — {len(syms):,}종 시도", flush=True)
    rows, ok, skip, fail = [], 0, 0, []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        fut = {ex.submit(fetch_one, s): s for s in syms}
        for i, f in enumerate(as_completed(fut), 1):
            s = fut[f]
            try:
                r = f.result()
                if r:
                    rows += r
                    ok += 1
                else:
                    skip += 1
            except Exception as e:
                fail.append((s, f"{type(e).__name__}: {str(e)[:60]}"))
            if i % 200 == 0:
                print(f"  {i:,}/{len(syms):,} · 성공 {ok:,} · 비12월 {skip:,} · 실패 {len(fail):,}", flush=True)
    tried = len(syms) - skip
    ok_rate = ok / tried if tried else 0
    df, st = merge(old, rows, str(date.today()))
    mis_rate = st['mismatch_syms'] / st['overlap_syms'] if st['overlap_syms'] else 0
    eq_fill = df.equity.notna().mean()
    summary = (f"성공 {ok:,}/{tried:,} ({ok_rate:.0%}) · 비12월 결산 {skip:,} · 실패 {len(fail):,} | "
               f"새 분기 {st['new']:,}행 · 빈칸 채움 {st['filled']:,} · "
               f"매출 불일치 {st['mismatch_syms']:,}/{st['overlap_syms']:,}종 ({mis_rate:.0%}) · "
               f"자본 채움률 {eq_fill:.0%} | 외화 공시 교정 {len(st.get('fx_syms', [])):,}종"
               f"(과거 칸 비움 {st.get('fx_cleared', 0):,})")
    print(summary, flush=True)
    print(f"::notice title=KR 분기재무(네이버)::{summary}", flush=True)
    if fail:
        print("실패 예:", fail[:5], flush=True)
    if st['mismatch']:
        print("불일치 예:", st['mismatch'], flush=True)
    # 불일치 상세를 남긴다 — 원인(연결/별도·금융업·결산 차이)을 사람이 분류할 수 있게
    try:
        det = st['detail']
        if len(det):
            nm = {}
            try:
                k = pd.read_csv(ROOT / 'data' / 'krx_listing_last.csv', dtype={'Code': str})
                nm = dict(zip(k.Code, k.Name))
            except Exception:
                pass
            det = det.assign(name=det.sym.map(nm))
            (ROOT / 'results').mkdir(exist_ok=True)
            # .json — results/*.csv 는 .gitignore 라 커밋 단계에서 git add 가 실패한다
            det.to_json(ROOT / 'results' / 'kr_fin_mismatch.json', orient='records', force_ascii=False, indent=1)
            print(f"불일치 상세 {len(det):,}칸 → results/kr_fin_mismatch.json", flush=True)
    except Exception as e:
        print(f"[warn] 불일치 상세 저장 실패: {e}", flush=True)
    if ok_rate < MIN_OK_RATE:
        print(f"::error::네이버 수집 성공률 {ok_rate:.0%} (<{MIN_OK_RATE:.0%}) — 페이지 구조 변경·차단 의심. 저장하지 않는다")
        raise SystemExit(1)
    if mis_rate > MAX_MISMATCH_RATE:
        print(f"::error::DART 대비 매출 불일치 {mis_rate:.0%} (>{MAX_MISMATCH_RATE:.0%}) — 읽는 격자가 어긋났을 가능성. 저장하지 않는다")
        raise SystemExit(1)
    if len(df) < len(old):
        print("::error::결과 행 수가 기존보다 적다 — 저장하지 않는다")
        raise SystemExit(1)
    if not limit:
        df.to_parquet(OUT, index=False)
        print(f"저장 {OUT.name} — {len(df):,}행", flush=True)
    else:
        print("--limit 시험 실행 — 저장하지 않음", flush=True)


if __name__ == '__main__':
    lim = None
    if '--limit' in sys.argv:
        lim = int(sys.argv[sys.argv.index('--limit') + 1])
    main(lim)
