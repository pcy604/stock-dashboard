"""kr_flow 수집 경로 진단(일회성) — Actions 에서 어떤 주소가 살아 있는지."""
import io, requests, pandas as pd
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36', 'Referer': 'https://finance.naver.com/'}
C = [
 'https://finance.naver.com/sise/investorDealTrendDay.nhn?bizdate=20261106&sosok=01&page=1',
 'https://finance.naver.com/sise/investorDealTrendDay.naver?bizdate=20261106&sosok=&page=1',
 'https://finance.naver.com/sise/sise_trans_style.naver',
 'https://m.stock.naver.com/api/index/KOSPI/trend',
 'https://m.stock.naver.com/api/index/KOSPI/investor',
 'https://m.stock.naver.com/api/index/KOSPI/investorTrend',
 'https://m.stock.naver.com/api/index/KOSPI/price?pageSize=3&page=1',
 'https://api.stock.naver.com/index/KOSPI/trend',
 'https://m.stock.naver.com/front-api/index/investorTrend?indexCode=KOSPI',
 'https://finance.naver.com/sise/sise_deposit.naver?page=1',
]
for u in C:
    try:
        r = requests.get(u, headers=UA, timeout=12); r.encoding = r.encoding or 'euc-kr'
        if 'finance.naver.com' in u: r.encoding = 'euc-kr'
        print('==', r.status_code, u, len(r.text)); print(r.text[:400].replace('\n', ' '))
        if 'deposit' in u or 'trans_style' in u or 'DealTrend' in u:
            try:
                for t in pd.read_html(io.StringIO(r.text)):
                    print('  table', t.shape, list(map(str, t.columns))[:12]); print(t.head(4).to_string()[:600])
            except Exception as e:
                print('  read_html', e)
    except Exception as e:
        print('== ERR', u, e)
try:
    from pykrx import stock
    d = stock.get_market_trading_value_by_date('20261020', '20261106', 'KOSPI')
    print('pykrx', d.shape); print(d.tail(3))
except Exception as e:
    print('pykrx ERR', type(e).__name__, str(e)[:200])
