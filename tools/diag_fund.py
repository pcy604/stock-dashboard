"""재무파일(fq_) 없는 미국 유니버스 종목 분류 (2026-10-19). leaders_cache 가 있는 러너에서 돈다."""
import os, collections
import pandas as pd

u = pd.read_csv('data/leaders_cache/_universe.csv')
have = {f[3:-4] for f in os.listdir('data/leaders_cache') if f.startswith('fq_')}
miss = u[~u.sym.isin(have)].copy()
dom = pd.read_csv('data/us_domicile.csv').set_index('sym')
mc = pd.read_csv('data/us_marketcap.csv').set_index('Symbol').marketcap
miss['country'] = miss.sym.map(dom.country)
miss['sic'] = miss.sym.map(dom.sic)
miss['cap_b'] = (miss.sym.map(mc) / 1e9).round(1)
def kind(r):
    s = r.sic
    if pd.isna(s): return 'SIC 없음'
    s = int(s)
    if 6000 <= s < 6300: return '은행·증권(6000-6299)'
    if 6300 <= s < 6500: return '보험(6300-6499)'
    if s in (6798,): return '리츠(6798)'
    if 6500 <= s < 7000: return '부동산·투자(6500-6999)'
    if s == 2834 or s == 2836: return '제약·바이오(2834/2836)'
    return '기타 업종'
miss['kind'] = miss.apply(kind, axis=1)
print(f"::notice title=재무파일 없음::{len(miss)}/{len(u)}종")
for k, n in miss.kind.value_counts().items():
    ex = miss[miss.kind == k].sort_values('cap_b', ascending=False).head(10)
    print(f"::notice title=없음 · {k} {n}종::" + ', '.join(f"{r.sym}({r.cap_b}B)" for r in ex.itertuples()))
print(f"::notice title=없음 · 국가::{dict(miss.country.value_counts())}")
top = miss.sort_values('cap_b', ascending=False).head(25)
print("::notice title=없음 · 시총 상위 25::" + ', '.join(f"{r.sym}({r.cap_b}B,{r.sic})" for r in top.itertuples()))
