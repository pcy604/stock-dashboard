"""kr_flow 진단 5차 — trendDeposit 호스트·응답 형식."""
import requests
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36', 'Referer': 'https://finance.naver.com/market/stock/kr/deposit'}
for h in ('https://finance.naver.com', 'https://m.stock.naver.com', 'https://stock.naver.com', 'https://m.stock.naver.com/front-api', 'https://finance.naver.com/front-api'):
    for q in ('', '?page=1&pageSize=20', '?pageSize=20'):
        u = f'{h}/api/domestic/market/trendDeposit{q}'
        try:
            r = requests.get(u, headers=UA, timeout=10)
            print('==', r.status_code, u, r.headers.get('content-type', '')[:30]); print(r.text[:500])
        except Exception as e:
            print('== ERR', u, e)
