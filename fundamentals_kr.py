"""한국 종목 상세 정보: pykrx + 네이버금융 스크래핑"""
import contextlib
import io
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
from datetime import datetime

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}


def _safe(val, digits=2):
    try:
        if pd.isna(val):
            return None
        return round(float(val), digits)
    except:
        return None


def get_pykrx_data(ticker: str) -> dict:
    result = {'per': None, 'pbr': None, 'eps': None, 'bps': None,
              'div': None, 'market_cap': None, 'price': None, 'roe': None}
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            from pykrx import stock
            today = datetime.now().strftime('%Y%m%d')

            f = stock.get_market_fundamental(today, today, ticker)
            if not f.empty:
                row = f.iloc[-1]
                result['per'] = _safe(row.get('PER'))
                result['pbr'] = _safe(row.get('PBR'))
                result['eps'] = _safe(row.get('EPS'), 0)
                result['bps'] = _safe(row.get('BPS'), 0)
                result['div'] = _safe(row.get('DIV'))
                if result['eps'] and result['bps'] and result['bps'] != 0:
                    result['roe'] = _safe(result['eps'] / result['bps'] * 100)

            cap = stock.get_market_cap(today, today, ticker)
            if not cap.empty:
                row = cap.iloc[-1]
                result['market_cap'] = int(row.get('시가총액', 0))
                result['price'] = int(row.get('종가', 0))
    except:
        pass
    return result


def get_naver_earnings(ticker: str) -> list:
    """네이버금융에서 분기 실적 파싱 (매출/영업익/순익)"""
    try:
        url = f'https://finance.naver.com/item/coinfo.naver?code={ticker}&target=finsum_D'
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')

        table = soup.select_one('table.tb_type1')
        if not table:
            return []

        rows = table.select('tr')
        quarters, revenues, op_incomes, net_incomes = [], [], [], []

        for row in rows:
            cells = row.select('th, td')
            texts = [c.get_text(strip=True) for c in cells]
            if not texts:
                continue
            header = texts[0]
            if re.match(r'\d{4}\.\d{1,2}', header):
                quarters.append(header)
                def parse_num(s):
                    s = s.replace(',', '').replace('-', '').strip()
                    try:
                        return int(s)
                    except:
                        return None
                revenues.append(parse_num(texts[1]) if len(texts) > 1 else None)
                op_incomes.append(parse_num(texts[2]) if len(texts) > 2 else None)
                net_incomes.append(parse_num(texts[3]) if len(texts) > 3 else None)

        results = []
        for i in range(min(5, len(quarters))):
            results.append({
                'quarter': quarters[i],
                'revenue': revenues[i],
                'op_income': op_incomes[i],
                'net_income': net_incomes[i],
            })
        return results
    except:
        return []


def get_naver_analyst_reports(ticker: str, max_reports=5) -> list:
    """네이버금융 증권사 리포트 스크래핑"""
    reports = []
    try:
        url = (f'https://finance.naver.com/research/company_list.naver'
               f'?searchType=itemCode&itemCode={ticker}')
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')

        rows = soup.select('table.type_1 tr')
        for row in rows:
            cells = row.select('td')
            if len(cells) < 5:
                continue
            texts = [c.get_text(strip=True) for c in cells]
            try:
                reports.append({
                    'date':        texts[0],
                    'firm':        texts[1],
                    'title':       texts[2],
                    'target':      texts[3],
                    'opinion':     texts[4] if len(texts) > 4 else '',
                })
            except:
                continue
            if len(reports) >= max_reports:
                break
    except:
        pass
    return reports


def get_sector(ticker: str, market: str = 'KOSPI') -> str:
    try:
        from pykrx import stock
        today = datetime.now().strftime('%Y%m%d')
        df = stock.get_market_sector_classifications(today, market)
        if ticker in df.index:
            return df.loc[ticker, '업종명']
    except:
        pass
    return '기타'


def fmt_market_cap(won: int) -> str:
    if won is None:
        return 'N/A'
    if won >= 1_000_000_000_000:
        return f"{won/1_000_000_000_000:.1f}조"
    elif won >= 100_000_000:
        return f"{won//100_000_000:,}억"
    return f"{won:,}원"


def build_stock_card(ticker: str, name: str, result: dict, pct_change: float, fdr_marcap: int = 0) -> str:
    """종목별 상세 카드 생성"""
    fund = get_pykrx_data(ticker)
    if not fund.get('market_cap') and fdr_marcap:
        fund['market_cap'] = fdr_marcap
    earnings = get_naver_earnings(ticker)
    reports = get_naver_analyst_reports(ticker, max_reports=3)

    # 신호 타입 결정
    signals = []
    sig_map = {
        '52w_high': '52주신고가', 'volume': '거래량폭발',
        'ma5_ride': '5일선라이딩', 'cup_handle': '컵위드핸들',
        'ma_convergence': '이평선수렴', 'rsi_macd': 'RSI/MACD',
    }
    for k, label in sig_map.items():
        if result.get(k, {}).get('signal'):
            signals.append(label)

    # 신고가 타입
    high_type = ''
    if result.get('52w_high', {}).get('signal'):
        dist = result['52w_high'].get('dist_pct', 0)
        high_type = '역사적신고가' if dist > 5 else '52주신고가'

    sign = '+' if pct_change >= 0 else ''
    lines = [
        f"{'─'*50}",
        f"✅ {name}({sign}{pct_change:.2f}%)",
        '',
    ]

    if signals:
        lines.append(f"❗ {' | '.join(signals)}")
    if high_type:
        lines.append(f"📌 {high_type}")

    lines += [
        '',
        f"시가총액 : {fmt_market_cap(fund.get('market_cap'))}",
        f"현재가   : {fund.get('price', 'N/A'):,}원" if fund.get('price') else "현재가   : N/A",
        f"({'네이버금융 기준'})",
        '',
        '* 주요지표',
        f"PER : {fund.get('per', 'N/A')}배  /  PBR : {fund.get('pbr', 'N/A')}배",
        f"ROE : {fund.get('roe', 'N/A')}%  /  EPS : {int(fund.get('eps', 0)):,}원" if fund.get('eps') else "ROE : N/A  /  EPS : N/A",
        '',
    ]

    if earnings:
        lines.append('* 최근 분기실적 (매출/영업익/순익, 억원)')
        for e in earnings:
            rev = f"{e['revenue']:,}" if e['revenue'] else 'N/A'
            op  = f"{e['op_income']:,}" if e['op_income'] else 'N/A'
            ni  = f"{e['net_income']:,}" if e['net_income'] else 'N/A'
            lines.append(f"{e['quarter']}  {rev} / {op} / {ni}")
        lines.append('')

    if reports:
        lines.append(f'* 증권사 보고서 (최근 {len(reports)}건)')
        for rp in reports:
            lines.append(f"{rp['date']} [{rp['firm']}]")
            lines.append(f"  {rp['opinion']} / 목표가: {rp['target']}")
            lines.append(f"  {rp['title']}")
        lines.append('')

    lines.append(f"📎 https://finance.naver.com/item/main.naver?code={ticker}")
    return '\n'.join(lines)
