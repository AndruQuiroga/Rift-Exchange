"""Basic offline UX smoke tests. Requires Playwright and a local Chromium binary.

Run: python prototype/smoke_test.py
Uses page.set_content because some sandboxed browsers block file:// or localhost navigation.
Does not represent financial backend/security testing.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

HTML = Path(__file__).with_name('index.html').read_text()

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, executable_path='/opt/pw-browsers/chromium', args=['--no-sandbox'])
    for width in (320, 390, 768, 1440):
        page = browser.new_page(viewport={'width': width, 'height': 844})
        errors = []
        page.on('pageerror', lambda exc: errors.append(str(exc)))
        page.set_content(HTML, wait_until='load')
        assert page.locator('.hero-value').count() == 1, (width, 'wallet hero missing')
        assert page.evaluate('document.documentElement.scrollWidth') <= width, (width, 'horizontal scroll')
        assert '2,000' in page.locator('.hero-value').inner_text(), (width, 'opening balance')
        assert not errors, (width, errors)
        if width == 390:
            page.locator('button[data-outcome="a-win-0"]').first.click()
            assert page.locator('#mobile-slip:not(.hidden)').count() == 1
            page.locator('#mobile-slip').click()
            page.locator('#sheet [data-stake="a-win-0"]').fill('400')
            page.locator('#sheet [data-stake="a-win-0"]').dispatch_event('change')
            assert '648 RC' in page.locator('#sheet .slip-total.important').inner_text()
            page.locator('#sheet button[data-place]').click()
            assert page.locator('.ticket-card').count() == 1
            assert '400 RC' in page.locator('.ticket-card').inner_text()
            page.locator('[data-settle][data-grade="WON"]').click()
            page.locator('button[data-view="profile"]').last.click()
            assert '2,248' in page.locator('.hero-value').inner_text(), 'settlement arithmetic'
        if width == 1440:
            assert page.locator('.nav-btn').count() == 5, 'desktop navigation buttons'
            page.locator('button[data-outcome="a-win-1"]').first.click()
            assert '100' in page.locator('#rail-body').inner_text()
        print(f'PASS: {width}px')
        page.close()
    browser.close()
print('PASS: demo interaction smoke tests (browser-state only)')
