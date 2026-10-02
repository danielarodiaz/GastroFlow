from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlmodel import Session, select

from gastroflow.data.database import engine
from gastroflow.domain.enums import FormaPago, ReglaPrecioCombo, TipoPromocion, UnidadVenta
from gastroflow.models import (
    Categoria,
    ComboRegla,
    Producto,
    ProductoCategoria,
    Promocion,
    PromocionProducto,
    ZonaEnvio,
)
from gastroflow.services import OrderItemInput, OrderService, PublicOrderInput


def first_or_create(session: Session, model: type, lookup: dict, values: dict):
    statement = select(model)
    for field, value in lookup.items():
        statement = statement.where(getattr(model, field) == value)
    instance = session.exec(statement).first()
    if instance is not None:
        return instance

    instance = model(**lookup, **values)
    session.add(instance)
    session.flush()
    return instance


def main() -> None:
    with Session(engine) as session:
        categoria = first_or_create(
            session,
            Categoria,
            {"codigo": "LISTA_HORNO"},
            {"nombre": "Smoke lista para hornear"},
        )
        mayorista = first_or_create(
            session,
            Categoria,
            {"codigo": "MAYORISTA"},
            {
                "nombre": "Smoke mayorista",
                "visible_cliente": False,
                "es_automatica": True,
                "cantidad_minima_total": 10,
                "prioridad": 100,
            },
        )
        muzza = first_or_create(
            session,
            Producto,
            {"codigo": "SMOKE_MUZZA"},
            {
                "nombre": "Smoke Muzzarella",
                "unidad_venta": UnidadVenta.PIEZA,
            },
        )
        especial = first_or_create(
            session,
            Producto,
            {"codigo": "SMOKE_ESPECIAL"},
            {
                "nombre": "Smoke Especial",
                "unidad_venta": UnidadVenta.PIEZA,
            },
        )
        for product, standard_price, wholesale_price in (
            (muzza, Decimal("5500.00"), Decimal("4500.00")),
            (especial, Decimal("7000.00"), Decimal("6000.00")),
        ):
            first_or_create(
                session,
                ProductoCategoria,
                {"producto_id": product.id, "categoria_id": categoria.id},
                {"precio": standard_price},
            )
            first_or_create(
                session,
                ProductoCategoria,
                {"producto_id": product.id, "categoria_id": mayorista.id},
                {"precio": wholesale_price},
            )
        promo = first_or_create(
            session,
            Promocion,
            {"codigo": "SMOKE_PROMO_MUZZA_2"},
            {
                "nombre": "Smoke Muzzarella x2",
                "tipo": TipoPromocion.PRECIO_UNITARIO_POR_CANTIDAD,
                "cantidad_minima": 2,
                "precio_unitario_promocional": Decimal("5000.00"),
                "activa": True,
            },
        )
        first_or_create(
            session,
            PromocionProducto,
            {"promocion_id": promo.id, "producto_id": muzza.id},
            {},
        )
        first_or_create(
            session,
            ComboRegla,
            {"producto_a_id": muzza.id, "producto_b_id": especial.id},
            {
                "requiere_confirmacion": False,
                "regla_precio": ReglaPrecioCombo.PROMEDIO,
                "precio_fijo_combo": None,
            },
        )
        zona = first_or_create(
            session,
            ZonaEnvio,
            {"nombre": "Smoke zona"},
            {"costo": Decimal("1000.00")},
        )
        session.commit()

        order = OrderService(session).create_public_order(
            PublicOrderInput(
                nombre_apellido="Cliente Smoke",
                telefono="+54 381 555-0000",
                fecha_entrega=date.today(),
                direccion_delivery="Retiro en el local",
                zona_envio_id=zona.id,
                forma_pago=FormaPago.EFECTIVO,
                items=[
                    OrderItemInput(producto_id=muzza.id, cantidad=5),
                    OrderItemInput(producto_id=especial.id, cantidad=5),
                ],
            )
        )
        combo_order = OrderService(session).create_public_order(
            PublicOrderInput(
                nombre_apellido="Cliente Combo Smoke",
                telefono="+54 381 555-0001",
                fecha_entrega=date.today(),
                direccion_delivery="Retiro en el local",
                forma_pago=FormaPago.TRANSFERENCIA,
                items=[
                    OrderItemInput(
                        producto_id=muzza.id,
                        producto_combo_id=especial.id,
                        cantidad=1,
                    )
                ],
            )
        )

        print(order.pedido.codigo, order.pedido.monto_total, order.pedido.estado.value)
        print(combo_order.pedido.codigo, combo_order.pedido.monto_total, combo_order.pedido.estado.value)


if __name__ == "__main__":
    main()
