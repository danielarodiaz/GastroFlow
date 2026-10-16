import asyncio
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import JSON, MetaData, event
from sqlmodel import Session, create_engine

from gastroflow.domain.enums import UnidadVenta
from gastroflow.models import Categoria, Producto, ProductoCategoria, ZonaEnvio
from gastroflow.services import public_catalog
from gastroflow.services.public_catalog import PublicReadCache, brand_cache, catalog_cache
from gastroflow.states import public_order_state as app_state
from gastroflow.states.public_order_state import PublicOrderState


@pytest.fixture
def contextual_catalog(monkeypatch):
    categories = [
        Categoria(id=1, codigo="LISTA_HORNO", nombre="Lista para hornear"),
        Categoria(id=2, codigo="LISTA_COMER", nombre="Lista para comer"),
        Categoria(id=3, codigo="EVENTOS", nombre="Eventos"),
    ]
    products = [
        Producto(id=index, codigo=f"P{index}", nombre=name, unidad_venta=UnidadVenta.UNIDAD)
        for index, name in enumerate(("Muzzarella", "Especial", "Calabresa"), 1)
    ]
    # Reproduce the reported first matches: muzzarella in COMER, the others in HORNO.
    relations = [
        ProductoCategoria(
            id=category.id * 10 + product.id,
            producto_id=product.id,
            categoria_id=category.id,
            precio=Decimal(category.id * 1000 + product.id),
            descripcion_publica=f"{product.nombre} / {category.nombre}",
            foto_url=f"https://example.com/{category.codigo}/{product.id}.jpg",
            orden=0 if category.id == (2 if product.id == 1 else 1) else 1,
        )
        for category in categories for product in products
    ]
    catalog_cache.invalidate()
    brand_cache.invalidate()
    monkeypatch.setattr(app_state, "_public_catalog_rows", lambda: (categories, products, relations, []))
    monkeypatch.setattr(app_state, "_read_brand_logo_url", lambda: "")

    async def get_brand(self, cls):
        return SimpleNamespace(logo_url="")

    monkeypatch.setattr(PublicOrderState, "get_state", get_brand)
    state = PublicOrderState(_reflex_internal_init=True)

    async def load():
        _ = [update async for update in state.load_catalog()]

    asyncio.run(load())
    try:
        yield state
    finally:
        catalog_cache.invalidate()
        brand_cache.invalidate()


@pytest.mark.parametrize("category_id", [1, 2, 3])
@pytest.mark.parametrize("product_id", [1, 2, 3])
def test_product_detail_preserves_category_price_description_and_photo(contextual_catalog, category_id, product_id):
    state = contextual_catalog
    # Navigate away and back too: selection must never depend on the previous detail.
    for current_category in [3, 2, 1, category_id]:
        state.show_categories()
        state.show_category(current_category)
        card = next(item for item in state.visible_products if item["id"] == product_id)
        state.detail_quantity = "7"
        state.open_product(card["id"], card["categoria_id"])
        assert state.view == "detail"
        assert state.detail_quantity == "1"
        assert state.selected_product == card
        assert state.selected_product["categoria_id"] == current_category
        assert Decimal(state.selected_product["precio"]) == Decimal(current_category * 1000 + product_id)
        assert state.selected_product["categoria"] in state.selected_product["descripcion"]
        assert state.selected_product["categoria_codigo"] in state.selected_product["foto"]
        state.show_category(state.selected_category_id)
        assert state.view == "products"
        assert card in state.visible_products


def test_invalid_or_stale_product_click_never_opens_another_category(contextual_catalog):
    state = contextual_catalog
    state.show_category(1)
    state.open_product(1, 1)
    state.show_category(3)
    state.open_product(1, 1)  # An old event arriving after changing category.
    assert state.view == "products"
    assert not state.selected_product
    state.open_product(999, 3)
    assert state.view == "products"
    assert not state.selected_product
    assert state.message


def test_product_missing_from_current_category_has_no_cross_category_fallback(contextual_catalog):
    state = contextual_catalog
    state.products = [
        item for item in state.products
        if not (item["id"] == 1 and item["categoria_id"] == 3)
    ]
    state.show_category(3)
    state.open_product(2, 3)
    state.open_product(1, 3)
    assert state.view == "products"
    assert not state.selected_product
    assert state.message


def test_cart_keeps_categories_separate_through_pricing_removal_and_checkout(contextual_catalog, monkeypatch):
    state = contextual_catalog
    pricing_inputs = []
    orders = []

    def price(inputs):
        pricing_inputs.append(inputs)
        category_ids = {"LISTA_HORNO": 1, "LISTA_COMER": 2, "EVENTOS": 3}
        return [SimpleNamespace(
            precio_unitario=Decimal(category_ids[item.contexto_origen] * 1000 + item.producto_id),
            subtotal=Decimal(category_ids[item.contexto_origen] * 1000 + item.producto_id) * item.cantidad,
        ) for item in inputs]

    def create(payload):
        orders.append(payload)
        return SimpleNamespace(pedido=SimpleNamespace(codigo="PED-REGRESSION", monto_total=Decimal("5003")))

    monkeypatch.setattr(app_state, "_price_public_cart", price)
    monkeypatch.setattr(app_state, "_create_public_order", create)

    async def run():
        for category_id in [1, 2, 3, 1]:
            state.show_category(category_id)
            state.open_product(1, category_id)
            _ = [event async for event in state.add_selected_to_cart()]
        assert [(item["categoria_codigo"], item["cantidad"]) for item in state.cart] == [
            ("LISTA_HORNO", 2), ("LISTA_COMER", 1), ("EVENTOS", 1),
        ]
        assert state.cart_total == "7004.00"
        assert [item.contexto_origen for item in pricing_inputs[-1]] == ["LISTA_HORNO", "LISTA_COMER", "EVENTOS"]
        _ = [event async for event in state.remove_cart_item(1, "LISTA_COMER")]
        assert [item["categoria_codigo"] for item in state.cart] == ["LISTA_HORNO", "EVENTOS"]
        assert state.cart_total == "5003.00"
        state.nombre_apellido = "Cliente Prueba"
        state.telefono = "3815551234"
        state.fecha_entrega = "25/12/2026"
        state.horario_entrega = "21"
        _ = [event async for event in state.submit_order({})]
        assert state.registered_order_code == "PED-REGRESSION"

    asyncio.run(run())
    assert len(orders) == 1
    assert [(item.producto_id, item.contexto_origen, item.cantidad) for item in orders[0].items] == [
        (1, "LISTA_HORNO", 2), (1, "EVENTOS", 1),
    ]


def test_catalog_cache_shares_reads_and_expires(monkeypatch):
    now = [1.0]
    monkeypatch.setattr(public_catalog, "monotonic", lambda: now[0])
    cache = PublicReadCache(ttl_seconds=30)
    calls = []
    def load():
        calls.append(1)
        return len(calls)
    with ThreadPoolExecutor(max_workers=8) as workers:
        assert list(workers.map(lambda _: cache.get(load), range(8))) == [1] * 8
    now[0] = 32.0
    assert cache.get(load) == 2
    cache.invalidate()
    assert cache.get(load) == 3


def test_failed_catalog_read_can_be_retried():
    cache = PublicReadCache()
    def fail():
        raise RuntimeError("database unavailable")
    with pytest.raises(RuntimeError):
        cache.get(fail)
    assert cache.get(lambda: "recovered") == "recovered"


def test_catalog_join_uses_two_reads_and_filters_private_products(monkeypatch):
    engine = create_engine("sqlite://")
    Categoria.__table__.create(engine)
    # Test-only SQLite representation of PostgreSQL's JSONB photo list.
    product_table = Producto.__table__.to_metadata(MetaData())
    product_table.c.fotos.type = JSON()
    product_table.create(engine)
    ProductoCategoria.__table__.create(engine)
    ZonaEnvio.__table__.create(engine)
    with Session(engine) as session:
        session.add_all([
            Categoria(id=1, codigo="PUBLIC", nombre="Público"),
            Categoria(id=2, codigo="EMPTY", nombre="Sin productos"),
            Categoria(id=3, codigo="PRIVATE", nombre="Privado", visible_cliente=False),
            Producto(id=1, codigo="VISIBLE", nombre="Pizza", unidad_venta=UnidadVenta.UNIDAD),
            Producto(id=2, codigo="INACTIVE", nombre="Inactiva", unidad_venta=UnidadVenta.UNIDAD, activo=False),
            Producto(id=3, codigo="HIDDEN", nombre="Oculta", unidad_venta=UnidadVenta.UNIDAD),
            ProductoCategoria(producto_id=1, categoria_id=1, precio=100),
            ProductoCategoria(producto_id=2, categoria_id=1, precio=100),
            ProductoCategoria(producto_id=3, categoria_id=1, precio=100, visible=False),
            ProductoCategoria(producto_id=1, categoria_id=3, precio=100),
            ZonaEnvio(nombre="Centro", costo=20),
        ])
        session.commit()
    reads = []
    event.listen(engine, "before_cursor_execute", lambda conn, cursor, statement, *args: reads.append(statement))
    monkeypatch.setattr(app_state, "engine", engine)
    categories, products, relations, zones = app_state._public_catalog_rows()
    assert len(reads) == 2
    assert {category.id for category in categories} == {1, 2}
    assert [product.id for product in products] == [1]
    assert [(relation.producto_id, relation.categoria_id) for relation in relations] == [(1, 1)]
    assert len(zones) == 1


def test_catalog_load_failure_exits_spinner_and_retry_recovers(monkeypatch):
    catalog_cache.invalidate()
    brand_cache.invalidate()
    attempts = []
    def load_rows():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("connection interrupted")
        return [Categoria(id=1, codigo="PUBLIC", nombre="Público")], [], [], []
    monkeypatch.setattr(app_state, "_public_catalog_rows", load_rows)
    monkeypatch.setattr(app_state, "_read_brand_logo_url", lambda: "")
    brand = type("Brand", (), {"logo_url": ""})()
    async def get_brand(self, cls):
        return brand
    monkeypatch.setattr(PublicOrderState, "get_state", get_brand)
    state = PublicOrderState(_reflex_internal_init=True)
    async def run():
        _ = [update async for update in state.load_catalog()]
        assert not state.is_loading_catalog
        assert state.catalog_error
        _ = [update async for update in state.load_catalog()]
        assert not state.is_loading_catalog
        assert not state.catalog_error
        assert state.categories[0]["id"] == 1
    try:
        asyncio.run(run())
    finally:
        catalog_cache.invalidate()
        brand_cache.invalidate()
