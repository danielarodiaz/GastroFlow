import asyncio
from datetime import date, datetime, time
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine, select

from gastroflow.domain.enums import FormaPago, RolUsuario
from gastroflow.models import Categoria, Cliente, Pedido, PedidoItem, Usuario
from gastroflow.services.auth import AuthService
from gastroflow.services.orders import OrderItemInput, OrderService, PricedItem, PublicOrderInput
from gastroflow.states import public_order_state as app_state
from gastroflow.states.public_order_state import PublicOrderState, _complete_time, _parse_delivery_date


def _state():
    state = PublicOrderState(_reflex_internal_init=True)
    state.cart = [{"producto_id": 1, "cantidad": 1, "categoria_codigo": "LISTA_HORNO"}]
    state.nombre_apellido = "Daniela Diaz"
    state.telefono = "3815551234"
    state.fecha_entrega = "14/10"
    state.horario_entrega = "21"
    return state


def test_delivery_controls_never_query_database(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Delivery buttons must not open database sessions")
    monkeypatch.setattr(app_state, "Session", fail)
    state = _state()
    state.cart_total = "100.00"
    state.zones = [{"id": 1, "nombre": "Centro", "costo": "20", "costo_display": "20,00"}]
    for _ in range(5):
        state.set_delivery_mode("delivery")
        state.select_zone(1)
        assert state.order_total_display == "120,00"
        state.set_delivery_mode("retiro")
        assert state.order_total_display == "100,00"


def test_optional_year_and_minutes():
    year = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).year
    assert _parse_delivery_date("14/10") == date(year, 10, 14)
    assert _parse_delivery_date("14/10/2027") == date(2027, 10, 14)
    assert _complete_time("21") == "21:00"
    assert _complete_time("9") == "09:00"
    assert _complete_time("21:45") == "21:45"
    assert _complete_time("2115") == "21:15"
    assert _complete_time("0915") == "09:15"
    with pytest.raises(ValueError):
        _complete_time("24")
    with pytest.raises(ValueError):
        _parse_delivery_date("31/02")


def test_delivery_time_raw_blur_never_removes_colon_and_allows_deletion():
    state = _state()
    state.set_horario_entrega("2115")
    assert state.horario_entrega == "21:15"
    state.complete_delivery_time("2115")
    assert state.horario_entrega == "21:15"
    state.set_horario_entrega("2115")  # A delayed change event must agree with blur.
    assert state.horario_entrega == "21:15"
    for value in ("21:15", "21:1", "21", "2", ""):
        state.set_horario_entrega(value)
        assert state.horario_entrega == value
        state.complete_delivery_time(value)
        assert state.horario_entrega == value
    state.complete_delivery_time("21")
    assert state.horario_entrega == "21"
    for invalid in ("2415", "2160", "211", "21:1"):
        with pytest.raises(ValueError):
            _complete_time(invalid)


def test_confirmation_accepts_raw_four_digit_time_without_waiting_for_mask(monkeypatch):
    calls = []

    def create(payload):
        calls.append(payload)
        return SimpleNamespace(pedido=SimpleNamespace(codigo="PED-HORARIO", monto_total=Decimal("100")))

    monkeypatch.setattr(app_state, "_create_public_order", create)
    monkeypatch.setattr(PublicOrderState, "_build_whatsapp_url", lambda *args: "https://wa.me/123?text=pedido")
    state = _state()

    async def run():
        _ = [event async for event in state.submit_order({"horario_entrega": "2115"})]

    asyncio.run(run())
    assert state.registered_order_code == "PED-HORARIO"
    assert state.horario_entrega == "21:15"
    assert calls[0].horario_entrega == time(21, 15)


def test_delivery_date_adds_separators_and_raw_blur_does_not_remove_them():
    state = _state()
    for raw, expected in [("1", "1"), ("19", "19"), ("191", "19-1"), ("1910", "19-10"),
                          ("19102", "19-10-2"), ("19102026", "19-10-2026")]:
        state.set_fecha_entrega(raw)
        assert state.fecha_entrega == expected
    state.complete_delivery_date("1910")
    assert state.fecha_entrega == "19-10"
    state.complete_delivery_date("19102026")
    assert state.fecha_entrega == "19-10-2026"
    state.complete_delivery_date("191")
    assert state.fecha_entrega == "19-1"
    state.complete_delivery_date("3113")
    assert state.fecha_entrega == "31-13"
    state.set_fecha_entrega("")
    assert state.fecha_entrega == ""


def test_delivery_date_can_be_erased_and_retyped_without_autocompleting():
    state = _state()
    for value in ("18-10-2026", "18-10-202", "18-10-20", "18-10-2", "18-10",
                  "18-1", "18", "1", ""):
        state.set_fecha_entrega(value)
        assert state.fecha_entrega == value
        state.complete_delivery_date(value)
        assert state.fecha_entrega == value
    for raw, expected in [("1", "1"), ("18", "18"), ("181", "18-1"), ("1810", "18-10")]:
        state.set_fecha_entrega(raw)
        assert state.fecha_entrega == expected
    state.complete_delivery_date("1810")
    assert state.fecha_entrega == "18-10"
    year = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).year
    assert _parse_delivery_date(state.fecha_entrega) == date(year, 10, 18)


def test_delivery_date_accepts_compact_form_values_before_change_event_finishes():
    year = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).year
    assert _parse_delivery_date("1910") == date(year, 10, 19)
    assert _parse_delivery_date("19102026") == date(2026, 10, 19)
    assert _parse_delivery_date("2026-10-19") == date(2026, 10, 19)
    with pytest.raises(ValueError):
        _parse_delivery_date("3113")


def test_business_text_preserves_display_casing_and_media_urls():
    engine = create_engine("sqlite://")
    Categoria.__table__.create(engine)
    with Session(engine) as session:
        category = Categoria(codigo="lista_horno", nombre="Pizzas Clásicas",
            descripcion_publica="Listas para hornear", foto_url="https://example.com/MixedCase/image.jpg")
        session.add(category)
        session.commit()
        session.refresh(category)
        assert category.nombre == "Pizzas Clásicas"
        assert category.codigo == "LISTA_HORNO"
        assert category.descripcion_publica == "Listas para hornear"
        assert category.foto_url == "https://example.com/MixedCase/image.jpg"


def test_confirmation_shows_loading_and_repeated_clicks_save_once(monkeypatch):
    calls = []
    def create(payload):
        calls.append(payload)
        return SimpleNamespace(pedido=SimpleNamespace(codigo="PED-1", monto_total=Decimal("100")))
    monkeypatch.setattr(app_state, "_create_public_order", create)
    state = _state()
    state.nombre_apellido = "Stale input"
    monkeypatch.setattr(PublicOrderState, "_build_whatsapp_url", lambda *args: "https://wa.me/123?text=pedido")

    async def run():
        handler = state.submit_order({"nombre_apellido": "Daniela Diaz"})
        await anext(handler)
        assert state.is_submitting
        assert state.message == ""
        assert not calls
        assert [event async for event in state.submit_order({})] == []
        events = [event async for event in handler]
        assert events
        assert not state.is_submitting
        assert state.registered_order_code == "PED-1"
        assert state.whatsapp_url.startswith("https://wa.me/")
        assert [event async for event in state.submit_order({})] == []
    asyncio.run(run())
    assert len(calls) == 1
    assert calls[0].nombre_apellido == "Daniela Diaz"
    assert calls[0].horario_entrega == time(21, 0)


def test_whatsapp_includes_order_date_and_separate_delivery_date():
    state = _state()
    state.fecha_entrega = "25/12/2026"
    state.cart = []
    message = parse_qs(urlparse(state._build_whatsapp_url("PED-1", Decimal("100"))).query)["text"][0]
    assert "Fecha del pedido: " in message
    assert "Fecha de entrega: 25/12/2026" in message
    assert "Horario ideal de entrega: 21hs" in message


def test_failed_confirmation_can_retry_with_same_token(monkeypatch):
    tokens = []
    def fail(payload):
        tokens.append(payload.submission_token)
        raise RuntimeError("connection interrupted")
    monkeypatch.setattr(app_state, "_create_public_order", fail)
    state = _state()
    async def run():
        for _ in range(2):
            _ = [event async for event in state.submit_order({})]
            assert not state.is_submitting
            assert not state.registered_order_code
    asyncio.run(run())
    assert len(tokens) == 2 and tokens[0] == tokens[1] and tokens[0]


def test_database_retry_returns_existing_order_and_preserves_display_text(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool)
    for table in (Cliente.__table__, Pedido.__table__, PedidoItem.__table__, Usuario.__table__):
        table.create(engine)
    monkeypatch.setattr("gastroflow.services.orders.next_business_code", lambda *args: "PED-1")
    item = OrderItemInput(producto_id=1, cantidad=1)
    monkeypatch.setattr(OrderService, "_price_items", lambda *args: [PricedItem(
        item=item, precio_unitario=Decimal("100"), categoria_venta_id=1,
        subtotal=Decimal("100"), requiere_confirmacion=False,
    )])
    payload = PublicOrderInput(nombre_apellido="Daniela Díaz", telefono="3815551234",
        fecha_entrega=date(2026, 10, 14), horario_entrega=time(21, 0), direccion_delivery="San Martín 25",
        forma_pago=FormaPago.EFECTIVO, items=[item], observaciones="Sin cebolla",
        submission_token="test-checkout-token")
    with Session(engine) as session:
        result = OrderService(session).create_public_order(payload)
    with Session(engine) as session:
        duplicate = OrderService(session).create_public_order(payload)
        assert duplicate.pedido.id == result.pedido.id
        assert len(session.exec(select(Pedido)).all()) == 1
        assert len(session.exec(select(PedidoItem)).all()) == 1
        customer = session.exec(select(Cliente)).one()
        assert customer.nombre_apellido == "Daniela Díaz"
        assert duplicate.pedido.direccion_delivery == "San Martín 25"
        assert duplicate.pedido.horario_entrega == time(21, 0)
        assert duplicate.pedido.observaciones == "Sin cebolla"
        customer.nombre_apellido = "daniela diaz"
        session.commit()
        session.refresh(customer)
        assert customer.nombre_apellido == "daniela diaz"
        user = AuthService(session).create_user("Administrador", "SecretCase123", RolUsuario.ADMIN)
        assert user.username == "ADMINISTRADOR"
        assert AuthService(session).authenticate("aDmInIsTrAdOr", "SecretCase123").id == user.id


def test_same_normalized_phone_reuses_customer_and_updates_display_name():
    engine = create_engine("sqlite://")
    Cliente.__table__.create(engine)
    with Session(engine) as session:
        service = OrderService(session)
        first = service._upsert_cliente("Daniela Díaz", "381 555-1234")
        first_id = first.id
        second = service._upsert_cliente("Daniela Diaz", "+54 9 381 555-1234")
        session.commit()
        assert second.id == first_id
        assert second.telefono == "3815551234"
        assert second.nombre_apellido == "Daniela Diaz"


def test_confirmation_rejects_invalid_phone_before_saving(monkeypatch):
    calls = []
    monkeypatch.setattr(app_state, "_create_public_order", lambda payload: calls.append(payload))
    state = _state()
    state.telefono = "381543860"

    async def run():
        _ = [event async for event in state.submit_order({})]

    asyncio.run(run())
    assert not calls
    assert "10 dígitos" in state.message


@pytest.mark.parametrize("event_units", [0, 1, 9, 10, 11])
def test_confirmation_enforces_events_minimum_independently_of_other_categories(monkeypatch, event_units):
    calls = []

    def create(payload):
        calls.append(payload)
        return SimpleNamespace(pedido=SimpleNamespace(codigo="PED-EVENTOS", monto_total=Decimal("100")))

    monkeypatch.setattr(app_state, "_create_public_order", create)
    state = _state()
    state.cart[0]["cantidad"] = 20
    state.cart[0]["categoria"] = "Lista para hornear"
    state.cart[0]["nombre"] = "Muzzarella"
    state.cart[0]["subtotal_display"] = "100,00"
    if event_units:
        # The threshold is across products, not per product.
        for product_id, quantity in [(1, (event_units + 1) // 2), (2, event_units // 2)]:
            if quantity:
                state.cart.append({"producto_id": product_id, "cantidad": quantity,
                    "categoria_codigo": "EVENTOS", "categoria": "Eventos", "nombre": "Pizza",
                    "subtotal_display": "100,00"})

    async def run():
        blocked = 0 < event_units < 10
        assert bool(state.events_minimum_message) == blocked
        _ = [event async for event in state.submit_order({})]
        assert not state.is_submitting
        if blocked:
            assert not calls
            assert not state.registered_order_code
            assert state.message == "La cantidad minima de compra para Eventos debe ser de 10 unidades"
        else:
            assert len(calls) == 1
            assert state.registered_order_code == "PED-EVENTOS"

    asyncio.run(run())


def test_events_minimum_message_updates_after_removing_events():
    state = _state()
    state.cart = [{"producto_id": 1, "cantidad": 1, "categoria_codigo": "EVENTOS"}]
    assert state.events_minimum_message
    state.cart = []
    assert not state.events_minimum_message
