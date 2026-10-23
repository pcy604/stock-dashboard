# -*- coding: utf-8 -*-
"""배포 앱 깨우기 + 실화면 건강 점검 (2026-10-21 깨우기, 2026-10-23 점검 추가)

Streamlit Community Cloud 는 한동안 접속이 없으면 앱을 재운다. 잠든 앱은 첫 방문자가
'Yes, get this app back up!' 을 누르고 수십 초 기다려야 한다(지인 베타 첫인상).
러너가 몇 시간마다 실제 브라우저로 들어가 깨워 둔다(단순 HTTP GET 으로는 안 깨어난다).

2026-10-23: 깨우기만 하고 앱이 에러 화면이어도 초록불이었다 → 메인 탭 5개 + 종목 분석
(TSLA·005930) 을 실제로 열어 Streamlit 예외 박스·Traceback 문구를 센다.
결과는 results/app_health.json (워크플로가 app-health 브랜치로 푸시) · 하나라도 깨지면 exit 1.
"""
import asyncio
import datetime as dt
import json
import os
import re
import sys

from playwright.async_api import async_playwright

URL = (sys.argv[1] if len(sys.argv) > 1 else
       'https://stock-dashboard-dmfvhcig7brge7utl7et5r.streamlit.app/').rstrip('/') + '/'
APP = URL + '~/+/'          # Cloud 래퍼(iframe) 없이 앱 본체
TABS = ["🏠 종합", "🌍 매크로", "🔎 종목 발굴", "🔍 종목 분석", "🛡️ 내 포트폴리오"]
SYMS = ['TSLA', '005930']
ERR_RE = re.compile(r'Traceback \(most recent call last\)|KeyError|TypeError|ValueError|'
                    r'AttributeError|NameError|IndexError|StreamlitAPIException|ModuleNotFoundError')


async def _settle(pg, max_s=150):
    """스크립트 실행이 끝날 때까지(‘Running…’ 표시가 사라질 때까지) 기다린다."""
    await pg.wait_for_timeout(3000)
    for _ in range(max_s // 3):
        running = await pg.locator('[data-testid="stStatusWidget"]').count()
        if not running:
            return True
        await pg.wait_for_timeout(3000)
    return False


async def _scan(pg, label):
    exc = await pg.locator('[data-testid="stException"]').count()
    txt = ''
    try:
        txt = await pg.locator('[data-testid="stMain"], section.main, body').first.inner_text(timeout=10000)
    except Exception:
        pass
    m = ERR_RE.findall(txt)
    errs = []
    if exc:
        for i in range(min(exc, 3)):
            try:
                errs.append((await pg.locator('[data-testid="stException"]').nth(i).inner_text())[:300])
            except Exception:
                pass
    ok = exc == 0 and not m and len(txt) > 200
    return {'page': label, 'ok': ok, 'exceptions': exc, 'error_words': sorted(set(m))[:5],
            'text_len': len(txt), 'samples': errs}


async def main():
    out = {'at': dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'), 'url': URL, 'checks': []}
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={'width': 1400, 'height': 1000})
        await pg.goto(URL, timeout=120000)
        await pg.wait_for_timeout(8000)
        try:
            btn = pg.get_by_role('button', name='Yes, get this app back up!')
            if await btn.count():
                print('잠들어 있었음 → 깨움')
                out['woke'] = True
                await btn.first.click()
                await pg.wait_for_timeout(90000)
            else:
                print('깨어 있음')
        except Exception as e:
            print('버튼 확인 실패', e)

        # 메인 탭 5개
        try:
            await pg.goto(APP, timeout=120000)
            await _settle(pg)
            for t in TABS:
                try:
                    await pg.get_by_role('tab', name=t).first.click(timeout=20000)
                    done = await _settle(pg)
                    r = await _scan(pg, t)
                    r['finished'] = done
                except Exception as e:
                    r = {'page': t, 'ok': False, 'error': f'탭 열기 실패: {e}'[:300]}
                out['checks'].append(r)
                print(('✅' if r['ok'] else '❌'), t, r.get('exceptions'), r.get('error_words') or r.get('error', ''))
            # 종목 분석 딥링크
            for s in SYMS:
                try:
                    await pg.goto(APP + f'?sym={s}', timeout=120000)
                    done = await _settle(pg, 180)
                    r = await _scan(pg, f'종목 분석 ?sym={s}')
                    r['finished'] = done
                except Exception as e:
                    r = {'page': f'?sym={s}', 'ok': False, 'error': str(e)[:300]}
                out['checks'].append(r)
                print(('✅' if r['ok'] else '❌'), s, r.get('exceptions'), r.get('error_words') or r.get('error', ''))
        except Exception as e:
            out['checks'].append({'page': 'app', 'ok': False, 'error': str(e)[:300]})
        await b.close()

    out['ok'] = bool(out['checks']) and all(c.get('ok') for c in out['checks'])
    os.makedirs('results', exist_ok=True)
    with open('results/app_health.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('실화면 점검:', '통과' if out['ok'] else '실패',
          f"{sum(c.get('ok', False) for c in out['checks'])}/{len(out['checks'])}")
    return 0 if out['ok'] else 1


sys.exit(asyncio.run(main()))
