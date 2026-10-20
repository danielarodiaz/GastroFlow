from datetime import date, time

from sqlmodel import Session, create_engine, select

from gastroflow.domain.enums import EstadoPedido
from gastroflow.internal_app.streamlit_app import (
    _build_production_summary,
    _create_auth_token,
    _date_text,
    _decode_auth_token,
    _filter_delivered_orders,
    _normalize_date_range,
    _sync_promotion_products,
)
from gastroflow.models import PromocionProducto


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
