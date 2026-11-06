"""kr_flow 진단 4차 — 증시자금동향 page 청크에서 데이터 주소 찾기."""
import re, requests
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36', 'Referer': 'https://finance.naver.com/sise/sise_deposit.naver'}
t = requests.get('https://finance.naver.com/sise/sise_deposit.naver', headers=UA, timeout=12).text
urls = sorted(set(re.findall(r'https://ssl\.pstatic\.net/imgstock/fn/real/pc/_next/static/chunks/[^"\'\s\\]+', t)))
print(len(urls))
seen = set()
for u in urls:
    if not u.endswith('.js'):
        u += '.js'
    try:
        c = requests.get(u, headers=UA, timeout=10).text
    except Exception as e:
        print('ERR', u, e); continue
    for m in re.findall(r'["`\'](?:https?:)?//?[a-zA-Z0-9.\-]*/?[^"`\'\s]{0,120}["`\']', c):
        if any(k in m.lower() for k in ('api', 'deposit', 'credit', 'fund')) and m not in seen:
            seen.add(m); print(u.split('/chunks/')[-1][:50], m[:180])
i = t.find('__next_f'); print('next_f count', t.count('self.__next_f.push'))
for k in ('depositAmount', 'creditBalance', 'customerDeposit', 'deposit'):
    j = t.find(k); print(k, t[j-100:j+300].replace('\n', ' ') if j >= 0 else '-')
