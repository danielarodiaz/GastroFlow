import asyncio
from datetime import date
from decimal import Decimal
from itertools import combinations
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from sqlmodel import select

from gastroflow.domain.enums import FormaPago, ReglaPrecioCombo, TipoPromocion, UnidadVenta
from gastroflow.domain.errors import ValidationError
from gastroflow.models import Categoria, Cliente, ComboRegla, Pedido, PedidoItem, Producto, ProductoCategoria, Promocion, PromocionCategoria, PromocionProducto, ZonaEnvio
from gastroflow.services.combo_rules import HALF_PIZZA_FLAVORS, ensure_half_pizza_rules
from gastroflow.services.orders import OrderItemInput, OrderService, PublicOrderInput
from gastroflow.services.public_catalog import brand_cache, catalog_cache
from gastroflow.states import public_order_state as public
from gastroflow.states.public_order_state import PublicOrderState
from tests.test_orders import _catalog, _session


@pytest.fixture
def pizzas(monkeypatch):
    with _session() as session:
        ids = _catalog(session)
        session.add_all([Producto(codigo=name.upper(), nombre=name, unidad_venta=UnidadVenta.PIEZA)
                         for name in ("Calabresa", "Fugazzetta", "Napolitana")])
        session.flush()
        products = {product.nombre: product for product in session.exec(select(Producto)).all()}
        prices = {"Muzzarella": "6500", "Especial": "8000", "Calabresa": "8500", "Fugazzetta": "7500", "Napolitana": "9000"}
        for name, base in prices.items():
            for category_id, increment in [(ids["lista_horno"], 0), (ids["lista_comer"], 1000), (ids["mayorista"], -2000)]:
                relation = session.exec(select(ProductoCategoria).where(
                    ProductoCategoria.producto_id == products[name].id,
                    ProductoCategoria.categoria_id == category_id,
                )).first() or ProductoCategoria(producto_id=products[name].id, categoria_id=category_id, precio=0)
                relation.precio = Decimal(base) + increment
                session.add(relation)
        session.commit()
        ensure_half_pizza_rules(session)
        session.commit()
        ZonaEnvio.__table__.create(session.get_bind())
        catalog_cache.invalidate()
        brand_cache.invalidate()
        monkeypatch.setattr(public, "engine", session.get_bind())
        monkeypatch.setattr(public, "_read_brand_logo_url", lambda: "")
        monkeypatch.setattr(public, "_price_public_cart", lambda items: OrderService(session)._price_items(items, enforce_event_minimum=False))

        async def brand(self, cls):
            return SimpleNamespace(logo_url="")

        monkeypatch.setattr(PublicOrderState, "get_state", brand)
        state = PublicOrderState(_reflex_internal_init=True)

        async def load():
            _ = [event async for event in state.load_catalog()]

        asyncio.run(load())
        assert not state.catalog_error
        yield session, ids, products, state
        catalog_cache.invalidate()
        brand_cache.invalidate()


@pytest.mark.parametrize("first,second", list(combinations(HALF_PIZZA_FLAVORS, 2)))
@pytest.mark.parametrize("category", ["lista_horno", "lista_comer"])
def test_all_ten_pairs_use_only_the_selected_category_prices(pizzas, first, second, category):
    session, ids, products, state = pizzas
    first_id, second_id = products[first].id, products[second].id
    state.show_category(ids[category])
    state.open_product(first_id, ids[category])
    assert len(state.combo_options) == 4
    state.set_pizza_mode("Mitad y mitad")
    state.select_combo(str(second_id))
    category_prices = OrderService(session)._prices_for_category(ids[category])
    expected = (category_prices[first_id] + category_prices[second_id]) / 2
    assert state.detail_price_display == f"{expected:.2f}".replace(".", ",")
    line = OrderService(session)._price_items([OrderItemInput(
        first_id, 1, second_id, "LISTA_HORNO" if category == "lista_horno" else "LISTA_COMER",
    )])[0]
    assert line.precio_unitario == expected
    assert line.categoria_venta_id == ids[category]


def test_combo_registration_is_idempotent_and_reuses_reverse_pairs(pizzas):
    session, _, _, _ = pizzas
    rules = session.exec(select(ComboRegla)).all()
    original_ids = {rule.id for rule in rules}
    rules[0].producto_a_id, rules[0].producto_b_id = rules[0].producto_b_id, rules[0].producto_a_id
    rules[0].regla_precio = ReglaPrecioCombo.MAYOR_VALOR
    session.add(rules[0])
    session.commit()
    ensure_half_pizza_rules(session)
    session.commit()
    updated = session.exec(select(ComboRegla)).all()
    assert len(updated) == 10
    assert {rule.id for rule in updated} == original_ids
    assert all(rule.regla_precio == ReglaPrecioCombo.PROMEDIO and not rule.requiere_confirmacion for rule in updated)
    assert len({tuple(sorted((rule.producto_a_id, rule.producto_b_id))) for rule in updated}) == 10


def test_registration_refuses_missing_flavors_without_creating_rules():
    with _session() as session:
        _catalog(session)
        original = session.exec(select(ComboRegla)).all()
        with pytest.raises(ValidationError, match="Calabresa"):
            ensure_half_pizza_rules(session)
        assert session.exec(select(ComboRegla)).all() == original


@pytest.mark.parametrize("invalid", ["hidden", "inactive_relation", "inactive_product", "missing_category", "same_flavor", "missing_rule"])
def test_backend_rejects_invalid_halves_even_if_a_client_bypasses_the_ui(pizzas, invalid):
    session, ids, products, _ = pizzas
    first, second = products["Especial"].id, products["Fugazzetta"].id
    relation = session.exec(select(ProductoCategoria).where(
        ProductoCategoria.producto_id == second, ProductoCategoria.categoria_id == ids["lista_comer"],
    )).one()
    if invalid == "hidden":
        relation.visible = False
        session.add(relation)
    elif invalid == "inactive_relation":
        relation.activo = False
        session.add(relation)
    elif invalid == "missing_category":
        session.delete(relation)  # The flavor still exists in Horno, which must not be used.
    elif invalid == "inactive_product":
        products["Fugazzetta"].activo = False
        session.add(products["Fugazzetta"])
    elif invalid == "same_flavor":
        second = first
    elif invalid == "missing_rule":
        session.delete(OrderService(session)._get_combo_rule(first, second))
    session.commit()
    with pytest.raises(ValidationError):
        OrderService(session)._price_items([OrderItemInput(first, 1, second, "LISTA_COMER")])


def test_cart_distinguishes_whole_pizzas_pairs_and_categories_and_preserves_checkout(pizzas, monkeypatch):
    _, ids, products, state = pizzas
    submitted = []

    def create(payload):
        submitted.append(payload)
        return SimpleNamespace(pedido=SimpleNamespace(codigo="PED-MITADES", monto_total=Decimal(state.cart_total)))

    monkeypatch.setattr(public, "_create_public_order", create)

    async def add(first, second=None, category="lista_horno"):
        state.show_category(ids[category])
        state.open_product(products[first].id, ids[category])
        if second:
            state.set_pizza_mode("Mitad y mitad")
            state.select_combo(str(products[second].id))
        _ = [event async for event in state.add_selected_to_cart()]
        assert not state.technical_error

    async def run():
        await add("Especial")
        await add("Especial", "Fugazzetta")
        await add("Fugazzetta", "Especial")
        await add("Especial", "Calabresa")
        await add("Especial", "Fugazzetta", "lista_comer")
        assert len(state.cart) == 4
        assert [item["cantidad"] for item in state.cart] == [1, 2, 1, 1]
        assert state.cart[1]["nombre"] == "Mitad Especial / mitad Fugazzetta"
        assert state.cart[1]["subtotal_display"] == "15500,00"
        assert state.cart[3]["subtotal_display"] == "8750,00"
        _ = [event async for event in state.remove_cart_item(products["Especial"].id, "LISTA_HORNO", products["Fugazzetta"].id)]
        assert len(state.cart) == 3
        assert state.cart[0]["nombre"] == "Especial"
        assert state.cart[1]["nombre"] == "Mitad Especial / mitad Calabresa"
        assert state.cart[2]["categoria_codigo"] == "LISTA_COMER"
        state.nombre_apellido, state.telefono = "Cliente Prueba", "3815551234"
        state.fecha_entrega, state.horario_entrega = "25/12/2026", "21"
        _ = [event async for event in state.submit_order({})]
        assert state.registered_order_code == "PED-MITADES"
        assert "Mitad Especial / mitad Fugazzetta" in unquote(state.whatsapp_url)

    asyncio.run(run())
    assert len(submitted) == 1
    assert [item.producto_combo_id for item in submitted[0].items] == [None, products["Calabresa"].id, products["Fugazzetta"].id]


def test_second_flavor_is_required_and_navigation_resets_selection(pizzas):
    _, ids, products, state = pizzas
    state.show_category(ids["lista_horno"])
    state.open_product(products["Especial"].id, ids["lista_horno"])
    state.set_pizza_mode("Mitad y mitad")

    async def add():
        _ = [event async for event in state.add_selected_to_cart()]

    asyncio.run(add())
    assert not state.cart
    assert state.message == "Elegí el sabor de la otra mitad."
    state.select_combo(str(products["Fugazzetta"].id))
    state.show_category(ids["lista_comer"])
    assert state.pizza_mode == "Un solo sabor"
    assert state.selected_combo_id == ""
    state.show_category(ids["eventos"])
    state.open_product(products["Muzzarella"].id, ids["eventos"])
    assert not state.combo_options


def test_halves_do_not_receive_whole_pizza_promos_and_count_as_one_for_wholesale(pizzas):
    session, ids, products, _ = pizzas
    first, second = products["Especial"].id, products["Fugazzetta"].id
    promo = Promocion(codigo="PROMO_ESPECIAL", nombre="2 especiales", tipo=TipoPromocion.PRECIO_UNITARIO_POR_CANTIDAD,
        cantidad_minima=2, precio_unitario_promocional=Decimal("1000"))
    session.add(promo)
    session.flush()
    session.add_all([PromocionProducto(promocion_id=promo.id, producto_id=first),
        PromocionCategoria(promocion_id=promo.id, categoria_id=ids["lista_horno"])])
    session.commit()
    service = OrderService(session)
    two = service._price_items([OrderItemInput(first, 2, second)])[0]
    assert two.subtotal == Decimal("15500")
    nine = service._price_items([OrderItemInput(first, 9, second)])[0]
    assert nine.categoria_venta_id == ids["lista_horno"]
    ten = service._price_items([OrderItemInput(first, 10, second)])[0]
    assert ten.categoria_venta_id == ids["mayorista"]
    assert ten.precio_unitario == Decimal("5750")


def test_confirmation_persists_both_flavors_and_category_with_average_price(pizzas, monkeypatch):
    session, ids, products, _ = pizzas
    for model in (Cliente, Pedido, PedidoItem):
        model.__table__.create(session.get_bind())
    monkeypatch.setattr("gastroflow.services.orders.next_business_code", lambda *args: "PED-MITADES")
    first, second = products["Especial"].id, products["Fugazzetta"].id
    result = OrderService(session).create_public_order(PublicOrderInput(
        nombre_apellido="Cliente Prueba", telefono="3815551234", fecha_entrega=date(2026, 12, 25),
        direccion_delivery="Retiro en el local", forma_pago=FormaPago.EFECTIVO,
        items=[OrderItemInput(first, 2, second, "LISTA_COMER")],
    ))
    item = session.exec(select(PedidoItem)).one()
    assert (item.producto_id, item.producto_combo_id, item.categoria_venta_id) == (first, second, ids["lista_comer"])
    assert item.precio_unitario == Decimal("8750")
    assert item.subtotal == result.pedido.monto_total == Decimal("17500")
