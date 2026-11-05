from pathlib import Path

import pytest

from gastroflow.services.notice_formatting import clean_notice_html, notice_html
from tests.test_delivery_mask_browser import browser as browser_fixture


def test_rich_formatting_survives_and_dangerous_content_is_removed():
    raw = '''<h2 style="text-align:center;color:#aa1133">Promos</h2>
      <p><b>Dos muzzas</b> <i>para hornear</i> <u>$12.000</u></p>
      <span style="font-family:Georgia;font-size:24px;position:fixed;background:url(https://example.com)">Precio</span>
      <script>alert(1)</script><img src=x onerror=alert(1)><a href="javascript:alert(1)">enlace</a>'''
    html, text = clean_notice_html(raw)
    assert '<h2 style="text-align:center;color:#aa1133">Promos</h2>' in html
    assert '<b>Dos muzzas</b>' in html and '<i>para hornear</i>' in html and '<u>$12.000</u>' in html
    assert 'font-family:Georgia;font-size:24px' in html
    for unsafe in ('script', 'alert(', 'onerror', 'javascript:', 'position:', 'background:', '<img', '<a '):
        assert unsafe not in html
    assert '$12.000' in text and '<b>' not in text


def test_old_plain_notices_render_with_line_breaks_and_escape_html():
    assert notice_html({'mensaje': '2 muzzas\n<oferta>'}) == '<p>2 muzzas<br>&lt;oferta&gt;</p>'


@pytest.fixture
def browser():
    yield from browser_fixture.__wrapped__()


@pytest.fixture
def page(browser):
    page = browser.new_page()
    page.set_content(Path('gastroflow/internal_app/rich_text_editor/index.html').read_text(encoding='utf-8'))
    page.evaluate('''() => {
      window.updates = [];
      window.addEventListener('message', e => {
        if (e.data.type === 'streamlit:setComponentValue') window.updates.push(e.data.value);
      });
      window.postMessage({type:'streamlit:render', args:{initial_html:'<p>Promo muzza</p>'}}, '*');
    }''')
    page.wait_for_function("document.querySelector('#editor').textContent === 'Promo muzza'")
    yield page
    page.close()


def select_text(page):
    page.locator('#editor').focus()
    page.evaluate('''() => {
      const selected = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(document.querySelector('#editor'));
      selected.removeAllRanges(); selected.addRange(range);
      document.dispatchEvent(new Event('selectionchange'));
    }''')


def test_actual_editor_supports_inline_styles_color_and_alignment(page):
    select_text(page)
    page.get_by_role('button', name='Negrita', exact=True).click()
    page.get_by_role('button', name='Cursiva', exact=True).click()
    page.get_by_role('button', name='Subrayado', exact=True).click()
    page.get_by_label('Tipografía').select_option('Georgia')
    page.get_by_label('Color de texto').evaluate("e => {e.value='#aa1133'; e.dispatchEvent(new Event('input'));}")
    page.get_by_role('button', name='Centrar', exact=True).click()
    page.wait_for_function('window.updates.length > 0')
    raw = page.evaluate('window.updates.at(-1).html')
    html, text = clean_notice_html(raw)
    assert text == 'Promo muzza'
    assert 'font-weight:bold' in html
    assert 'font-style:italic' in html
    assert 'underline' in html and 'Georgia' in html
    assert 'text-align:center' in html and 'color:rgb(170, 17, 51)' in html


def test_editor_keeps_current_edit_when_parent_rerenders(page):
    page.locator('#editor').fill('Mensaje recién escrito')
    page.evaluate("window.postMessage({type:'streamlit:render',args:{initial_html:'<p>Viejo</p>'}}, '*')")
    assert page.locator('#editor').inner_text() == 'Mensaje recién escrito'
    page.wait_for_function("window.updates.at(-1).html.includes('recién escrito')")


def test_editor_heading_survives_sanitization(page):
    select_text(page)
    page.get_by_label('Tipo de texto').select_option('h2')
    page.wait_for_function("window.updates.length > 0")
    assert '<h2>' in clean_notice_html(page.evaluate('window.updates.at(-1).html'))[0]
