"""Regressions for client interactions under delayed server responses."""

import asyncio

import pytest

from gastroflow.components.public_interactions import INTERACTIONS_SCRIPT
from gastroflow.public_ui import public_page
from tests.test_delivery_mask_browser import browser as browser_fixture
from tests.test_half_pizzas import pizzas
from tests.test_public_checkout import _state
from gastroflow.states import public_order_state as public


@pytest.fixture
def browser():
    # Keep Playwright's sync event loop scoped to each browser test.
    yield from browser_fixture.__wrapped__()


@pytest.fixture
def page(browser):
    page = browser.new_page()
    page.set_content('''
      <div id="root" data-navigation-revision="0" data-cart-revision="0">
        <input id="editing" value="2115">
        <button data-public-navigation="true">Volver</button>
        <form data-public-cart-action="true">
          <input name="detail_quantity" type="hidden" value="1">
          <button type="button" data-quantity-step="-1">−</button>
          <output data-quantity-display="true">1</output>
          <button type="button" data-quantity-step="1">+</button>
          <button type="submit">Agregar</button>
        </form>
      </div>
    ''')
    page.add_script_tag(content=INTERACTIONS_SCRIPT)
    page.evaluate('''() => {
      window.root = document.querySelector('#root');
      window.attach = () => window.dispose = attachPublicInteractions(root);
      attach();
      window.navigations = 0; window.submissions = [];
      root.querySelector('[data-public-navigation]').addEventListener('click', () => window.navigations++);
      root.querySelector('form').addEventListener('submit', event => {
        event.preventDefault(); window.submissions.push(Object.fromEntries(new FormData(event.target)));
      });
    }''')
    yield page
    page.close()


def test_quantity_is_immediate_preserves_edits_and_submits_exactly_once(page):
    page.evaluate('''() => {
      for (let i = 0; i < 20; i++) root.querySelector('[data-quantity-step="1"]').click();
      // An unrelated render/late server response must not reset the local count.
      dispose(); attach();
    }''')
    assert page.locator('output').inner_text() == '21'
    assert page.locator('[name="detail_quantity"]').input_value() == '21'
    page.get_by_text('Agregar', exact=True).click()
    page.get_by_text('Agregar', exact=True).click(force=True)
    page.get_by_text('+', exact=True).click()
    assert page.evaluate('window.submissions') == [{'detail_quantity': '21'}]
    assert page.locator('output').inner_text() == '21'
    # Server validation error or completed action unlocks the next attempt.
    page.evaluate("() => {dispose(); root.dataset.cartRevision='1'; attach();}")
    page.get_by_text('Agregar', exact=True).click()
    assert len(page.evaluate('window.submissions')) == 2


def test_navigation_first_click_keeps_focus_and_blocks_duplicates_until_ack(page):
    page.locator('#editing').focus()
    page.evaluate("() => {window.blurs = 0; document.querySelector('#editing').addEventListener('blur', () => window.blurs++);}")
    button = page.get_by_role('button', name='Volver')
    button.click()
    assert page.evaluate('window.navigations') == 1
    assert page.evaluate('window.blurs') == 0
    assert button.get_attribute('aria-busy') == 'true'
    page.evaluate('() => {dispose(); attach();}')
    button.click(force=True)
    assert page.evaluate('window.navigations') == 1
    page.evaluate("() => {dispose(); root.dataset.navigationRevision='1'; attach();}")
    button.focus()
    button.press('Enter')
    assert page.evaluate('window.navigations') == 2


def test_quantity_never_goes_below_one(page):
    page.get_by_text('−', exact=True).click(click_count=3)
    assert page.locator('output').inner_text() == '1'


@pytest.mark.parametrize('field,label', [
    ('nombre_apellido', 'Nombre y apellido'), ('telefono', 'Celular'),
    ('fecha_entrega', 'Fecha de entrega'), ('horario_entrega', 'Horario ideal de entrega'),
    ('direccion_delivery', 'Dirección'), ('pago_efectivo', 'Monto en efectivo'),
    ('pago_transferencia', 'Monto por transferencia'),
])
def test_required_checkout_data_is_checked_on_server(monkeypatch, field, label):
    state = _state()
    state.delivery_mode = 'delivery'
    state.direccion_delivery = 'Calle 123'
    state.zona_envio_id = '1'
    state.forma_pago = 'mixto'
    state.pago_efectivo = state.pago_transferencia = '50'
    monkeypatch.setattr(public, '_create_public_order', lambda _: pytest.fail('Incomplete order reached persistence'))

    async def submit():
        return [event async for event in state.submit_order({field: '   '})]

    asyncio.run(submit())
    assert state.message == f'Completá el campo {label}.'
    assert not state.is_submitting


def test_form_contains_native_required_fields_except_observations():
    # Build the actual tree, including conditional delivery/mixed payment inputs.
    fields = {}
    def walk(value):
        if isinstance(value, dict):
            props = value.get('props', [])
            for prop in props:
                if prop.startswith('name:'):
                    fields[prop.removeprefix('name:').strip('"')] = props
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(public_page().render())
    for name in ('nombre_apellido', 'telefono', 'fecha_entrega', 'horario_entrega',
                 'direccion_delivery', 'pago_efectivo', 'pago_transferencia'):
        assert 'required:true' in fields[name], name
    assert 'required:true' not in fields['observaciones']


def test_quantity_submitted_from_browser_overrides_stale_server_state(pizzas):
    _, ids, products, state = pizzas
    state.show_category(ids['lista_horno'])
    state.open_product(products['Muzzarella'].id, ids['lista_horno'])
    assert state.detail_quantity == '1'
    async def add():
        return [event async for event in state.add_selected_to_cart({'detail_quantity': '7'})]
    asyncio.run(add())
    assert state.cart[0]['cantidad'] == 7
    assert state.cart_action_revision == 1


def test_invalid_quantity_unlocks_cart_action(pizzas):
    _, ids, products, state = pizzas
    state.show_category(ids['lista_horno'])
    state.open_product(products['Muzzarella'].id, ids['lista_horno'])
    async def add():
        return [event async for event in state.add_selected_to_cart({'detail_quantity': '0'})]
    asyncio.run(add())
    assert not state.cart
    assert state.cart_action_revision == 1
