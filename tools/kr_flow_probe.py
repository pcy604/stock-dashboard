"""kr_flow 수집 경로 진단(일회성) — 2차."""
import io, requests, pandas as pd
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36', 'Referer': 'https://finance.naver.com/'}
def get(u, enc):
    r = requests.get(u, headers=UA, timeout=12); r.encoding = enc; return r
for u, enc in [('https://finance.naver.com/sise/investorDealTrendDay.nhn?bizdate=20261106&sosok=01&page=2', 'euc-kr'),
               ('https://finance.naver.com/sise/investorDealTrendDay.nhn?bizdate=20261106&sosok=02&page=1', 'euc-kr'),
               ('https://finance.naver.com/sise/sise_deposit.naver?page=1', 'utf-8'),
               ('https://finance.naver.com/sise/sise_deposit.nhn?page=1', 'euc-kr')]:
    r = get(u, enc); print('==', r.status_code, u, len(r.text))
    try:
        for t in pd.read_html(io.StringIO(r.text)):
            print('  table', t.shape); print(t.dropna(how='all').head(6).to_string()[:1500])
    except Exception as e:
        print('  read_html', e)
for u in ['https://m.stock.naver.com/api/index/KOSDAQ/trend', 'https://m.stock.naver.com/api/index/KOSPI/trend?pageSize=20&page=1',
          'https://m.stock.naver.com/api/index/KOSPI/trend?bizdate=20261105']:
    r = get(u, 'utf-8'); print('==', r.status_code, u); print(r.text[:300])
r = get('https://finance.naver.com/sise/sise_deposit.naver?page=1', 'utf-8')
import re
i = r.text.find('신용잔고'); print('deposit ctx', r.text[i-200:i+1500].replace('\n', ' ') if i >= 0 else 'none')
