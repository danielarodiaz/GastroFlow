from datetime import date, time

from sqlmodel import Session, create_engine, select

from gastroflow.domain.enums import EstadoPedido
from gastroflow.internal_app.streamlit_app import (
    _build_production_summary,
    _date_text,
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
