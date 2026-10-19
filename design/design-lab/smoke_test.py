"""Design exploration: responsive visual test and reference captures.
Run: python design-lab/smoke_test.py
"""
from pathlib import Path
from playwright.sync_api import sync_playwright
BASE=Path(__file__).resolve().parent
HTML=(BASE/'index.html').read_text()
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True, executable_path='/opt/pw-browsers/chromium', args=['--no-sandbox'])
    for theme in ('arena','sportsdesk','terminal'):
        for width in (320,390,768,1440):
            page=browser.new_page(viewport={'width':width,'height':844},device_scale_factor=1)
            errors=[]
            page.on('pageerror',lambda exc:errors.append(str(exc)))
            page.set_content(HTML,wait_until='load')
            page.locator(f'[data-settheme="{theme}"]').click()
            page.wait_for_timeout(240)  # wait until palette transition ends for accurate screenshots
            assert page.locator('body').get_attribute('data-theme')==theme
            assert page.evaluate('document.documentElement.scrollWidth')<=width,(theme,width,'horizontal overflow',page.evaluate('document.documentElement.scrollWidth'))
            assert not errors,errors
            if width==390:
                page.screenshot(path=str(BASE/f'{theme}-mobile.png'),full_page=True)
                page.locator('.odds button').first.click()
                assert page.locator('#mobile-open:visible').count()==1
                page.locator('#mobile-open').click()
                assert page.locator('#sheet.open').count()==1
                assert page.locator('#mobile-body [data-total]').inner_text()=='162 RC'
                page.locator('#sheet-close').click()
            if width==1440:page.screenshot(path=str(BASE/f'{theme}-desktop.png'),full_page=True)
            print(f'PASS {theme} {width}px')
            page.close()
    browser.close()
