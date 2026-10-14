import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import JSON, MetaData, event
from sqlmodel import Session, create_engine

from gastroflow.domain.enums import UnidadVenta
from gastroflow.models import Categoria, Producto, ProductoCategoria, ZonaEnvio
from gastroflow.services import public_catalog
from gastroflow.services.public_catalog import PublicReadCache, brand_cache, catalog_cache
from gastroflow.states import app_state
from gastroflow.states.app_state import PublicOrderState


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
