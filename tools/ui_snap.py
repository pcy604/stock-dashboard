# -*- coding: utf-8 -*-
"""매크로 탭 실데이터 화면 캡처 (2026-10-21) — CI 러너(인터넷 됨)에서 streamlit 을 띄우고 playwright 로 찍는다.
산출물: data/research/ui/macro_*.png"""
import asyncio, os, sys, time
from playwright.async_api import async_playwright
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'research', 'ui')
os.makedirs(OUT, exist_ok=True)


async def main(w):
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={'width': w, 'height': 1000})
        await pg.goto('http://localhost:8501', timeout=300000)
        await pg.get_by_role('tab', name='🌍 매크로').wait_for(timeout=600000)
        await pg.wait_for_timeout(5000)
        await pg.get_by_role('tab', name='🌍 매크로').click()
        await pg.get_by_text('욕심 조절 원칙').first.wait_for(timeout=600000)
        await pg.wait_for_timeout(8000)
        try:
            await pg.get_by_text('📊 상세 지표 차트').first.click()
            await pg.wait_for_timeout(15000)
        except Exception as e:
            print('expander', e)
        for y in range(0, 16000, 700):
            await pg.mouse.wheel(0, 700); await pg.wait_for_timeout(500)
        H = await pg.evaluate("() => { const m = document.querySelector('[data-testid=stMain]') || document.body; return m.scrollHeight }")
        await pg.set_viewport_size({'width': w, 'height': min(H + 200, 16000)})
        await pg.wait_for_timeout(8000)
        await pg.screenshot(path=os.path.join(OUT, f'macro_{w}.png'), full_page=True)
        # 상세 차트의 다른 탭들도
        for nm in ['📈 10년 국채', '📉 수익률곡선', '🔥 물가', '💧 유동성']:
            try:
                el = pg.get_by_role('tab', name=nm)
                await el.click(); await pg.wait_for_timeout(6000)
                box = pg.locator('[data-testid=stExpander]').filter(has_text='상세 지표 차트').first
                await box.screenshot(path=os.path.join(OUT, f'detail_{nm.split()[1]}.png'))
            except Exception as e:
                print('tab', nm, e)
        print('H', H)
        await b.close()

asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 1400))
