"""CANSLIM 스크리너 — 윌리엄 오닐 방식 (한국주식)

[정량 기준]
M  시장방향  : KOSPI 주봉 MA10 > MA30  (상승추세)
C  분기실적  : 최근 분기 순이익 전년 동기 대비 ≥ +20%  (네이버금융)
A  연간실적  : 연간 EPS 전년 대비 ≥ +20% × 2개년 연속  (pykrx)
N  신고가    : 52주 신고가 -5% 이내
S  거래량    : 60일 평균 대비 ≥ 1.5배 + 양봉 + 몸통 40%+
L  상대강도  : 12개월 수익률 전체 상위 30% (RS ≥ 70)
I  기관수급  : 기관+외국인 최근 20거래일 합산 순매수 > 0  (pykrx)

[최소 통과 기준]
  M✅ + N✅ + S✅ + L✅  →  필수 4항목
  C, A, I  →  가산점 (보유 수 표시)
  최종 점수 = 4~7점
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time, threading
from concurrent.futures import ThreadPoolExecutor
import FinanceDataReader as fdr
import config
from report import save_report
from telegram_notifier import send_message
from fundamentals_kr import get_naver_earnings

DATE_STR = datetime.now().strftime('%Y-%m-%d')

# ── 정량 기준 ────────────────────────────────────────────────────────
C_MIN_GROWTH  = 20.0   # 분기 순이익 YoY 성장 최소 (%)
A_MIN_GROWTH  = 20.0   # 연간 EPS YoY 성장 최소 (%)
N_THRESHOLD   = -5.0   # 52주 신고가 허용 거리 (%)
S_VOL_MIN     = 1.5    # 거래량 배수
S_BODY_MIN    = 0.4    # 캔들 몸통 비율
L_RS_MIN      = 70     # RS 퍼센타일 하한 (상위 30%)
I_DAYS        = 20     # 기관 순매수 조회 거래일 수
MIN_MARCAP    = 300_000_000_000   # 시총 3000억+

_print_lock = threading.Lock()


# ── M: 시장방향 ──────────────────────────────────────────────────────

def check_market(verbose=True):
    """KOSPI 주봉 MA10 > MA30 → 상승추세"""
    try:
        start = (datetime.now() - timedelta(days=500)).strftime('%Y-%m-%d')
        df = fdr.DataReader('KS11', start)
        df.index = pd.to_datetime(df.index).tz_localize(None)
        wdf = df['Close'].resample('W').last().dropna()
        if len(wdf) < 30:
            return True, 'N/A'
        ma10 = wdf.iloc[-10:].mean()
        ma30 = wdf.iloc[-30:].mean()
        ok = ma10 > ma30
        direction = '상승추세 ✅' if ok else '하락추세 ⚠️'
        if verbose:
            print(f"  [M] KOSPI: MA10={ma10:,.0f} / MA30={ma30:,.0f} → {direction}")
        return ok, direction
    except Exception as e:
        print(f"  [M] KOSPI 조회 실패: {e}")
        return True, 'N/A'


# ── 유니버스 ─────────────────────────────────────────────────────────

def get_universe():
    print("  유니버스 로딩...", end=' ', flush=True)
    try:
        krx = fdr.StockListing('KRX')
        f = krx[krx['Marcap'] >= MIN_MARCAP].sort_values('Marcap', ascending=False)
        pairs = list(zip(
            f['Code'].astype(str).str.zfill(6),
            f['Name'].astype(str),
            f['Marcap'].astype(int),
        ))
        print(f"{len(pairs)}개 (3,000억+)")
        return pairs
    except Exception as e:
        print(f"실패: {e}")
        return []


# ── 가격 데이터 + N/S/RS 계산 ────────────────────────────────────────

def fetch_price(sym):
    try:
        start = (datetime.now() - timedelta(days=550)).strftime('%Y-%m-%d')
        df = fdr.DataReader(sym, start)
        if df.empty or len(df) < 200:
            return None
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna(subset=['Close'])
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df
    except:
        return None


def check_n(df):
    """N: 52주 신고가 -5% 이내"""
    if len(df) < 200:
        return False, {}
    high_52w = df['High'].iloc[-252:-1].max() if len(df) >= 252 else df['High'].iloc[:-1].max()
    curr = df['Close'].iloc[-1]
    dist = (curr / high_52w - 1) * 100
    return dist >= N_THRESHOLD, {'dist_pct': round(dist, 1), '52w_high': round(high_52w, 0)}


def check_s(df):
    """S: 거래량 1.5배+ + 양봉 + 몸통 40%+"""
    if len(df) < 60:
        return False, {}
    avg_vol = df['Volume'].iloc[-61:-1].mean()
    if avg_vol == 0:
        return False, {}
    today = df.iloc[-1]
    vol_ratio = today['Volume'] / avg_vol
    rng = today['High'] - today['Low']
    if rng == 0:
        return False, {}
    body = abs(today['Close'] - today['Open'])
    body_ratio = body / rng
    is_bull = today['Close'] > today['Open']
    ok = vol_ratio >= S_VOL_MIN and body_ratio >= S_BODY_MIN and is_bull
    return ok, {'vol_ratio': round(vol_ratio, 1), 'body_pct': round(body_ratio * 100, 1), 'is_bull': is_bull}


def calc_rs_return(df):
    """12개월 수익률 계산 (RS 랭킹용)"""
    try:
        if len(df) < 240:
            return None
        curr = df['Close'].iloc[-1]
        year_ago = df['Close'].iloc[-252] if len(df) >= 252 else df['Close'].iloc[0]
        return (curr / year_ago - 1) * 100
    except:
        return None


def process_price(item):
    """가격 다운로드 + N/S/RS 계산 — 병렬 실행"""
    sym, name, marcap = item
    time.sleep(0.05)
    df = fetch_price(sym)
    if df is None:
        return None
    n_ok, n_detail = check_n(df)
    s_ok, s_detail = check_s(df)
    rs_ret = calc_rs_return(df)
    return {
        'sym': sym, 'name': name, 'marcap': marcap,
        'df': df,
        'n_ok': n_ok, 'n_detail': n_detail,
        's_ok': s_ok, 's_detail': s_detail,
        'rs_ret': rs_ret,
    }


# ── C: 분기실적 (네이버금융) ─────────────────────────────────────────

def fetch_naver_earnings_table(sym):
    """네이버 종목 메인 '기업실적분석' 테이블 파싱
    반환: {'annual': [(label, ni), ...], 'quarterly': [(label, ni), ...]}
    (E) 추정치 컬럼은 제외, ni는 억원 (음수 보존)
    """
    import requests
    from bs4 import BeautifulSoup
    headers = {'User-Agent': 'Mozilla/5.0'}
    r = requests.get(f'https://finance.naver.com/item/main.naver?code={sym}',
                     headers=headers, timeout=8)
    soup = BeautifulSoup(r.text, 'html.parser')
    tb = soup.select_one('div.cop_analysis table')
    if tb is None:
        return None

    heads = [th.get_text(' ', strip=True) for th in tb.select('thead th')]
    # 날짜 형식(yyyy.mm) 헤더만 추출 — 앞쪽 메타 헤더 제외
    import re
    date_heads = [h for h in heads if re.match(r'\d{4}\.\d{2}', h)]
    if len(date_heads) < 4:
        return None
    # 통상 연간 4개 + 분기 6개
    n_annual = 4 if len(date_heads) >= 10 else len(date_heads) - 6

    ni_vals = None
    for row in tb.select('tbody tr'):
        th = row.select_one('th')
        if th and '당기순이익' in th.get_text():
            ni_vals = [td.get_text(strip=True) for td in row.select('td')]
            break
    if ni_vals is None:
        return None

    def parse_num(s):
        s = s.replace(',', '').strip()
        if not s or s == '-':
            return None
        try:
            return float(s)
        except:
            return None

    pairs = list(zip(date_heads, [parse_num(v) for v in ni_vals]))
    annual    = [(l, v) for l, v in pairs[:n_annual] if '(E)' not in l and v is not None]
    quarterly = [(l, v) for l, v in pairs[n_annual:] if '(E)' not in l and v is not None]
    return {'annual': annual, 'quarterly': quarterly}


_naver_cache = {}

def _get_naver_table(sym):
    if sym not in _naver_cache:
        try:
            _naver_cache[sym] = fetch_naver_earnings_table(sym)
        except:
            _naver_cache[sym] = None
    return _naver_cache[sym]


def check_c(sym):
    """C: 최근 분기 순이익 전년 동기 대비 성장률"""
    try:
        data = _get_naver_table(sym)
        if not data or len(data['quarterly']) < 5:
            return None, {}
        q = data['quarterly']
        q_label, latest = q[-1]          # 최근 확정 분기
        # 전년 동기 = 같은 월 분기 찾기
        target_month = q_label.split('.')[1]
        target_year  = int(q_label.split('.')[0]) - 1
        year_ago = next((v for l, v in q if l == f"{target_year}.{target_month}"), None)
        if latest is None or year_ago is None or year_ago == 0:
            return None, {}
        if year_ago < 0:
            ok = latest > 0
            return ok, {'growth': '흑자전환' if ok else None, 'quarter': q_label}
        growth = (latest - year_ago) / abs(year_ago) * 100
        ok = growth >= C_MIN_GROWTH
        return ok, {'growth': round(growth, 1), 'quarter': q_label}
    except:
        return None, {}


# ── A: 연간 순이익 성장 (네이버금융 스크래핑) ────────────────────────

def check_a_yf(sym):
    """A: 연간 순이익 YoY 성장률 — 네이버 기업실적분석 테이블
    반환: (growth_y1, growth_y2) — 최근년/전년, None=데이터없음
    """
    try:
        data = _get_naver_table(sym)
        if not data or len(data['annual']) < 2:
            return None, None
        a = data['annual']  # 오래된 → 최신 순
        vals = [v for _, v in a]
        g1 = g2 = None
        if len(vals) >= 2 and vals[-2] and vals[-2] != 0:
            g1 = round((vals[-1] / abs(vals[-2]) - 1) * 100, 1) if vals[-2] > 0 else None
        if len(vals) >= 3 and vals[-3] and vals[-3] != 0:
            g2 = round((vals[-2] / abs(vals[-3]) - 1) * 100, 1) if vals[-3] > 0 else None
        return g1, g2
    except:
        return None, None


# ── I: 기관+외국인 순매수 (pykrx, 최근 20거래일 합산, 억원) ───────────

def check_i(sym):
    """I: 최근 20거래일 기관+외국인 합산 순매수 (억원). 양수=매집.
    pykrx get_market_trading_value_by_date 사용. 실패 시 None.
    """
    try:
        from pykrx import stock
        today = datetime.now().strftime('%Y%m%d')
        frm = (datetime.now() - timedelta(days=40)).strftime('%Y%m%d')
        df = stock.get_market_trading_value_by_date(frm, today, sym)
        if df is None or len(df) == 0:
            return None
        df = df.tail(I_DAYS)
        def _pick(*names):
            for n in names:
                if n in df.columns:
                    return n
            return None
        inst_c = _pick('기관합계', '기관')
        forn_c = _pick('외국인', '외국인합계')
        if inst_c is None and forn_c is None:
            return None
        net = 0.0
        if inst_c is not None:
            net += float(df[inst_c].sum())
        if forn_c is not None:
            net += float(df[forn_c].sum())
        return round(net / 1e8, 1)   # 억원
    except Exception:
        return None


# ── 메인 스캔 ────────────────────────────────────────────────────────

def scan(pairs):
    total = len(pairs)
    counter = [0]
    tech_results = []

    # Step 1: 가격 데이터 + N/S/RS 병렬 계산
    print(f"[Step 1] 가격 데이터 + N/S/RS 계산 ({total}개 병렬)")

    def _run(item):
        res = process_price(item)
        with _print_lock:
            counter[0] += 1
            if counter[0] % 100 == 0 or counter[0] == total:
                print(f"\r  {counter[0]}/{total} 완료...", end='', flush=True)
        return res

    with ThreadPoolExecutor(max_workers=8) as ex:
        for r in ex.map(_run, pairs):
            if r is not None:
                tech_results.append(r)
    print()

    # Step 2: RS 랭킹 계산 (전체 기준)
    print("[Step 2] RS 랭킹 계산")
    rs_vals = [(r['sym'], r['rs_ret']) for r in tech_results if r['rs_ret'] is not None]
    if rs_vals:
        rs_df = pd.DataFrame(rs_vals, columns=['sym', 'ret'])
        rs_df['pct'] = rs_df['ret'].rank(pct=True) * 100
        rs_map = dict(zip(rs_df['sym'], rs_df['pct'].round(1)))
    else:
        rs_map = {}

    # Step 3: 느슨한 사전 필터 (N -20% 이내, RS 상위 60%)
    # 대시보드에서 사용자가 슬라이더로 정밀 조정
    print("[Step 3] 사전 필터 (N -20% 이내, RS 상위 60%)")
    candidates = []
    for r in tech_results:
        sym = r['sym']
        rs_pct = rs_map.get(sym, 0)
        n_dist = r['n_detail'].get('dist_pct', -999)
        if n_dist >= -20 and rs_pct >= 40:
            r['rs_pct'] = rs_pct
            candidates.append(r)

    print(f"  → 사전 필터 통과: {len(candidates)}개\n")

    # Step 4: C / A / I raw 데이터 수집 (통과 종목만)
    hits = []
    for i, r in enumerate(candidates):
        sym  = r['sym']
        name = r['name']
        print(f"  [{i+1}/{len(candidates)}] {name}({sym}) ...", end=' ', flush=True)

        c_ok, c_det = check_c(sym)
        a_y1, a_y2  = check_a_yf(sym)
        i_inst      = check_i(sym)

        c_str = f"C:{c_det.get('growth')}%" if c_det and c_det.get('growth') is not None else "C:?"
        a_str = f"A:{a_y1}/{a_y2}%"
        i_str = f"I:{i_inst:+.0f}억" if i_inst is not None else "I:?"
        print(f"{c_str} {a_str} {i_str}")

        hits.append({
            'sym':         sym,
            'name':        name,
            'marcap':      r['marcap'],
            'rs_pct':      r['rs_pct'],
            'n_dist_pct':  r['n_detail'].get('dist_pct'),
            's_vol_ratio': r['s_detail'].get('vol_ratio'),
            's_body_pct':  r['s_detail'].get('body_pct'),
            's_bull':      r['s_detail'].get('is_bull', False),
            'c_growth_pct': c_det.get('growth') if c_det else None,
            'c_quarter':   c_det.get('quarter', '') if c_det else '',
            'a_growth_y1': a_y1,
            'a_growth_y2': a_y2,
            'i_inst_pct':  i_inst,
        })

    return hits


# ── 리포트 ───────────────────────────────────────────────────────────

def build_report(hits, m_ok, m_dir):
    m_str = '✅ 상승추세' if m_ok else '⚠️ 하락추세 (신규매수 주의)'
    lines = [
        f"📌 CANSLIM 스크리너 ({DATE_STR} 기준)",
        f"후보 {len(hits)}개 종목  |  유니버스: KRX 3,000억+ (N -20%, RS 40p 이상)",
        f"",
        f"[M] 시장방향: {m_str}  ({m_dir})",
        f"",
    ]

    if not hits:
        lines.append("  조건을 충족하는 종목이 없습니다.")
    else:
        lines += ["─" * 60, f"{'시총':>8}  RS    N거리    S배수  C분기%  A연간%  I순매수  종목명", "─" * 60]
        for h in sorted(hits, key=lambda x: -(x.get('rs_pct') or 0)):
            cap = h['marcap'] // 100_000_000
            cap_str = f"{cap/10000:.1f}조" if cap >= 10000 else f"{cap:,}억"
            c_s = f"{h['c_growth_pct']:+.0f}%" if h.get('c_growth_pct') is not None else "?"
            a_s = (f"{h['a_growth_y1']:+.0f}%/{h['a_growth_y2']:+.0f}%"
                   if h.get('a_growth_y1') is not None and h.get('a_growth_y2') is not None else "?")
            i_s = f"{h['i_inst_pct']:+.0f}억" if h.get('i_inst_pct') is not None else "?"
            lines.append(
                f"{cap_str:>8}  {h.get('rs_pct',0):>4.0f}p  "
                f"{h.get('n_dist_pct',0):+5.1f}%  "
                f"{h.get('s_vol_ratio',0):>4.1f}x  "
                f"{c_s:>7}  {a_s:>12}  {i_s:>6}  {h['name']}"
            )

    lines += [
        "", "─" * 60,
        "📊 데이터 출처",
        "  N/S/L : FDR 가격 데이터",
        "  C     : 네이버금융 분기실적 스크래핑",
        "  A     : 네이버금융 연간실적 스크래핑",
        "  I     : pykrx 기관+외국인 20거래일 순매수 (억원)",
        "  ※ 대시보드에서 슬라이더로 기준 실시간 조정 가능",
    ]
    return '\n'.join(lines)


# ── 메인 ─────────────────────────────────────────────────────────────

def main():
    print(f"\n{'═'*55}")
    print(f"  📊 CANSLIM 스크리너 (KR)  |  {DATE_STR}")
    print(f"{'═'*55}\n")

    m_ok, m_dir = check_market()
    if not m_ok:
        print("  ⚠️  KOSPI 하락추세 — CANSLIM은 상승장 전략입니다.")
        print("      결과는 출력하지만 신규 매수 주의.\n")

    pairs = get_universe()
    if not pairs:
        print("유니버스 로딩 실패")
        return

    hits = []
    try:
        hits = scan(pairs)
    except Exception as e:
        print(f"\n  ⚠️ 스캔 중 오류: {e} — 현재까지 결과로 저장")

    print(f"\n  → 최종 신호: {len(hits)}개\n")

    # 대시보드용 JSON 저장 (오류 발생해도 항상 저장)
    import json, os
    os.makedirs('results', exist_ok=True)
    json_path = 'results/canslim_latest.json'

    def _safe(v, default=None):
        try: return v
        except: return default

    payload = {
        'date': DATE_STR,
        'market_ok': bool(m_ok),
        'market_dir': m_dir,
        'stocks': [],
    }
    for h in hits:
        try:
            payload['stocks'].append({
                'sym':          h['sym'],
                'name':         h['name'],
                'marcap':       h['marcap'],
                'rs_pct':       h.get('rs_pct', 0),
                'n_dist_pct':   h.get('n_dist_pct'),
                's_vol_ratio':  h.get('s_vol_ratio'),
                's_body_pct':   h.get('s_body_pct'),
                's_bull':       h.get('s_bull', False),
                'c_growth_pct': h.get('c_growth_pct'),
                'c_quarter':    h.get('c_quarter', ''),
                'a_growth_y1':  h.get('a_growth_y1'),
                'a_growth_y2':  h.get('a_growth_y2'),
                'i_inst_pct':   h.get('i_inst_pct'),
            })
        except Exception as e:
            print(f"  [직렬화 오류] {h.get('sym','?')}: {e}")

    # numpy 타입(np.bool_/np.int64/np.float64)은 기본 json이 직렬화 못 하므로 변환기 지정
    def _jdefault(o):
        if isinstance(o, np.bool_):    return bool(o)
        if isinstance(o, np.integer):  return int(o)
        if isinstance(o, np.floating): return float(o)
        return str(o)
    # 원자적 저장: 임시파일에 쓴 뒤 교체 → 중간에 끊겨도 기존 파일 손상 없음
    tmp_path = json_path + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=_jdefault)
    os.replace(tmp_path, json_path)
    print(f"JSON 저장: {json_path}")

    report = build_report(hits, m_ok, m_dir)
    fname  = save_report(report, 'canslim')
    print(f"리포트 저장: {fname}")
    print('\n' + report)

    if config.TELEGRAM_ENABLED and hits:
        for chunk in [report[i:i + 4000] for i in range(0, len(report), 4000)]:
            send_message(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, chunk)
        print('✅ 텔레그램 전송 완료')


if __name__ == '__main__':
    main()
