from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy import JSON, MetaData
from sqlmodel import Session, create_engine, select

from gastroflow.domain.enums import EstadoPedido, FormaPago, RolUsuario, UnidadVenta
from gastroflow.internal_app import streamlit_app as internal
from gastroflow.internal_app.streamlit_app import (
    _build_production_summary,
    _create_auth_token,
    _date_text,
    _decode_auth_token,
    _filter_delivered_orders,
    _is_pizza_item,
    _normalize_date_range,
    _sync_promotion_products,
    _update_order,
)
from gastroflow.models import (
    Agregado,
    AgregadoCategoria,
    Categoria,
    Cliente,
    Pedido,
    PedidoItem,
    PedidoItemAgregado,
    PedidoPago,
    Producto,
    ProductoCategoria,
    PromocionProducto,
    UsuarioRead,
    ZonaEnvio,
)


def test_internal_dates_use_day_month_year() -> None:
    assert _date_text(date(2026, 10, 14)) == "14-10-2026"


def test_production_summary_groups_products_and_excludes_finished_orders() -> None:
    active_order = {
        "id": 1,
        "fecha_entrega": "14-10-2026",
        "fecha_entrega_raw": date(2026, 10, 14),
        "horario_entrega_raw": time(21, 0),
        "estado": EstadoPedido.PEDIDO.value,
        "items": [
            {"categoria": "Lista para hornear", "producto": "Muzza", "combo": "", "cantidad": 2},
            {"categoria": "Lista para comer", "producto": "Especial", "combo": "Muzza", "cantidad": 1},
        ],
    }
    cancelled_order = {
        **active_order,
        "id": 2,
        "estado": EstadoPedido.CANCELADO.value,
        "items": [{"categoria": "Lista para hornear", "producto": "Muzza", "combo": "", "cantidad": 8}],
    }

    summary = _build_production_summary([active_order, cancelled_order])

    assert summary["14-10-2026"]["order_count"] == 1
    assert summary["14-10-2026"]["categories"]["Lista para hornear"]["Muzza"] == 2
    assert summary["14-10-2026"]["categories"]["Lista para comer"]["Mitad Especial / mitad Muzza"] == 1


def test_auth_token_survives_reload_window_and_rejects_tampering_or_expiry() -> None:
    token = _create_auth_token(7, now=1_000, secret="test-secret")

    assert _decode_auth_token(token, now=1_001, secret="test-secret") == 7
    assert _decode_auth_token(f"{token}x", now=1_001, secret="test-secret") is None
    assert _decode_auth_token(token, now=1_000 + (12 * 60 * 60), secret="test-secret") is None


def test_delivered_order_filters_are_combined() -> None:
    delivered = {
        "id": 1,
        "estado": EstadoPedido.ENTREGADO.value,
        "fecha_entrega_raw": date(2026, 10, 14),
        "cliente": "Ana",
        "zona": "Centro",
        "items": [
            {"categoria": "Pizzas", "producto": "Muzza", "combo": "", "cantidad": 2},
        ],
    }
    another = {
        **delivered,
        "id": 2,
        "fecha_entrega_raw": date(2026, 9, 30),
        "cliente": "Beto",
        "items": [
            {"categoria": "Empanadas", "producto": "Carne", "combo": "", "cantidad": 1},
        ],
    }

    result = _filter_delivered_orders(
        [delivered, another],
        month="2026-10",
        date_from=date(2026, 10, 1),
        date_to=date(2026, 10, 31),
        category="Pizzas",
        product="Muzza",
        client="Ana",
        zone="Centro",
    )

    assert [order["id"] for order in result] == [1]
    assert _normalize_date_range((date(2026, 10, 1), date(2026, 10, 31))) == (
        date(2026, 10, 1),
        date(2026, 10, 31),
    )


def test_delivered_product_filter_keeps_only_matching_items_and_accepts_multiple_values() -> None:
    order = {
        "id": 243,
        "estado": EstadoPedido.ENTREGADO.value,
        "fecha_entrega_raw": date(2026, 10, 15),
        "cliente": "Alejo",
        "zona": "Alderetes",
        "items": [
            {"categoria": "Lista para comer", "producto": "Calabresa", "combo": "", "cantidad": 2},
            {"categoria": "Lista para comer", "producto": "Especial", "combo": "", "cantidad": 1},
            {"categoria": "Pre Pizzas", "producto": "Pre Pizza", "combo": "", "cantidad": 3},
        ],
    }

    result = _filter_delivered_orders(
        [order],
        month=["2026-10", "2026-09"],
        product=["Calabresa", "Muzzarella"],
        client=["Alejo", "Ana"],
        zone=["Alderetes"],
    )

    assert [item["producto"] for item in result[0]["items"]] == ["Calabresa"]
    assert len(order["items"]) == 3  # The cached source data is not mutated.
    assert _is_pizza_item(result[0]["items"][0])
    assert not _is_pizza_item(order["items"][2])


def test_updating_promotion_keeps_existing_product_links_without_duplicates() -> None:
    engine = create_engine("sqlite://")
    PromocionProducto.__table__.create(engine)
    with Session(engine) as session:
        session.add(PromocionProducto(promocion_id=2, producto_id=3))
        session.add(PromocionProducto(promocion_id=2, producto_id=2))
        session.commit()

        _sync_promotion_products(session, 2, [3, 2])
        session.commit()

        links = session.exec(select(PromocionProducto)).all()
        assert sorted(link.producto_id for link in links) == [2, 3]


def test_admin_order_edit_recalculates_item_total_shipping_and_payment(monkeypatch) -> None:
    test_engine = create_engine("sqlite://")
    Categoria.__table__.create(test_engine)
    product_table = Producto.__table__.to_metadata(MetaData())
    product_table.c.fotos.type = JSON()
    product_table.create(test_engine)
    ProductoCategoria.__table__.create(test_engine)
    ZonaEnvio.__table__.create(test_engine)
    Cliente.__table__.create(test_engine)
    Pedido.__table__.create(test_engine)
    PedidoItem.__table__.create(test_engine)
    PedidoPago.__table__.create(test_engine)
    Agregado.__table__.create(test_engine)
    AgregadoCategoria.__table__.create(test_engine)
    PedidoItemAgregado.__table__.create(test_engine)

    with Session(test_engine) as session:
        category = Categoria(id=1, codigo="LISTA_COMER", nombre="Lista para comer")
        product = Producto(id=1, codigo="CALABRESA", nombre="Calabresa", unidad_venta=UnidadVenta.UNIDAD)
        client = Cliente(id=1, nombre_apellido="Nombre anterior")
        zone = ZonaEnvio(id=1, nombre="Centro", costo=Decimal("1500.00"))
        order = Pedido(
            id=1,
            codigo="PED-0104",
            fecha_entrega=date(2026, 10, 20),
            cliente_id=1,
            direccion_delivery="Dirección anterior",
            zona_envio_id=1,
            costo_envio=Decimal("1000.00"),
            forma_pago=FormaPago.EFECTIVO,
            estado=EstadoPedido.ENTREGADO,
            monto_total=Decimal("7000.00"),
        )
        item = PedidoItem(
            id=1,
            pedido_id=1,
            producto_id=1,
            categoria_venta_id=1,
            cantidad=1,
            precio_unitario=Decimal("6000.00"),
            subtotal=Decimal("6000.00"),
        )
        session.add_all([
            category,
            product,
            ProductoCategoria(producto_id=1, categoria_id=1, precio=Decimal("6000.00")),
            client,
            zone,
            order,
            item,
            PedidoPago(pedido_id=1, forma_pago=FormaPago.EFECTIVO, monto=Decimal("7000.00")),
        ])
        session.commit()

    user = UsuarioRead(
        id=1,
        username="ADMIN",
        rol=RolUsuario.ADMIN,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(internal, "engine", test_engine)
    monkeypatch.setattr(internal, "_current_user", lambda: user)

    _update_order(
        order_id=1,
        customer_name="Cliente actualizado",
        customer_phone="381 555-1234",
        delivery_date=date(2026, 10, 21),
        delivery_time=time(21, 30),
        address="Dirección nueva",
        zone_id=1,
        shipping_cost=Decimal("1500.00"),
        payment_method=FormaPago.TRANSFERENCIA,
        cash_amount=Decimal("0.00"),
        transfer_amount=Decimal("0.00"),
        state=EstadoPedido.ENTREGADO,
        observations="Sin cebolla",
        item_rows=[{
            "ID": 1,
            "Producto": "Calabresa",
            "Combinación": "",
            "Categoría": "Lista para comer",
            "Cantidad": 2,
            "Subtotal": 10000,
            "Especial": False,
        }],
    )

    with Session(test_engine) as session:
        updated = session.get(Pedido, 1)
        updated_item = session.get(PedidoItem, 1)
        updated_client = session.get(Cliente, 1)
        payments = session.exec(select(PedidoPago).where(PedidoPago.pedido_id == 1)).all()
        assert updated is not None and updated.monto_total == Decimal("11500.00")
        assert updated.forma_pago == FormaPago.TRANSFERENCIA
        assert updated_item is not None and updated_item.precio_unitario == Decimal("5000.00")
        assert updated_client is not None and updated_client.telefono == "3815551234"
        assert [(payment.forma_pago, payment.monto) for payment in payments] == [
            (FormaPago.TRANSFERENCIA, Decimal("11500.00"))
        ]
