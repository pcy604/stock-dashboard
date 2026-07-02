"""
한국투자증권(KIS) Open API 클라이언트 — 공식 국내주식 시세
─────────────────────────────────────────────────────────────────
키 파일(코드에 두지 않음):
  data/.kis_appkey     ← 앱키(App Key)
  data/.kis_appsecret  ← 앱시크릿(App Secret)
  data/.kis_env        ← (선택) 'real'(실전, 기본) 또는 'vts'(모의)
토큰은 data/.kis_token 에 캐싱(24h). appkey/secret이 있으면 만료 시 자동 재발급.

CLI:
  python kis_client.py token                 # 토큰 발급 테스트
  python kis_client.py price 005930          # 삼성전자 최근 일봉
"""
import json
import time
import requests
from pathlib import Path
from datetime import datetime, timedelta

DATA = Path('data')
_APPKEY_F = DATA / '.kis_appkey'
_SECRET_F = DATA / '.kis_appsecret'
_ENV_F = DATA / '.kis_env'
_TOKEN_F = DATA / '.kis_token'

_HOSTS = {'real': 'https://openapi.koreainvestment.com:9443',
          'vts':  'https://openapivts.koreainvestment.com:29443'}


def _read(p, default=None):
    try:
        return p.read_text(encoding='utf-8').strip()
    except Exception:
        return default


def _env():
    return (_read(_ENV_F) or 'real').lower()


def _host():
    return _HOSTS.get(_env(), _HOSTS['real'])


def _creds():
    ak, sk = _read(_APPKEY_F), _read(_SECRET_F)
    if not ak or not sk:
        raise RuntimeError("KIS 키 없음 → data/.kis_appkey 와 data/.kis_appsecret 파일에 넣어줘")
    return ak, sk


def issue_token():
    """새 접근토큰 발급(유효 24h). 캐시에 저장."""
    ak, sk = _creds()
    r = requests.post(f"{_host()}/oauth2/tokenP",
                      json={"grant_type": "client_credentials", "appkey": ak, "appsecret": sk},
                      timeout=10)
    r.raise_for_status()
    d = r.json()
    tok = d.get('access_token')
    if not tok:
        raise RuntimeError(f"토큰 발급 실패: {d}")
    exp = time.time() + int(d.get('expires_in', 86400)) - 600  # 10분 여유
    _TOKEN_F.write_text(json.dumps({'token': tok, 'exp': exp, 'env': _env()}), encoding='utf-8')
    return tok


def get_token():
    """캐시된 유효 토큰 반환. 없거나 만료면 재발급."""
    try:
        c = json.loads(_TOKEN_F.read_text(encoding='utf-8'))
        if c.get('env') == _env() and c.get('exp', 0) > time.time():
            return c['token']
    except Exception:
        pass
    return issue_token()


def _headers(tr_id):
    ak, sk = _creds()
    return {"content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {get_token()}",
            "appkey": ak, "appsecret": sk, "tr_id": tr_id, "custtype": "P"}


def daily_prices(code, start=None, end=None, adj=True, pause=0.08):
    """
    국내주식 기간별 일봉(수정주가). code: 6자리 종목코드.
    start/end: 'YYYYMMDD' (기본: 최근 ~2년). 100영업일 초과 구간은 자동 윈도우 반복.
    반환: [{date, open, high, low, close, volume}]  (오름차순)
    """
    end = end or datetime.now().strftime('%Y%m%d')
    start = start or (datetime.now() - timedelta(days=365 * 2)).strftime('%Y%m%d')
    url = f"{_host()}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    out, cur_end = {}, end
    for _ in range(40):  # 안전 상한 (윈도우 반복)
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
                  "FID_INPUT_DATE_1": start, "FID_INPUT_DATE_2": cur_end,
                  "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0" if adj else "1"}
        r = requests.get(url, headers=_headers("FHKST03010100"), params=params, timeout=10)
        r.raise_for_status()
        j = r.json()
        rows = j.get('output2') or []
        rows = [x for x in rows if x.get('stck_bsop_date')]
        if not rows:
            break
        for x in rows:
            d = x['stck_bsop_date']
            out[d] = {'date': f"{d[:4]}-{d[4:6]}-{d[6:]}",
                      'open': float(x['stck_oprc']), 'high': float(x['stck_hgpr']),
                      'low': float(x['stck_lwpr']), 'close': float(x['stck_clpr']),
                      'volume': int(x['acml_vol'])}
        earliest = min(x['stck_bsop_date'] for x in rows)
        if earliest <= start:
            break
        cur_end = (datetime.strptime(earliest, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d')
        time.sleep(pause)  # 레이트리밋 보호
    return [out[k] for k in sorted(out)]


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'token'
    if cmd == 'token':
        print("✅ 토큰:", get_token()[:24], "... (env=%s)" % _env())
    elif cmd == 'price':
        code = sys.argv[2] if len(sys.argv) > 2 else '005930'
        bars = daily_prices(code, start=(datetime.now() - timedelta(days=40)).strftime('%Y%m%d'))
        print(f"{code}: {len(bars)} bars")
        for b in bars[-5:]:
            print(" ", b)
