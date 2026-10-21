import asyncio
from datetime import date
from decimal import Decimal
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlmodel import create_engine, select

from gastroflow.domain.enums import EstadoPedido, FormaPago, RolUsuario, TipoPromocion
from gastroflow.domain.errors import ValidationError
from gastroflow.internal_app import streamlit_app as internal
from gastroflow.models import Cliente, Pedido, PedidoItem, ProductoCategoria, Promocion, PromocionCategoria, PromocionProducto
from gastroflow.services.orders import OrderItemInput, OrderService, PublicOrderInput
from gastroflow.services.public_catalog import catalog_cache
from gastroflow.services.promotions import configure_promotion
from gastroflow.states import public_order_state as public
from tests.test_half_pizzas import pizzas


@pytest.fixture
def specials(pizzas, monkeypatch):
    session, ids, products, state = pizzas
    for name in ("Fugazzetta", "Napolitana"):
        for category in ("lista_horno", "eventos"):
            relation = session.exec(select(ProductoCategoria).where(
                ProductoCategoria.producto_id == products[name].id,
                ProductoCategoria.categoria_id == ids[category],
            )).first() or ProductoCategoria(producto_id=products[name].id, categoria_id=ids[category], precio=Decimal("6500"))
            relation.visible, relation.permite_pedido_especial = False, True
            session.add(relation)
    session.commit()
    for model in (Cliente, Pedido, PedidoItem):
        model.__table__.create(session.get_bind())
    monkeypatch.setattr("gastroflow.services.orders.next_business_code", lambda *args: "PED-ESPECIAL")
    catalog_cache.invalidate()

    async def load():
        _ = [event async for event in state.load_catalog()]

    asyncio.run(load())
    yield session, ids, products, state


def _payload(items):
    return PublicOrderInput(nombre_apellido="Cliente Prueba", telefono="3815551234", fecha_entrega=date(2026, 12, 25),
        direccion_delivery="Retiro", forma_pago=FormaPago.TRANSFERENCIA, items=items, submission_token="special-retry")


def test_specials_stay_out_of_regular_catalog_and_are_explicitly_available_by_request(specials):
    _, ids, products, state = specials
    for category in ("lista_horno", "eventos"):
        state.show_category(ids[category])
        assert state.has_special_catalog
        assert not any(item["es_especial"] for item in state.visible_products)
        state.open_product(products["Fugazzetta"].id, ids[category])
        assert state.view == "products" and not state.selected_product
        state.show_special_category(ids[category])
        assert {item["nombre"] for item in state.visible_products} == {"Fugazzetta", "Napolitana"}
        state.open_product(products["Fugazzetta"].id, ids[category])
        assert state.view == "detail" and state.detail_is_special
    state.show_category(ids["lista_comer"])
    assert not state.has_special_catalog
    assert "Fugazzetta" in {item["nombre"] for item in state.visible_products}


def test_special_half_pizza_uses_average_and_marks_entire_line_special(specials):
    session, ids, products, state = specials
    state.show_category(ids["lista_horno"])
    state.open_product(products["Muzzarella"].id, ids["lista_horno"])
    assert "Fugazzetta" not in {item["nombre"] for item in state.combo_options}
    state.show_special_category(ids["lista_horno"])
    state.open_product(products["Fugazzetta"].id, ids["lista_horno"])
    state.set_pizza_mode("Mitad y mitad")
    state.select_combo(str(products["Muzzarella"].id))
    assert state.detail_price_display == "7000,00"
    assert state.detail_is_special
    priced = OrderService(session)._price_items([OrderItemInput(
        products["Muzzarella"].id, 1, products["Fugazzetta"].id, "LISTA_HORNO",
    )])[0]
    assert priced.precio_unitario == Decimal("7000")
    assert priced.es_especial and priced.requiere_confirmacion


@pytest.mark.parametrize("event_units", [1, 9, 10])
def test_events_minimum_includes_regular_and_special_pizzas_only_in_events(specials, event_units):
    session, _, products, state = specials
    items = [OrderItemInput(products["Fugazzetta"].id, 1, contexto_origen="EVENTOS")]
    if event_units > 1:
        items.append(OrderItemInput(products["Muzzarella"].id, event_units - 1, contexto_origen="EVENTOS"))
    items.append(OrderItemInput(products["Muzzarella"].id, 12, contexto_origen="LISTA_HORNO"))
    service = OrderService(session)
    assert service._price_items(items, enforce_event_minimum=False)[0].es_especial
    state.cart = [{"producto_id": item.producto_id, "cantidad": item.cantidad, "categoria_codigo": item.contexto_origen} for item in items]
    assert bool(state.events_minimum_message) == (event_units < 10)
    if event_units < 10:
        with pytest.raises(ValidationError, match="10 unidades"):
            service._price_items(items)
    else:
        assert service._price_items(items)[0].precio_unitario == Decimal("6500")


def test_special_uses_applicable_tariff_without_regular_promotions(specials):
    session, ids, products, _ = specials
    promo = Promocion(codigo="SPECIAL_TEST", nombre="No aplicar", tipo=TipoPromocion.PRECIO_UNITARIO_POR_CANTIDAD,
        cantidad_minima=2, precio_unitario_promocional=Decimal("1"))
    session.add(promo)
    session.flush()
    session.add_all([PromocionProducto(promocion_id=promo.id, producto_id=products["Fugazzetta"].id),
        PromocionCategoria(promocion_id=promo.id, categoria_id=ids["lista_horno"])])
    session.commit()
    for quantity in (2, 10):
        line = OrderService(session)._price_items([OrderItemInput(products["Fugazzetta"].id, quantity)])[0]
        assert line.categoria_venta_id == ids["lista_horno" if quantity == 2 else "mayorista"]
        assert line.precio_unitario == Decimal("7500" if quantity == 2 else "5500")
        assert line.es_especial and line.requiere_confirmacion
    with pytest.raises(ValidationError, match="pertenecer"):
        configure_promotion(session, promo, [ids["lista_horno"]], [products["Fugazzetta"].id], [])


def test_twenty_pizza_order_applies_wholesale_to_all_five_flavors_and_stays_pending(specials):
    session, ids, products, state = specials
    flavors = ["Muzzarella", "Especial", "Calabresa", "Fugazzetta", "Napolitana"]
    items = [OrderItemInput(products[name].id, 4, contexto_origen="LISTA_HORNO") for name in flavors]
    service = OrderService(session)
    priced = service._price_items(items)
    assert [line.precio_unitario for line in priced] == [Decimal(price) for price in (4500, 6000, 6500, 5500, 7000)]
    assert all(line.categoria_venta_codigo == "MAYORISTA" for line in priced)
    assert [line.es_especial for line in priced] == [False, False, False, True, True]
    state.cart = [{"producto_id": products[name].id, "nombre": name, "cantidad": 4,
        "categoria": "Lista para hornear", "categoria_codigo": "LISTA_HORNO",
        "precio": str(next(product["precio"] for product in state.products
                           if product["id"] == products[name].id and product["categoria_id"] == ids["lista_horno"]))}
        for name in flavors]
    asyncio.run(state._refresh_cart_total())
    assert not state.technical_error
    assert state.cart_total == "118000.00"
    assert all(line["categoria_display"] == "Lista para hornear / Mayorista" for line in state.cart)
    assert state.cart_has_special_orders
    assert [line["es_especial"] for line in state.cart] == [False, False, False, True, True]
    result = service.create_public_order(_payload(items))
    assert result.es_especial
    assert result.pedido.estado == EstadoPedido.PENDIENTE_CONFIRMACION
    assert result.pedido.monto_total == Decimal("118000")
    saved = session.exec(select(PedidoItem).order_by(PedidoItem.id)).all()
    assert all(line.categoria_venta_id == ids["mayorista"] for line in saved)
    assert [line.es_especial for line in saved] == [False, False, False, True, True]


@pytest.mark.parametrize("regular_quantity", [5, 6])
def test_special_units_count_for_wholesale_threshold(specials, regular_quantity):
    session, ids, products, _ = specials
    priced = OrderService(session)._price_items([
        OrderItemInput(products["Muzzarella"].id, regular_quantity),
        OrderItemInput(products["Fugazzetta"].id, 4),
    ])
    wholesale = regular_quantity == 6
    assert all(line.categoria_venta_id == ids["mayorista" if wholesale else "lista_horno"] for line in priced)
    assert priced[1].precio_unitario == Decimal("5500" if wholesale else "7500")
    assert priced[1].es_especial and priced[1].requiere_confirmacion


def test_special_half_pizza_uses_both_wholesale_prices_and_keeps_availability_pending(specials):
    session, ids, products, _ = specials
    line = OrderService(session)._price_items([OrderItemInput(
        products["Muzzarella"].id, 10, products["Fugazzetta"].id, "LISTA_HORNO",
    )])[0]
    assert line.precio_unitario == Decimal("5000")
    assert line.subtotal == Decimal("50000")
    assert line.categoria_venta_id == ids["mayorista"]
    assert line.es_especial and line.requiere_confirmacion


def test_missing_wholesale_price_never_silently_uses_regular_price_for_special(specials):
    session, ids, products, _ = specials
    relation = session.exec(select(ProductoCategoria).where(
        ProductoCategoria.producto_id == products["Fugazzetta"].id,
        ProductoCategoria.categoria_id == ids["mayorista"],
    )).one()
    session.delete(relation)
    session.commit()
    with pytest.raises(ValidationError, match="precio configurado"):
        OrderService(session)._price_items([OrderItemInput(products["Fugazzetta"].id, 10)])


def test_mixed_order_is_pending_until_accepted_and_snapshot_survives_catalog_changes(specials, monkeypatch):
    session, ids, products, _ = specials
    service = OrderService(session)
    payload = _payload([OrderItemInput(products["Muzzarella"].id, 1), OrderItemInput(products["Fugazzetta"].id, 1)])
    result = service.create_public_order(payload)
    assert result.es_especial and result.pedido.estado == EstadoPedido.PENDIENTE_CONFIRMACION
    assert result.pedido.monto_total == Decimal("14000")
    assert [item.es_especial for item in session.exec(select(PedidoItem).order_by(PedidoItem.id)).all()] == [False, True]
    replay = service.create_public_order(payload)
    assert replay.es_especial and replay.pedido.id == result.pedido.id
    assert len(session.exec(select(Pedido)).all()) == 1
    relation = session.exec(select(ProductoCategoria).where(
        ProductoCategoria.producto_id == products["Fugazzetta"].id,
        ProductoCategoria.categoria_id == ids["lista_horno"],
    )).one()
    relation.permite_pedido_especial = False
    session.add(relation)
    session.commit()
    owner = SimpleNamespace(rol=RolUsuario.DUENO)
    with pytest.raises(ValidationError, match="Primero aceptá"):
        service.transition_order(result.pedido.id, EstadoPedido.EN_PROCESO, owner)
    monkeypatch.setattr(internal, "engine", session.get_bind())
    internal._load_order_rows.clear()
    rows = internal._load_order_rows()
    assert rows[0]["es_especial"]
    assert internal._build_production_summary(rows) == {}
    accepted = service.transition_order(result.pedido.id, EstadoPedido.PEDIDO, owner)
    assert accepted.monto_total == Decimal("14000")
    internal._load_order_rows.clear()
    assert internal._build_production_summary(internal._load_order_rows())
    assert service.transition_order(result.pedido.id, EstadoPedido.EN_PROCESO, owner).estado == EstadoPedido.EN_PROCESO
    internal._load_order_rows.clear()


def test_local_can_reject_special_request_without_changing_prices(specials):
    session, _, products, _ = specials
    service = OrderService(session)
    result = service.create_public_order(_payload([OrderItemInput(products["Napolitana"].id, 1)]))
    rejected = service.transition_order(result.pedido.id, EstadoPedido.CANCELADO, SimpleNamespace(rol=RolUsuario.DUENO))
    assert rejected.estado == EstadoPedido.CANCELADO
    assert rejected.monto_total == result.pedido.monto_total


def test_staff_interface_accepts_availability_before_preparation(specials, monkeypatch):
    from streamlit.testing.v1 import AppTest

    session, _, products, _ = specials
    result = OrderService(session).create_public_order(_payload([OrderItemInput(products["Fugazzetta"].id, 1)]))
    monkeypatch.setattr(internal, "engine", session.get_bind())
    monkeypatch.setattr(internal, "_current_user", lambda: SimpleNamespace(rol=RolUsuario.DUENO))
    internal._load_order_rows.clear()
    # AppTest reruns the full script rather than issuing fragment-only reruns.
    rerun = internal.st.rerun
    monkeypatch.setattr(internal.st, "rerun", lambda **kwargs: rerun())

    def page():
        from gastroflow.internal_app.streamlit_app import _init_session_state, _render_orders
        _init_session_state()
        _render_orders()

    app = AppTest.from_function(page, default_timeout=10).run()
    assert not app.exception
    labels = {button.label for button in app.button}
    assert "Aceptar disponibilidad" in labels and "Rechazar solicitud" in labels
    assert "🟠 Pasar a preparacion" not in labels
    next(button for button in app.button if button.label == "Aceptar disponibilidad").click().run()
    assert not app.exception
    session.expire_all()
    assert session.get(Pedido, result.pedido.id).estado == EstadoPedido.PEDIDO
    assert session.get(Pedido, result.pedido.id).monto_total == Decimal("7500")
    assert "🟠 Pasar a preparacion" in {button.label for button in app.button}
    internal._load_order_rows.clear()


def test_hidden_product_requires_explicit_special_permission_even_for_forged_requests(specials):
    session, ids, products, _ = specials
    relation = session.exec(select(ProductoCategoria).where(
        ProductoCategoria.producto_id == products["Fugazzetta"].id,
        ProductoCategoria.categoria_id == ids["lista_horno"],
    )).one()
    relation.permite_pedido_especial = False
    session.add(relation)
    session.commit()
    with pytest.raises(ValidationError, match="no está disponible"):
        OrderService(session)._price_items([OrderItemInput(products["Fugazzetta"].id, 1)])


def test_customer_flow_stores_special_line_and_whatsapp_has_no_transfer_instructions(specials, monkeypatch):
    session, ids, products, state = specials
    monkeypatch.setattr(public, "_create_public_order", lambda payload: OrderService(session).create_public_order(payload))
    monkeypatch.setattr(public, "TRANSFER_ALIAS", "NO-MOSTRAR-ALIAS")

    async def run():
        state.show_special_category(ids["lista_horno"])
        state.open_product(products["Fugazzetta"].id, ids["lista_horno"])
        state.set_pizza_mode("Mitad y mitad")
        state.select_combo(str(products["Muzzarella"].id))
        _ = [event async for event in state.add_selected_to_cart()]
        assert state.cart_has_special_orders
        assert state.cart[0]["es_especial"]
        assert state.cart_total_display == "7000,00"
        state.nombre_apellido, state.telefono = "Cliente Prueba", "3815551234"
        state.fecha_entrega, state.horario_entrega = "25/12/2026", "21"
        state.forma_pago = "transferencia"
        _ = [event async for event in state.submit_order({})]
        assert state.registered_order_is_special
        assert "precio es definitivo" in state.message
        assert "disponibilidad" in state.message
        message = unquote(state.whatsapp_url)
        assert "PENDIENTE DE ACEPTACIÓN DE DISPONIBILIDAD" in message
        assert "No realizar el pago" in message
        assert "NO-MOSTRAR-ALIAS" not in message
        assert "Datos para la transferencia" not in message
        assert "Mitad Muzzarella / mitad Fugazzetta" in message
        assert session.exec(select(PedidoItem)).one().es_especial
        state.start_new_order()
        assert not state.registered_order_is_special
        assert not state.cart_has_special_orders

    asyncio.run(run())


def test_special_order_migration_enables_only_requested_presentations_and_keeps_prices(monkeypatch):
    engine = create_engine("sqlite://")
    spec = importlib.util.spec_from_file_location("special_migration", Path("alembic/versions/0010_special_orders.py"))
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE categoria (id INTEGER PRIMARY KEY, codigo TEXT)"))
        connection.execute(text("CREATE TABLE producto (id INTEGER PRIMARY KEY, nombre TEXT)"))
        connection.execute(text("CREATE TABLE producto_categoria (id INTEGER PRIMARY KEY, producto_id INTEGER, categoria_id INTEGER, precio NUMERIC, visible BOOLEAN)"))
        connection.execute(text("CREATE TABLE pedido_item (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO categoria VALUES (1, 'LISTA_HORNO'), (2, 'EVENTOS'), (3, 'LISTA_COMER')"))
        connection.execute(text("INSERT INTO producto VALUES (1, 'Fugazzetta'), (2, 'Napolitana'), (3, 'Muzzarella')"))
        connection.execute(text("INSERT INTO producto_categoria VALUES (1,1,1,7500,0),(2,1,2,6500,0),(3,2,1,7500,0),(4,2,2,6500,0),(5,1,3,9500,1),(6,3,1,6500,1)"))
        connection.execute(text("INSERT INTO pedido_item VALUES (1)"))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        before = connection.execute(text("SELECT id, precio FROM producto_categoria ORDER BY id")).all()
        migration.upgrade()
        assert connection.execute(text("SELECT id FROM producto_categoria WHERE permite_pedido_especial = true ORDER BY id")).scalars().all() == [1, 2, 3, 4]
        assert connection.execute(text("SELECT id, precio FROM producto_categoria ORDER BY id")).all() == before
        assert connection.execute(text("SELECT es_especial FROM pedido_item")).scalar() == 0
        migration.downgrade()
