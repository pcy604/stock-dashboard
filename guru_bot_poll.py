"""텔레그램 인바운드 폴링 — /add <유튜브 채널 URL>로 분석 채널을 추가.

웹훅/상시서버 없이, GitHub Actions 크론에서 주기 실행(getUpdates).
추가된 채널은 data/guru_channels.json 에 적재 → 다음 요약부터 자동 포함
(guru_youtube.load_channels 가 이 파일을 읽음).
보안: ALLOWED chat_id(기본=소유자)만 명령 가능.

명령: /add <URL> · 채널 링크 직접 · /list · /help
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import re
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

import config
import guru_youtube as g

OFFSET_FILE   = Path('data/.bot_offset')
CHANNELS_FILE = Path('data/guru_channels.json')
API = f'https://api.telegram.org/bot{config.TELEGRAM_TOKEN}'

# 명령을 허용할 chat_id(문자열). 기본은 소유자 한 명. 친구 늘리면 여기에 추가.
ALLOWED = {str(config.TELEGRAM_CHAT_ID)}

URL_RE = re.compile(r'(https?://\S*youtu\S+|@[\w.\-]+|UC[\w\-]{20,})')


def _send(chat: str, text: str):
    try:
        requests.post(f'{API}/sendMessage',
                      json={'chat_id': chat, 'text': text, 'parse_mode': 'HTML',
                            'disable_web_page_preview': True}, timeout=10)
    except Exception as e:
        print(f'  [send 오류] {e}')


def load_offset() -> int:
    try:
        return int(OFFSET_FILE.read_text().strip())
    except Exception:
        return 0


def save_offset(o: int):
    OFFSET_FILE.parent.mkdir(parents=True, exist_ok=True)
    OFFSET_FILE.write_text(str(o))


def load_channels() -> list:
    if CHANNELS_FILE.exists():
        try:
            data = json.loads(CHANNELS_FILE.read_text(encoding='utf-8'))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return [dict(c) for c in getattr(config, 'GURU_CHANNELS', [])]


def save_channels(chans: list):
    CHANNELS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHANNELS_FILE.write_text(json.dumps(chans, ensure_ascii=False, indent=2), encoding='utf-8')


def channel_title(cid: str) -> str:
    try:
        r = requests.get(f'https://www.youtube.com/feeds/videos.xml?channel_id={cid}', timeout=15)
        root = ET.fromstring(r.content)
        t = root.find('{http://www.w3.org/2005/Atom}title')
        return (t.text or cid) if t is not None else cid
    except Exception:
        return cid


def handle(text: str, chat: str) -> bool:
    """명령 처리. 채널목록이 바뀌면 True."""
    text = (text or '').strip()
    low = text.lower()

    if low in ('/start', '/help'):
        _send(chat, '유튜브 채널을 요약 구독에 추가하려면:\n'
                    '<code>/add 채널URL</code>  또는  채널 링크를 그냥 보내세요.\n\n'
                    '명령: /list (현재 채널) · /help')
        return False

    if low == '/list':
        chans = load_channels()
        _send(chat, '<b>현재 분석 채널</b>\n' + '\n'.join(f"• {c['name']}" for c in chans))
        return False

    m = URL_RE.search(text)
    if not m:
        if low.startswith('/add'):
            _send(chat, '사용법: <code>/add &lt;유튜브 채널 URL&gt;</code>')
        return False

    cid = g.resolve_channel_id(m.group(1))
    if not cid:
        _send(chat, f'❌ 채널을 못 찾았어: {m.group(1)}\n영상 말고 <b>채널</b> URL인지 확인해줘.')
        return False

    chans = load_channels()
    if any(c.get('id') == cid for c in chans):
        _send(chat, 'ℹ️ 이미 등록된 채널이야.')
        return False

    name = channel_title(cid)
    chans.append({'name': name, 'id': cid})
    save_channels(chans)
    _send(chat, f'✅ 추가됨: <b>{name}</b>\n다음 요약부터 이 채널 영상도 포함돼.')
    print(f'  채널 추가: {name} ({cid})')
    return True


def main():
    if not config.TELEGRAM_TOKEN:
        print('TELEGRAM_TOKEN 없음 — 종료')
        return
    offset = load_offset()
    try:
        r = requests.get(f'{API}/getUpdates',
                         params={'offset': offset + 1, 'timeout': 0,
                                 'allowed_updates': json.dumps(['message'])}, timeout=30)
        updates = r.json().get('result', [])
    except Exception as e:
        print(f'getUpdates 오류: {e}')
        return

    if not updates:
        print('새 메시지 없음')
        return

    changed, last = False, offset
    for u in updates:
        last = max(last, u['update_id'])
        msg = u.get('message') or {}
        chat = str(msg.get('chat', {}).get('id', ''))
        text = msg.get('text', '')
        if not chat:
            continue
        if chat not in ALLOWED:
            _send(chat, '권한이 없어요. (베타 — 소유자 전용)')
            continue
        if handle(text, chat):
            changed = True

    save_offset(last)
    print(f'처리 {len(updates)}건 · 변경={changed} · offset={last}')


if __name__ == '__main__':
    main()
