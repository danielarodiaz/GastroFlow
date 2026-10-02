from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

from gastroflow.domain.enums import EstadoPedido, ReglaPrecioCombo, UnidadVenta
from gastroflow.domain.errors import ValidationError
from gastroflow.domain.order_state import assert_valid_order_transition
from gastroflow.models import Categoria, ComboRegla, Producto, ProductoCategoria
from gastroflow.services.orders import EVENTS_CONTEXT_CODE, OrderItemInput, OrderService, normalize_phone


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE categoria (
                    id INTEGER PRIMARY KEY,
                    codigo VARCHAR(50) NOT NULL UNIQUE,
                    nombre VARCHAR(120) NOT NULL,
                    descripcion_publica VARCHAR,
                    foto_url VARCHAR(500),
                    orden INTEGER NOT NULL,
                    visible_cliente BOOLEAN NOT NULL,
                    es_automatica BOOLEAN NOT NULL,
                    cantidad_minima_total INTEGER,
                    prioridad INTEGER NOT NULL,
                    acumulable BOOLEAN NOT NULL,
                    activa BOOLEAN NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE producto (
                    id INTEGER PRIMARY KEY,
                    codigo VARCHAR(50) NOT NULL UNIQUE,
                    nombre VARCHAR(140) NOT NULL,
                    descripcion VARCHAR,
                    fotos JSON,
                    unidad_venta VARCHAR(20) NOT NULL,
                    activo BOOLEAN NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE producto_categoria (
                    id INTEGER PRIMARY KEY,
                    producto_id INTEGER NOT NULL,
                    categoria_id INTEGER NOT NULL,
                    precio NUMERIC(12, 2) NOT NULL,
                    descripcion_publica VARCHAR,
                    foto_url VARCHAR(500),
                    visible BOOLEAN NOT NULL,
                    orden INTEGER NOT NULL,
                    destacado BOOLEAN NOT NULL,
                    activo BOOLEAN NOT NULL,
                    UNIQUE(producto_id, categoria_id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE combo_regla (
                    id INTEGER PRIMARY KEY,
                    producto_a_id INTEGER NOT NULL,
                    producto_b_id INTEGER NOT NULL,
                    requiere_confirmacion BOOLEAN NOT NULL,
                    regla_precio VARCHAR(20) NOT NULL,
                    precio_fijo_combo NUMERIC(12, 2)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE promocion (
                    id INTEGER PRIMARY KEY,
                    codigo VARCHAR(80) NOT NULL UNIQUE,
                    nombre VARCHAR(140) NOT NULL,
                    tipo VARCHAR(40) NOT NULL,
                    cantidad_minima INTEGER NOT NULL,
                    precio_unitario_promocional NUMERIC(12, 2) NOT NULL,
                    activa BOOLEAN NOT NULL,
                    vigencia_desde DATETIME,
                    vigencia_hasta DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE promocion_producto (
                    id INTEGER PRIMARY KEY,
                    promocion_id INTEGER NOT NULL,
                    producto_id INTEGER NOT NULL,
                    UNIQUE(promocion_id, producto_id)
                )
                """
            )
        )
    return Session(engine)


def _catalog(session: Session) -> dict[str, int]:
    lista_horno = Categoria(codigo="LISTA_HORNO", nombre="Lista para hornear")
    eventos = Categoria(
        codigo="EVENTOS",
        nombre="Eventos",
        cantidad_minima_total=10,
    )
    mayorista = Categoria(
        codigo="MAYORISTA",
        nombre="Mayorista",
        visible_cliente=False,
        es_automatica=True,
        cantidad_minima_total=10,
        prioridad=100,
    )
    muzza = Producto(codigo="PROD-MUZZA", nombre="Muzzarella", unidad_venta=UnidadVenta.PIEZA)
    especial = Producto(codigo="PROD-ESP", nombre="Especial", unidad_venta=UnidadVenta.PIEZA)
    session.add_all([lista_horno, eventos, mayorista, muzza, especial])
    session.flush()
    for product, standard, event, wholesale in (
        (muzza, "5500.00", "5200.00", "4500.00"),
        (especial, "7000.00", "6600.00", "6000.00"),
    ):
        session.add_all(
            [
                ProductoCategoria(
                    producto_id=product.id or 0,
                    categoria_id=lista_horno.id or 0,
                    precio=Decimal(standard),
                ),
                ProductoCategoria(
                    producto_id=product.id or 0,
                    categoria_id=eventos.id or 0,
                    precio=Decimal(event),
                ),
                ProductoCategoria(
                    producto_id=product.id or 0,
                    categoria_id=mayorista.id or 0,
                    precio=Decimal(wholesale),
                ),
            ]
        )
    session.add(
        ComboRegla(
            producto_a_id=muzza.id or 0,
            producto_b_id=especial.id or 0,
            requiere_confirmacion=False,
            regla_precio=ReglaPrecioCombo.PROMEDIO,
        )
    )
    session.commit()
    return {
        "lista_horno": lista_horno.id or 0,
        "eventos": eventos.id or 0,
        "mayorista": mayorista.id or 0,
        "muzza": muzza.id or 0,
        "especial": especial.id or 0,
    }


def test_order_transition_allows_expected_path() -> None:
    assert_valid_order_transition(EstadoPedido.PEDIDO, EstadoPedido.EN_PROCESO)
    assert_valid_order_transition(EstadoPedido.EN_PROCESO, EstadoPedido.ENTREGADO)


def test_order_transition_rejects_terminal_regression() -> None:
    with pytest.raises(ValidationError):
        assert_valid_order_transition(EstadoPedido.ENTREGADO, EstadoPedido.EN_PROCESO)


def test_combo_price_uses_average_rule() -> None:
    combo = ComboRegla(
        producto_a_id=1,
        producto_b_id=2,
        requiere_confirmacion=False,
        regla_precio=ReglaPrecioCombo.PROMEDIO,
    )

    price = OrderService(session=None)._combo_price(  # type: ignore[arg-type]
        combo,
        Decimal("5500.00"),
        Decimal("7000.00"),
    )

    assert price == Decimal("6250.00")


def test_normalize_phone_keeps_plus_and_digits() -> None:
    assert normalize_phone(" +54 381 555-1234 ") == "+543815551234"
    assert normalize_phone("0054 381 555-1234") == "+543815551234"


def test_standard_order_with_10_units_uses_automatic_wholesale_price() -> None:
    with _session() as session:
        ids = _catalog(session)

        priced_items = OrderService(session)._price_items(
            [OrderItemInput(producto_id=ids["muzza"], cantidad=10)]
        )

        assert priced_items[0].categoria_venta_id == ids["mayorista"]
        assert priced_items[0].precio_unitario == Decimal("4500.00")
        assert priced_items[0].subtotal == Decimal("45000.00")


def test_events_order_with_12_units_keeps_events_price() -> None:
    with _session() as session:
        ids = _catalog(session)

        priced_items = OrderService(session)._price_items(
            [OrderItemInput(producto_id=ids["muzza"], cantidad=12)],
            contexto_origen=EVENTS_CONTEXT_CODE,
        )

        assert priced_items[0].categoria_venta_id == ids["eventos"]
        assert priced_items[0].precio_unitario == Decimal("5200.00")


def test_events_order_below_minimum_is_rejected() -> None:
    with _session() as session:
        ids = _catalog(session)

        with pytest.raises(ValidationError):
            OrderService(session)._price_items(
                [OrderItemInput(producto_id=ids["muzza"], cantidad=9)],
                contexto_origen=EVENTS_CONTEXT_CODE,
            )


def test_combos_count_as_one_unit_each_for_wholesale_threshold() -> None:
    with _session() as session:
        ids = _catalog(session)

        priced_items = OrderService(session)._price_items(
            [
                OrderItemInput(
                    producto_id=ids["muzza"],
                    producto_combo_id=ids["especial"],
                    cantidad=10,
                )
            ]
        )

        assert priced_items[0].categoria_venta_id == ids["mayorista"]
        assert priced_items[0].precio_unitario == Decimal("5250.00")


def test_combo_regla_migration_defines_symmetric_unique_index() -> None:
    migration = "alembic/versions/0001_initial_schema.py"
    with open(migration, encoding="utf-8") as file:
        content = file.read()

    assert "CREATE UNIQUE INDEX uq_combo_regla_par" in content
    assert "LEAST(producto_a_id, producto_b_id)" in content
    assert "GREATEST(producto_a_id, producto_b_id)" in content
