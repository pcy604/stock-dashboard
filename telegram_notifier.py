"""
텔레그램 알림 모듈
"""
import requests


def send_message(token: str, chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(url, json={
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML',
        }, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"  [텔레그램 오류] {e}")
        return False


def send_photo(token: str, chat_id: str, photo_path: str, caption: str = '') -> bool:
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        with open(photo_path, 'rb') as f:
            r = requests.post(url, data={'chat_id': chat_id, 'caption': caption[:1024]},
                              files={'photo': f}, timeout=30)
        return r.status_code == 200
    except Exception as e:
        print(f"  [텔레그램 사진 오류] {e}")
        return False


def build_message(hits: list, date_str: str) -> str:
    """hits: list of (market, symbol, name, result, earnings, tf_label)"""
    lines = [f"<b>📊 주식 스크리너 | {date_str}</b>"]
    lines.append(f"신호 종목 {len(hits)}개\n")

    for market, sym, name, result, earnings, tf_labels in hits:
        stars = '★' * result['total_signals']
        label = f"[{market}] {sym}" + (f" ({name})" if name != sym else '')
        lines.append(f"<b>{stars} {label}</b>")

        # 타임프레임
        if tf_labels:
            lines.append(f"  타임프레임: {' | '.join(tf_labels)}")

        # 활성 신호
        sig_map = {
            '52w_high': '52주신고가', 'ma5_ride': '5일선라이딩',
            'cup_handle': '컵위드핸들', 'ma_convergence': '이평선수렴',
            'rsi_macd': 'RSI/MACD', 'volume': '거래량폭발',
        }
        active = [sig_map[k] for k, v in result.items()
                  if isinstance(v, dict) and v.get('signal')]
        lines.append(f"  신호: {' | '.join(active)}")

        # 실적
        if earnings:
            from earnings import fmt_earnings
            e_str = fmt_earnings(earnings)
            if e_str:
                lines.append(f"  {e_str}")

        lines.append('')

    return '\n'.join(lines)


def test_connection(token: str, chat_id: str) -> bool:
    """봇 연결 테스트"""
    return send_message(token, chat_id, "✅ 스크리너 봇 연결 성공!")
