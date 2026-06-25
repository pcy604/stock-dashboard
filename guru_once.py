"""단일 유튜브 영상 즉석 요약 — URL 하나 주면 분석해 내 텔레그램(개인 챗)으로 전송.

사용:
    python guru_once.py https://www.youtube.com/watch?v=XXXX
    python guru_once.py https://youtu.be/XXXX
    python guru_once.py XXXX            # 영상 ID 직접

라이브/자막없는 영상은 실패할 수 있음(방송 종료 후 자막 생기면 다시 시도).
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import re
from datetime import datetime

import requests

import config
import guru_youtube as g


def extract_video_id(url: str) -> str | None:
    url = url.strip()
    if re.fullmatch(r'[\w-]{11}', url):
        return url
    m = re.search(r'(?:v=|youtu\.be/|/live/|/shorts/|/embed/)([\w-]{11})', url)
    return m.group(1) if m else None


def fetch_title(vid: str) -> str:
    try:
        r = requests.get(
            f'https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json',
            timeout=10)
        return r.json().get('title', '') or '(제목 미상)'
    except Exception:
        return '(제목 미상)'


def main():
    if len(sys.argv) < 2:
        print('사용: python guru_once.py <유튜브 영상 URL 또는 ID>')
        return
    vid = extract_video_id(sys.argv[1])
    if not vid:
        print('영상 ID를 못 찾음. watch?v=… / youtu.be/… 형태 URL을 넣어줘.')
        return

    title = fetch_title(vid)
    video = {
        'video_id': vid,
        'title': title,
        'channel': '수동요청',
        'url': f'https://www.youtube.com/watch?v={vid}',
        'published': datetime.now(g.KST).isoformat(),
    }
    print(f'🎬 즉석 요약: {title}')

    client = g._gemini_client()
    analysis, source = g.analyze(client, video)
    video['analysis'] = analysis
    video['source'] = source

    if not g._has_content(analysis):
        print('요약 실패 — 자막 없음/영상분석 실패. 라이브면 방송 종료 후 자막 생기면 다시 시도해줘.')
        return

    date_str = datetime.now(g.KST).strftime('%Y-%m-%d')
    g._send_digest([video], date_str,
                   header='<b>🎬 즉석 요약 (수동 요청)</b>',
                   chat=config.TELEGRAM_CHAT_ID)   # 개인 챗으로
    print('완료')


if __name__ == '__main__':
    main()
