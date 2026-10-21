from datetime import date
from decimal import Decimal

import pytest
from sqlmodel import select

from gastroflow.domain.enums import FormaPago
from gastroflow.domain.errors import ValidationError
from gastroflow.models import (
    Agregado,
    AgregadoCategoria,
    Cliente,
    Pedido,
    PedidoItem,
    PedidoItemAgregado,
    PedidoPago,
    Producto,
    ProductoCategoria,
)
from gastroflow.services.orders import (
    OrderAddonInput,
    OrderItemInput,
    OrderPaymentInput,
    OrderService,
    PublicOrderInput,
)
from tests.test_orders import _catalog, _session


@pytest.fixture
def order_database(monkeypatch):
    with _session() as session:
        category_ids = _catalog(session)
        for model in (
            Agregado,
            AgregadoCategoria,
            Cliente,
            Pedido,
            PedidoItem,
            PedidoItemAgregado,
            PedidoPago,
        ):
            model.__table__.create(session.get_bind())
        egg = Agregado(codigo="HUEVO", nombre="Huevo", precio=Decimal("1000"))
        session.add(egg)
        session.flush()
        product = session.exec(select(Producto).where(Producto.nombre == "Muzzarella")).one()
        session.add_all([
            AgregadoCategoria(
                agregado_id=egg.id,
                categoria_id=category_ids["lista_comer"],
            ),
            ProductoCategoria(
                producto_id=product.id,
                categoria_id=category_ids["lista_comer"],
                precio=Decimal("6500"),
            ),
        ])
        session.commit()
        monkeypatch.setattr(
            "gastroflow.services.orders.next_business_code",
            lambda *args: "PED-0001",
        )
        yield session, product, egg


def test_split_payment_and_addon_are_snapshotted(order_database):
    session, product, egg = order_database
    payload = PublicOrderInput(
        nombre_apellido="Cliente Prueba",
        telefono="3815551234",
        fecha_entrega=date(2026, 10, 21),
        direccion_delivery="Retiro en el local",
        forma_pago=FormaPago.MIXTO,
        items=[OrderItemInput(
            producto_id=product.id,
            cantidad=1,
            contexto_origen="LISTA_COMER",
            agregados=(OrderAddonInput(agregado_id=egg.id, cantidad=2),),
        )],
        pagos=(
            OrderPaymentInput(FormaPago.EFECTIVO, Decimal("2500")),
            OrderPaymentInput(FormaPago.TRANSFERENCIA, Decimal("6000")),
        ),
    )

    result = OrderService(session).create_public_order(payload)

    assert result.pedido.forma_pago == FormaPago.MIXTO
    assert result.pedido.monto_total == Decimal("8500")
    assert {
        (payment.forma_pago, payment.monto)
        for payment in session.exec(select(PedidoPago)).all()
    } == {
        (FormaPago.EFECTIVO, Decimal("2500")),
        (FormaPago.TRANSFERENCIA, Decimal("6000")),
    }
    saved_addon = session.exec(select(PedidoItemAgregado)).one()
    assert saved_addon.agregado_nombre == "Huevo"
    assert saved_addon.cantidad == 2
    assert saved_addon.precio_unitario == Decimal("1000")
    assert saved_addon.subtotal == Decimal("2000")


def test_split_payment_must_match_exact_order_total(order_database):
    session, product, _ = order_database
    payload = PublicOrderInput(
        nombre_apellido="Cliente Prueba",
        telefono="3815551234",
        fecha_entrega=date(2026, 10, 21),
        direccion_delivery="Retiro en el local",
        forma_pago=FormaPago.MIXTO,
        items=[OrderItemInput(
            producto_id=product.id,
            cantidad=1,
            contexto_origen="LISTA_COMER",
        )],
        pagos=(
            OrderPaymentInput(FormaPago.EFECTIVO, Decimal("1000")),
            OrderPaymentInput(FormaPago.TRANSFERENCIA, Decimal("1000")),
        ),
    )

    with pytest.raises(ValidationError, match="coincidir con el total"):
        OrderService(session).create_public_order(payload)


def test_addon_is_rejected_outside_its_enabled_category(order_database):
    session, product, egg = order_database

    with pytest.raises(ValidationError, match="no está disponible"):
        OrderService(session)._price_items([OrderItemInput(
            producto_id=product.id,
            cantidad=1,
            contexto_origen="LISTA_HORNO",
            agregados=(OrderAddonInput(agregado_id=egg.id),),
        )])
