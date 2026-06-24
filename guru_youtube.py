"""구루 유튜브 일일 요약 — 투자 유튜브 채널 영상에서 핵심 인사이트·언급 종목 추출

흐름:  RSS로 신규 영상 감지 → 자막(타임스탬프 포함) 추출 → Gemini 분석
       (자막 실패 시 영상 URL 직접 분석으로 폴백)
       → results/guru_insights.json 저장 → 텔레그램 다이제스트(딥링크 포함) 전송

특징:
  - 각 종목·핵심 포인트가 영상의 몇 분 몇 초에 나왔는지 t(초)로 추출 → &t=초s 딥링크
  - Gemini가 영상의 투자관련성(relevant)을 판단 → 잡담·홍보·비투자 영상은 다이제스트에서 제외
  - 채널별 제목 필터(include/exclude) 지원

실행:  python guru_youtube.py     (매일 GitHub Actions에서 자동 실행)
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import re
import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone, timedelta

import requests

import config
from telegram_notifier import send_message

# ── 설정 ────────────────────────────────────────────────────────────
KST              = timezone(timedelta(hours=9))
RESULT_PATH      = Path('results/guru_insights.json')
LOOKBACK_HOURS   = 6           # 최근 N시간 내 영상만 (2시간 주기 + 누락슬롯 여유). 중복은 video_id로 차단
MAX_PER_CHANNEL  = 5           # 채널당 1회 최대 분석 영상 수
MAX_HISTORY      = 200         # JSON에 보관할 분석 기록 최대 개수
GEMINI_MODEL     = 'gemini-2.5-flash'
TRANSCRIPT_LANGS = ['ko', 'en']
OUTPUT_LANG      = getattr(config, 'GURU_OUTPUT_LANG', '한국어')   # 요약 출력 언어
TRANSCRIPT_LIMIT = 120_000     # Gemini에 넣을 자막 최대 글자 수 (토큰 안전)
STAMP_INTERVAL   = 20          # 자막에 [mm:ss] 마커를 넣는 간격(초)
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36'

# 전역 기본 제목 필터(채널별 설정이 없을 때 사용)
TITLE_INCLUDE = []                                   # 비우면 전체 허용
TITLE_EXCLUDE = ['쇼츠', 'shorts', '예고', '다시보기']


# ── 채널 ID 해석 ─────────────────────────────────────────────────────
def resolve_channel_id(ref: str) -> str | None:
    """채널 URL / @handle / UC… 무엇이든 받아 channel_id(UC…) 반환. EU consent 우회.
    지원: youtube.com/channel/UC…, youtube.com/@handle, youtube.com/c/Name,
          youtube.com/user/Name, @handle, UC… 직접.
    """
    s = ref.strip()
    # 1) /channel/UC… 또는 순수 UC id 는 페이지 접근 없이 바로
    m = re.search(r'(UC[\w-]{20,})', s)
    if m and (s.startswith('UC') or '/channel/' in s):
        return m.group(1)
    # 2) 접근할 채널 페이지 URL 결정
    if s.startswith('http'):
        url = s.split('?')[0]
    else:
        url = f'https://www.youtube.com/@{s.lstrip("@")}'
    try:
        r = requests.get(
            url,
            headers={'User-Agent': UA, 'Accept-Language': 'en-US,en'},
            cookies={'CONSENT': 'YES+1', 'SOCS': 'CAISNQgDEitib3FfaWRlbnRpdHlmcm9udGVuZF8yMDI0MDgwNi4wMV9wMRgBGgJlbiAEGgYIgZ7etgY'},
            timeout=15,
        )
        m = re.search(r'"(?:channelId|externalId)":"(UC[\w-]{20,})"', r.text)
        if m:
            return m.group(1)
        m = re.search(r'/channel/(UC[\w-]{20,})', r.text)
        if m:
            return m.group(1)
    except Exception as e:
        print(f'  [채널해석 실패] {ref}: {e}')
    return None


CHANNELS_FILE = Path('data/guru_channels.json')


def load_channels() -> list:
    """data/guru_channels.json 이 있으면 그걸, 없으면 config.GURU_CHANNELS 사용.
    (대시보드에서 URL로 추가한 채널이 이 파일에 쌓임)"""
    if CHANNELS_FILE.exists():
        try:
            data = json.loads(CHANNELS_FILE.read_text(encoding='utf-8'))
            if isinstance(data, list) and data:
                return data
        except Exception as e:
            print(f'  [채널파일 로드 실패] {e}')
    return getattr(config, 'GURU_CHANNELS', [])


# ── RSS로 최근 영상 목록 ─────────────────────────────────────────────
def fetch_recent_videos(channel_id: str, channel_name: str,
                        include=None, exclude=None) -> list:
    include = TITLE_INCLUDE if include is None else include
    exclude = TITLE_EXCLUDE if exclude is None else exclude
    url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'
    ns = {'a': 'http://www.w3.org/2005/Atom',
          'yt': 'http://www.youtube.com/xml/schemas/2015'}
    out = []
    try:
        r = requests.get(url, headers={'User-Agent': UA}, timeout=15)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        print(f'  [RSS 실패] {channel_name}: {e}')
        return out

    now = datetime.now(timezone.utc)
    for entry in root.findall('a:entry', ns):
        try:
            vid = entry.find('yt:videoId', ns).text
            title = entry.find('a:title', ns).text or ''
            published = entry.find('a:published', ns).text
            pub_dt = datetime.fromisoformat(published)
        except Exception:
            continue
        if (now - pub_dt).total_seconds() > LOOKBACK_HOURS * 3600:
            continue
        tl = title.lower()
        if include and not any(k.lower() in tl for k in include):
            continue
        if any(k.lower() in tl for k in exclude):
            continue
        out.append({
            'video_id': vid,
            'title': title,
            'channel': channel_name,
            'published': published,
            'url': f'https://www.youtube.com/watch?v={vid}',
        })
    return out


# ── 자막 추출 (타임스탬프 포함) ──────────────────────────────────────
def get_transcript_segments(video_id: str) -> list | None:
    """[(start_sec, text), ...] 반환. 실패 시 None."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except Exception as e:
        print(f'    [자막 모듈 없음] {e}')
        return None
    try:
        # 0.x: 정적 메서드 / 1.x: 인스턴스 메서드 둘 다 대응
        try:
            raw = YouTubeTranscriptApi.get_transcript(video_id, languages=TRANSCRIPT_LANGS)
            segs = [(float(s.get('start', 0)), s.get('text', '')) for s in raw]
        except AttributeError:
            fetched = YouTubeTranscriptApi().fetch(video_id, languages=TRANSCRIPT_LANGS)
            segs = [(float(getattr(s, 'start', 0)), getattr(s, 'text', '')) for s in fetched]
        segs = [(t, x) for t, x in segs if x]
        return segs or None
    except Exception as e:
        print(f'    [자막 실패] {video_id}: {type(e).__name__}')
        return None


def fmt_ts(sec) -> str:
    sec = int(sec or 0)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def stamp_link(url: str, sec) -> str:
    return f"{url}&t={int(sec or 0)}s"


def build_stamped_transcript(segs: list, limit: int = TRANSCRIPT_LIMIT) -> str:
    """STAMP_INTERVAL초 간격으로 [mm:ss] 마커를 삽입한 자막 텍스트."""
    out, next_mark = [], 0
    for start, text in segs:
        if start >= next_mark:
            out.append(f"[{fmt_ts(start)}]")
            next_mark = start + STAMP_INTERVAL
        out.append(text)
    return ' '.join(out)[:limit]


# ── Gemini 분석 ──────────────────────────────────────────────────────
PROMPT = """당신은 주식·투자 전문 애널리스트입니다. 아래는 '{channel}' 채널의 영상 「{title}」 내용입니다.
투자자가 빠르게 흡수해야 할 핵심을 정리하세요.
영상의 원래 언어와 무관하게, summary·context·key_points·actionable 등 모든 출력 텍스트는 반드시 {lang}로 작성하세요. (종목명은 원래 표기 유지, ticker는 심볼/코드)
자막에는 [mm:ss] 또는 [h:mm:ss] 형태의 타임스탬프 마커가 섞여 있습니다. 각 항목이 언급되기 시작하는 시점을 초(정수)로 추정해 함께 적으세요.

반드시 아래 JSON 스키마로만 출력하세요. 코드블록·설명·머리말 없이 순수 JSON만:
{{
  "relevant": true,
  "one_liner": "영상 핵심을 한 문장으로",
  "summary": ["핵심 요약 3~6개 불릿"],
  "tickers": [{{"name": "종목명", "ticker": "티커(미국=심볼, 한국=6자리코드, 모르면 빈 문자열)", "context": "언급 맥락 한 줄", "view": "긍정|중립|부정", "t": 정수초}}],
  "key_points": [{{"point": "강조된 시장관·이슈·전망", "t": 정수초}}],
  "actionable": ["투자자가 체크할 액션 0~3개"]
}}

규칙:
- relevant: 구체적 종목·섹터·시장전망·거시지표·자산배분을 실질적으로 다루면 true. 역사·인문·철학·교양·심리 강의나 일반 사회담론은 시장과 억지로 엮여 있어도 false. 판단 기준: "투자 의사결정에 바로 쓸 내용이 있는가". tickers가 비어 있고 actionable이 없으면 대체로 false.
- 언급된 종목이 없으면 tickers는 빈 배열 [].
- 추측하지 말고 영상 내용에 근거할 것. view는 화자가 해당 종목을 보는 톤.
- t는 해당 내용이 시작되는 가장 가까운 [타임스탬프]의 초 값(정수). 모르면 0.

[영상 내용]
{body}
"""

_EMPTY = {'relevant': True, 'one_liner': '', 'summary': [], 'tickers': [],
          'key_points': [], 'actionable': []}


def _gemini_client():
    from google import genai
    key = getattr(config, 'GEMINI_KEY', '') or ''
    if not key:
        raise RuntimeError('GEMINI_KEY 미설정 (data/.gemini_key 또는 환경변수 GEMINI_KEY)')
    return genai.Client(api_key=key)


def _parse_json(text: str) -> dict:
    t = (text or '').strip()
    t = re.sub(r'^```(?:json)?\s*|\s*```$', '', t, flags=re.IGNORECASE).strip()
    candidates = [t]
    m = re.search(r'\{.*\}', t, flags=re.DOTALL)
    if m:
        candidates.append(m.group(0))
    for c in candidates:
        try:
            return {**_EMPTY, **json.loads(c)}
        except Exception:
            continue
    return {**_EMPTY, '_parse_error': True, '_raw': t[:500]}


_TRANSIENT = ('503', 'UNAVAILABLE', 'overloaded', 'high demand',
              '429', 'RESOURCE_EXHAUSTED', 'deadline', 'timeout')


def _generate(client, contents, retries: int = 4):
    """일시적 과부하(503/429 등)는 백오프 재시도 후에만 실패로 처리."""
    last = None
    for i in range(retries):
        try:
            return client.models.generate_content(model=GEMINI_MODEL, contents=contents)
        except Exception as e:
            last = e
            transient = any(k.lower() in str(e).lower() for k in _TRANSIENT)
            if not transient or i == retries - 1:
                raise
            wait = 5 * (i + 1)
            print(f'    [Gemini 일시오류 재시도 {i+1}/{retries}] {type(e).__name__} → {wait}s 대기')
            time.sleep(wait)
    raise last


def analyze(client, video: dict) -> tuple[dict, str]:
    """(analysis_dict, source) 반환. source: 'transcript' | 'video' | 'fail'"""
    segs = get_transcript_segments(video['video_id'])
    if segs:
        body = build_stamped_transcript(segs)
        prompt = PROMPT.format(channel=video['channel'], title=video['title'], body=body, lang=OUTPUT_LANG)
        try:
            resp = _generate(client, prompt)
            return _parse_json(resp.text), 'transcript'
        except Exception as e:
            print(f'    [Gemini 텍스트 실패→영상폴백] {e}')

    # 폴백: 영상 URL 직접 분석 (자막 없음 / 자막 IP 차단 대응)
    try:
        from google.genai import types
        body = '(자막 없음 — 영상의 음성을 직접 분석하고, 각 항목이 나오는 영상 내 시점을 초 단위로 추정해 t에 넣으세요)'
        prompt = PROMPT.format(channel=video['channel'], title=video['title'], body=body, lang=OUTPUT_LANG)
        resp = _generate(client, types.Content(parts=[
            types.Part(file_data=types.FileData(file_uri=video['url'])),
            types.Part(text=prompt),
        ]))
        return _parse_json(resp.text), 'video'
    except Exception as e:
        print(f'    [Gemini 영상 분석 실패] {e}')
        return {**_EMPTY, '_error': str(e)[:200]}, 'fail'


# ── 저장 / 텔레그램 ──────────────────────────────────────────────────
def load_history() -> dict:
    if RESULT_PATH.exists():
        try:
            return json.loads(RESULT_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {'items': []}


def save_history(data: dict):
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    data['updated'] = datetime.now(KST).isoformat()
    data['items'] = data['items'][:MAX_HISTORY]
    RESULT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _esc(s: str) -> str:
    return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _kp_text(kp) -> str:
    return kp.get('point', '') if isinstance(kp, dict) else str(kp)


def build_telegram(new_items: list, date_str: str, header: str | None = None) -> str:
    shown = [it for it in new_items if it.get('analysis', {}).get('relevant', True)]
    if header:
        head = header
    else:
        skipped = len(new_items) - len(shown)
        head = f'<b>🎙️ 구루 인사이트 | {date_str}</b>\n투자 관련 영상 {len(shown)}개'
        if skipped:
            head += f' (비투자 {skipped}개 제외)'
    lines = [head, '']
    for it in shown:
        a = it.get('analysis', {})
        url = it['url']
        lines.append(f"<b>[{it['channel']}] {_esc(it['title'])}</b>")
        if a.get('one_liner'):
            lines.append(f"💡 {_esc(a['one_liner'])}")
        for kp in a.get('key_points', [])[:4]:
            t = kp.get('t') if isinstance(kp, dict) else None
            txt = _esc(_kp_text(kp))
            if t:
                lines.append(f"• {txt} <a href=\"{stamp_link(url, t)}\">[{fmt_ts(t)}]</a>")
            else:
                lines.append(f"• {txt}")
        tickers = a.get('tickers', [])
        if tickers:
            tags = []
            for tk in tickers[:8]:
                mark = {'긍정': '🟢', '부정': '🔴'}.get(tk.get('view', ''), '⚪')
                nm = _esc(tk.get('name', ''))
                code = f"({tk['ticker']})" if tk.get('ticker') else ''
                t = tk.get('t')
                if t:
                    tags.append(f"{mark}<a href=\"{stamp_link(url, t)}\">{nm}{_esc(code)}</a>")
                else:
                    tags.append(f"{mark}{nm}{_esc(code)}")
            lines.append('📌 ' + ', '.join(tags))
        lines.append(f"<a href=\"{url}\">▶️ 전체 영상</a>\n")
    return '\n'.join(lines)


def _send_digest(items: list, date_str: str, header: str | None = None):
    """텍스트 다이제스트 + 종목 차트를 텔레그램으로. (브로드캐스트 채널 설정 시 그쪽)"""
    if not getattr(config, 'TELEGRAM_ENABLED', False):
        return
    token = config.TELEGRAM_TOKEN
    if not token:
        print('⚠️ TELEGRAM_TOKEN 미설정 — 텔레그램 발송 불가. '
              'GitHub repo Settings→Secrets and variables→Actions 에 TELEGRAM_TOKEN 등록 필요.')
        return
    tg_chat = getattr(config, 'GURU_BROADCAST_CHAT', '') or config.TELEGRAM_CHAT_ID
    msg = build_telegram(items, date_str, header=header)
    ok = True
    for chunk in [msg[i:i + 3800] for i in range(0, len(msg), 3800)]:
        ok = send_message(token, tg_chat, chunk) and ok
    print(f'{"✅ 텔레그램 전송 성공" if ok else "❌ 텔레그램 전송 실패(토큰/chat_id 확인)"} → {tg_chat}')
    try:
        import guru_charts
        from telegram_notifier import send_photo
        path, series = guru_charts.build_chart(items)
        if path:
            sok = send_photo(token, tg_chat, path, guru_charts.build_caption(series))
            print(f'{"📊 차트 전송 성공" if sok else "❌ 차트 전송 실패"}: {len(series)}종목')
    except Exception as e:
        print(f'차트 생성 스킵: {e}')


def _within_hours(it: dict, hours: int) -> bool:
    ts = it.get('analyzed_at') or it.get('published')
    if not ts:
        return False
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    except Exception:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() <= hours * 3600


def roundup(hours: int = 24):
    """재분석 없이 지난 hours 시간의 투자 영상을 한 번에 종합 (매일 아침용)."""
    date_str = datetime.now(KST).strftime('%Y-%m-%d')
    print(f"\n🌅 아침 종합  |  {date_str}  (지난 {hours}시간)")
    history = load_history()
    recent = [it for it in history['items']
              if it.get('analysis', {}).get('relevant', True) and _within_hours(it, hours)]
    if not recent:
        print('지난 24시간 투자 영상 없음 — 종합 생략')
        return
    recent.sort(key=lambda x: x.get('published', ''), reverse=True)
    print(f'종합 대상 {len(recent)}개')
    header = f'<b>🌅 오늘 아침 종합 | {date_str}</b>\n지난 {hours}시간 투자 영상 {len(recent)}개'
    _send_digest(recent, date_str, header=header)


# ── 메인 ─────────────────────────────────────────────────────────────
def main():
    date_str = datetime.now(KST).strftime('%Y-%m-%d')
    print(f"\n{'═'*55}\n  🎙️ 구루 유튜브 일일 요약  |  {date_str}\n{'═'*55}\n")

    channels = load_channels()
    if not channels:
        print('분석할 채널 없음 (config.GURU_CHANNELS / data/guru_channels.json) — 종료')
        return

    history = load_history()
    seen = {it['video_id'] for it in history['items']}

    client = _gemini_client()
    new_items = []

    for ch in channels:
        name = ch['name']
        cid = resolve_channel_id(ch['id'])
        if not cid:
            print(f'⚠️  [{name}] 채널 ID 해석 실패 — 건너뜀 (id="{ch["id"]}")')
            continue
        vids = fetch_recent_videos(cid, name, ch.get('include'), ch.get('exclude'))
        vids = [v for v in vids if v['video_id'] not in seen][:MAX_PER_CHANNEL]
        print(f'📺 [{name}] 신규 분석 대상 {len(vids)}개')

        for v in vids:
            print(f'   ▶ {v["title"][:50]}')
            analysis, source = analyze(client, v)
            v['analysis'] = analysis
            v['source'] = source
            v['analyzed_at'] = datetime.now(KST).isoformat()
            rel = '✓' if analysis.get('relevant', True) else '✗비투자'
            print(f'      [{source}] 관련성:{rel} 종목:{len(analysis.get("tickers",[]))} 포인트:{len(analysis.get("key_points",[]))}')
            new_items.append(v)
            seen.add(v['video_id'])
            time.sleep(1)

    if not new_items:
        print('\n신규 영상 없음 — 종료')
        return

    new_items.sort(key=lambda x: x['published'], reverse=True)
    history['items'] = new_items + history['items']
    save_history(history)
    print(f'\n💾 저장: {RESULT_PATH}  (총 {len(history["items"])}개 보관)')

    relevant = [it for it in new_items if it.get('analysis', {}).get('relevant', True)]
    if not relevant:
        print('투자 관련 신규 영상 없음 — 텔레그램 생략')
        return
    _send_digest(new_items, date_str)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'roundup':
        roundup()
    else:
        main()
