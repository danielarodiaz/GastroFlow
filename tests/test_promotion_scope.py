from decimal import Decimal
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlmodel import select

from gastroflow.domain.errors import ValidationError
from gastroflow.domain.enums import TipoPromocion
from gastroflow.models import Categoria, ProductoCategoria, Promocion, PromocionCategoria, PromocionItem, PromocionProducto
from gastroflow.services.orders import OrderItemInput, OrderService
from gastroflow.services.promotions import configure_promotion
from tests.test_orders import _catalog, _session


@pytest.fixture
def catalog():
    with _session() as session:
        ids = _catalog(session)
        oven_price = session.exec(select(ProductoCategoria).where(
            ProductoCategoria.producto_id == ids["muzza"], ProductoCategoria.categoria_id == ids["lista_horno"],
        )).one()
        oven_price.precio = Decimal("6500")
        session.add(oven_price)
        prep = Categoria(codigo="PRE_PIZZAS", nombre="Pre Pizzas")
        session.add(prep)
        session.flush()
        ids["pre_pizzas"] = prep.id
        session.add_all([
            ProductoCategoria(producto_id=ids["muzza"], categoria_id=ids["lista_comer"], precio=Decimal("9500")),
            ProductoCategoria(producto_id=ids["prepizza"], categoria_id=prep.id, precio=Decimal("1300")),
        ])
        session.commit()
        yield session, ids


def _promo(session, ids, *, categories=None, package=False, total=None, code="PROMO_HORNO_2"):
    promo = Promocion(codigo=code, nombre=code, tipo=TipoPromocion.PRECIO_UNITARIO_POR_CANTIDAD,
        cantidad_minima=2, precio_unitario_promocional=Decimal("6000"),
        precio_total_promocional=Decimal(total) if total else None)
    session.add(promo)
    session.flush()
    product_ids = [ids["muzza"], ids["prepizza"]] if package else [ids["muzza"]]
    session.add_all([PromocionProducto(promocion_id=promo.id, producto_id=product) for product in product_ids])
    if categories is not None:
        configure_promotion(session, promo, categories, product_ids, [
            (ids["muzza"], ids["lista_horno"], 2), (ids["prepizza"], ids["pre_pizzas"], 3),
        ] if package else [])
    session.commit()
    return promo


def test_promotion_never_leaks_to_other_category_of_same_product(catalog):
    session, ids = catalog
    _promo(session, ids, categories=[ids["lista_horno"]])
    priced = OrderService(session)._price_items([
        OrderItemInput(ids["muzza"], 2, contexto_origen="LISTA_HORNO"),
        OrderItemInput(ids["muzza"], 2, contexto_origen="LISTA_COMER"),
    ])
    assert [line.subtotal for line in priced] == [Decimal("12000"), Decimal("19000")]


def test_unassigned_promotion_is_never_treated_as_global(catalog):
    session, ids = catalog
    _promo(session, ids)
    priced = OrderService(session)._price_items([OrderItemInput(ids["muzza"], 2)])
    assert priced[0].subtotal == Decimal("13000")


def test_multiple_categories_are_explicit_and_quantities_do_not_cross_categories(catalog):
    session, ids = catalog
    _promo(session, ids, categories=[ids["lista_horno"], ids["lista_comer"]])
    service = OrderService(session)
    assert [line.subtotal for line in service._price_items([
        OrderItemInput(ids["muzza"], 1, contexto_origen="LISTA_HORNO"),
        OrderItemInput(ids["muzza"], 1, contexto_origen="LISTA_COMER"),
    ])] == [Decimal("6500"), Decimal("9500")]
    assert [line.subtotal for line in service._price_items([
        OrderItemInput(ids["muzza"], 3, contexto_origen="LISTA_HORNO"),
        OrderItemInput(ids["muzza"], 3, contexto_origen="LISTA_COMER"),
    ])] == [Decimal("18500"), Decimal("21500")]


@pytest.mark.parametrize("muzza,prepizza,total", [
    (2, 3, "15000"), (3, 4, "22800"), (4, 6, "30000"), (5, 7, "37800"),
    (1, 4, "11700"), (3, 2, "22100"), (0, 3, "3900"),
])
def test_cross_category_package_requires_exact_composition_and_keeps_extras_at_base(catalog, muzza, prepizza, total):
    session, ids = catalog
    _promo(session, ids, categories=[ids["lista_horno"], ids["pre_pizzas"]], package=True, total="15000")
    items = []
    if muzza:
        items.append(OrderItemInput(ids["muzza"], muzza, contexto_origen="LISTA_HORNO"))
    if prepizza:
        items.append(OrderItemInput(ids["prepizza"], prepizza, contexto_origen="PRE_PIZZAS"))
    priced = OrderService(session)._price_items(items)
    assert sum(line.subtotal for line in priced) == Decimal(total)
    if muzza >= 2 and prepizza >= 3:
        assert all(line.promocion_nombre == "PROMO_HORNO_2" for line in priced)
    else:
        assert not any(line.promocion_nombre for line in priced)


def test_package_does_not_match_wrong_category_or_wholesale(catalog):
    session, ids = catalog
    _promo(session, ids, categories=[ids["lista_horno"], ids["pre_pizzas"]], package=True, total="15000")
    priced = OrderService(session)._price_items([
        OrderItemInput(ids["muzza"], 2, contexto_origen="LISTA_COMER"),
        OrderItemInput(ids["prepizza"], 3, contexto_origen="PRE_PIZZAS"),
    ])
    assert sum(line.subtotal for line in priced) == Decimal("22900")
    priced = OrderService(session)._price_items([
        OrderItemInput(ids["muzza"], 10, contexto_origen="LISTA_HORNO"),
        OrderItemInput(ids["prepizza"], 3, contexto_origen="PRE_PIZZAS"),
    ])
    assert sum(line.subtotal for line in priced) == Decimal("48900")
    assert not any(line.promocion_nombre for line in priced)


@pytest.mark.parametrize("package_total,expected,uses_package", [("15000", "15000", True), ("16000", "15900", False)])
def test_package_replaces_other_promos_only_if_total_is_lower(catalog, package_total, expected, uses_package):
    session, ids = catalog
    _promo(session, ids, categories=[ids["lista_horno"]], code="SIMPLE")
    _promo(session, ids, categories=[ids["lista_horno"], ids["pre_pizzas"]], package=True, total=package_total)
    priced = OrderService(session)._price_items([
        OrderItemInput(ids["muzza"], 2, contexto_origen="LISTA_HORNO"),
        OrderItemInput(ids["prepizza"], 3, contexto_origen="PRE_PIZZAS"),
    ])
    assert sum(line.subtotal for line in priced) == Decimal(expected)
    assert bool(priced[0].promocion_nombre) == uses_package


def test_editing_scope_replaces_old_categories_and_validates_product_membership(catalog):
    session, ids = catalog
    promo = _promo(session, ids, categories=[ids["lista_horno"]])
    configure_promotion(session, promo, [ids["lista_comer"]], [ids["muzza"]], [])
    session.commit()
    assert [link.categoria_id for link in session.exec(select(PromocionCategoria)).all()] == [ids["lista_comer"]]
    with pytest.raises(ValidationError, match="categoría"):
        configure_promotion(session, promo, [], [ids["muzza"]], [])
    with pytest.raises(ValidationError, match="pertenecer"):
        configure_promotion(session, promo, [ids["pre_pizzas"]], [ids["muzza"]], [])


def test_package_configuration_requires_total_and_complete_valid_quantities(catalog):
    session, ids = catalog
    promo = _promo(session, ids, categories=[ids["lista_horno"]])
    with pytest.raises(ValidationError, match="Precio total"):
        configure_promotion(session, promo, [ids["lista_horno"]], [ids["muzza"]], [(ids["muzza"], ids["lista_horno"], 2)])
    promo.precio_total_promocional = Decimal("15000")
    with pytest.raises(ValidationError, match="entera"):
        configure_promotion(session, promo, [ids["lista_horno"]], [ids["muzza"]], [(ids["muzza"], ids["lista_horno"], 0)])


def test_migration_backfills_known_scope_and_leaves_ambiguous_promotions_unassigned(catalog, monkeypatch):
    session, ids = catalog
    known = _promo(session, ids)
    ambiguous = _promo(session, ids, code="PROMO_SIN_CATEGORIA")
    spec = importlib.util.spec_from_file_location("promotion_migration", Path("alembic/versions/0009_promotion_categories.py"))
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    known_id, ambiguous_id = known.id, ambiguous.id
    session.close()
    engine = session.get_bind()
    PromocionItem.__table__.drop(engine)
    PromocionCategoria.__table__.drop(engine)
    with engine.begin() as connection:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        scopes = connection.execute(select(PromocionCategoria.promocion_id, PromocionCategoria.categoria_id)).all()
        assert scopes == [(known_id, ids["lista_horno"])]
        assert ambiguous_id != known_id
        migration.downgrade()


def test_streamlit_editor_selects_categories_and_saves_package_composition(catalog, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from gastroflow.internal_app import streamlit_app

    session, ids = catalog
    monkeypatch.setattr(streamlit_app, "engine", session.get_bind())
    monkeypatch.setattr(streamlit_app, "_is_admin", lambda: True)

    def page():
        from gastroflow.internal_app.streamlit_app import _render_promotions
        _render_promotions()

    app = AppTest.from_function(page, default_timeout=10).run()
    assert not app.exception
    assert app.multiselect[0].label == "Categorías de la promo"
    assert app.multiselect[1].label == "Productos elegibles"
    assert not app.multiselect[1].options
    app.multiselect[0].set_value([ids["lista_horno"], ids["pre_pizzas"]]).run()
    app.multiselect[1].set_value([ids["muzza"], ids["prepizza"]]).run()
    app.checkbox[0].check().run()
    assert not app.exception
    units = [widget for widget in app.number_input if "unidades por paquete" in widget.label]
    assert len(units) == 2
    units[0].set_value(2)
    units[1].set_value(3)
    app.text_input[0].set_value("PROMO_PAQUETE")
    app.text_input[1].set_value("2 muzzas y 3 prepizzas")
    next(widget for widget in app.number_input if widget.label == "Precio total del paquete").set_value(15000.0)
    next(widget for widget in app.button if widget.label == "Guardar promo").click().run()
    assert not app.exception
    assert not app.error
    session.expire_all()
    promo = session.exec(select(Promocion)).one()
    assert promo.precio_total_promocional == Decimal("15000")
    assert promo.cantidad_minima == 5
    assert {(item.producto_id, item.categoria_id, item.cantidad) for item in session.exec(select(PromocionItem)).all()} == {
        (ids["muzza"], ids["lista_horno"], 2), (ids["prepizza"], ids["pre_pizzas"], 3),
    }
    assert {link.categoria_id for link in session.exec(select(PromocionCategoria)).all()} == {
        ids["lista_horno"], ids["pre_pizzas"],
    }
