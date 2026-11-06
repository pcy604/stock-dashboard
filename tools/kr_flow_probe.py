"""kr_flow 수집 경로 진단(일회성) — 3차: 증시자금동향 데이터 API 찾기."""
import re, requests
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36', 'Referer': 'https://finance.naver.com/sise/sise_deposit.naver'}
r = requests.get('https://finance.naver.com/sise/sise_deposit.naver', headers=UA, timeout=12); r.encoding = 'utf-8'
t = r.text
print('apis', sorted(set(re.findall(r'["\'](/[a-zA-Z0-9_\-/]*api[a-zA-Z0-9_\-/]*)', t)))[:40])
print('urls', sorted(set(re.findall(r'https?://[a-zA-Z0-9.\-]+/[a-zA-Z0-9_\-/]*(?:api|deposit)[a-zA-Z0-9_\-/]*', t)))[:40])
js = sorted(set(re.findall(r'/_next/static/chunks/[^"\']+\.js', t)))
print('chunks', len(js))
for j in js:
    try:
        c = requests.get('https://finance.naver.com' + j if j.startswith('/') else j, headers=UA, timeout=10).text
    except Exception:
        try:
            c = requests.get('https://ssl.pstatic.net/imgstock/fn/real/pc' + j, headers=UA, timeout=10).text
        except Exception:
            continue
    for m in set(re.findall(r'["`\'][^"`\']{0,80}(?:eposit|redit)[^"`\']{0,80}["`\']', c)):
        print('  ', j[-40:], m[:170])
for u in ['https://finance.naver.com/api/sise/deposit?page=1', 'https://finance.naver.com/api/sise/deposits?page=1',
          'https://m.stock.naver.com/api/sise/deposit', 'https://m.stock.naver.com/front-api/sise/deposit',
          'https://finance.naver.com/front-api/sise/deposit?page=1', 'https://finance.naver.com/front-api/sise/deposit']:
    try:
        x = requests.get(u, headers=UA, timeout=10); print('==', x.status_code, u, x.text[:250])
    except Exception as e:
        print('== ERR', u, e)
