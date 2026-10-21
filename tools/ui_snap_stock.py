# -*- coding: utf-8 -*-
"""종목 분석 탭 실데이터 화면 캡처 (2026-10-21) — ?sym= 로 바로 열어 전체 페이지를 찍고, 화면 오류·삼켜진 예외 문구를 텍스트로 남긴다.
산출물: data/research/ui/stock_<sym>.png · results/verify/ui_<sym>.txt"""
import asyncio, os, re, sys
from playwright.async_api import async_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'research', 'ui'); TXT = os.path.join(ROOT, 'results', 'verify')
os.makedirs(OUT, exist_ok=True); os.makedirs(TXT, exist_ok=True)


W = int(os.environ.get('SNAP_W', '1400'))           # 모바일 = 390(아이폰 폭)
SUF = '' if W >= 1000 else f'_m{W}'


async def one(b, sym, w=W):
    mob = w < 1000
    pg = await b.new_page(viewport={'width': w, 'height': 1200 if not mob else 844},
                          is_mobile=mob, has_touch=mob)
    await pg.goto(f'http://localhost:8501/?sym={sym}', timeout=300000)
    try:
        await pg.get_by_text('요약 판단').first.wait_for(timeout=900000)
    except Exception as e:
        print(sym, '요약 판단 안 뜸', e)
    for _ in range(3):                       # 늦게 그려지는 블록(Form 4·희석·AI 요약)까지
        for y in range(0, 30000, 900):
            await pg.mouse.wheel(0, 900); await pg.wait_for_timeout(250)
        await pg.wait_for_timeout(15000)
    H = await pg.evaluate("() => (document.querySelector('[data-testid=stMain]') || document.body).scrollHeight")
    await pg.set_viewport_size({'width': w, 'height': min(H + 200, 30000)})
    await pg.wait_for_timeout(10000)
    await pg.screenshot(path=os.path.join(OUT, f'stock_{sym}{SUF}.png'), full_page=True)
    txt = await pg.evaluate("() => (document.querySelector('[data-testid=stMain]') || document.body).innerText")
    errs = await pg.evaluate("() => [...document.querySelectorAll('[data-testid=stException],[data-testid=stAlertContentError]')].map(e => e.innerText.slice(0, 500))")
    swallowed = [l for l in txt.splitlines() if l.strip().startswith('`') or '실패' in l or 'Error' in l]
    with open(os.path.join(TXT, f'ui_{sym}{SUF}.txt'), 'w', encoding='utf-8') as f:
        f.write(f"H={H}\n== 오류 요소 {len(errs)}\n" + '\n'.join(errs) + f"\n== 실패·예외 문구 {len(swallowed)}\n" + '\n'.join(swallowed[:80])
                + "\n== 전체 텍스트\n" + txt)
    print(sym, 'H', H, 'errs', len(errs), 'swallowed', len(swallowed))
    await pg.close()


async def main(syms):
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for s in syms:
            try:
                await one(b, s)
            except Exception as e:
                print(s, 'snap 실패', e)
        await b.close()

asyncio.run(main(sys.argv[1:] or ['006110', 'TSLA']))
