# -*- coding: utf-8 -*-
"""배포 앱 깨우기 (2026-10-21) — Streamlit Community Cloud 는 한동안 접속이 없으면 앱을 재운다.
잠든 앱은 첫 방문자가 'Yes, get this app back up!' 을 누르고 수십 초 기다려야 한다(지인 베타 첫인상).
러너가 몇 시간마다 실제 브라우저로 들어가 깨워 둔다(단순 HTTP GET 으로는 안 깨어난다 — 버튼을 눌러야 한다)."""
import asyncio, sys
from playwright.async_api import async_playwright
URL = sys.argv[1] if len(sys.argv) > 1 else 'https://stock-dashboard-dmfvhcig7brge7utl7et5r.streamlit.app/'


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page()
        await pg.goto(URL, timeout=120000)
        await pg.wait_for_timeout(8000)
        try:
            btn = pg.get_by_role('button', name='Yes, get this app back up!')
            if await btn.count():
                print('잠들어 있었음 → 깨움')
                await btn.first.click()
                await pg.wait_for_timeout(90000)
            else:
                print('깨어 있음')
        except Exception as e:
            print('버튼 확인 실패', e)
        await pg.wait_for_timeout(20000)       # 앱 스크립트가 한 번 끝까지 돌아 캐시가 데워지게
        await b.close()

asyncio.run(main())
