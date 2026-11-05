import asyncio
from datetime import date, datetime, time
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlmodel import Session, create_engine, select
from sqlalchemy.pool import StaticPool

from gastroflow.domain.enums import FormaPago
from gastroflow.domain.errors import ValidationError
from gastroflow.models import AvisoPublico
from gastroflow.services.orders import OrderItemInput, OrderService, PublicOrderInput
from gastroflow.services.public_notices import active_notices, delivery_block, notice_rows, validate_notice
from gastroflow.states import public_order_state as public
from gastroflow.states.public_order_state import PublicOrderState


def row(**overrides):
    return {
        "id": 1, "titulo": "Solo retiro", "mensaje": "Del 7 al 12 no hacemos envíos.",
        "tipo": "informativo", "accion": "suspender_envios", "habilitado": True,
        "prioridad": 0, "inicio": "2026-11-07T00:00:00", "fin": "2026-11-12T18:00:00",
        **overrides,
    }


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    AvisoPublico.__table__.create(engine)
    yield engine
    engine.dispose()


def test_information_before_offers_then_priority_and_deterministic_order():
    rows = [row(id=4, tipo="oferta", accion="ninguna", prioridad=-50),
            row(id=3, prioridad=2), row(id=2), row(id=1),
            row(id=5, habilitado=False), row(id=6, inicio="2026-11-10T00:00:00")]
    assert [notice["id"] for notice in active_notices(rows, datetime(2026, 11, 9))] == [1, 2, 3, 4]


@pytest.mark.parametrize("instant,expected", [
    (datetime(2026, 11, 6, 23, 59), False),
    (datetime(2026, 11, 7), True),
    (datetime(2026, 11, 12, 17, 59), True),
    (datetime(2026, 11, 12, 18), False),
])
def test_start_inclusive_end_exclusive_for_popups_and_delivery(instant, expected):
    assert bool(active_notices([row()], instant)) is expected
    assert bool(delivery_block([row()], instant.date(), instant.time())) is expected


def test_no_end_disabled_and_information_does_not_restrict():
    assert delivery_block([row(fin=None)], date(2027, 1, 1), time(21))
    assert not delivery_block([row(habilitado=False)], date(2026, 11, 8), time(21))
    assert not delivery_block([row(accion="ninguna")], date(2026, 11, 8), time(21))
    assert delivery_block([row()], date(2026, 11, 12))  # Unknown hour requires choosing one.
    assert not delivery_block([row()], date(2026, 11, 13))


def test_popup_queue_once_per_visit_and_edited_notice_reappears(monkeypatch):
    rows = [row(), row(id=2, tipo="oferta", accion="ninguna", titulo="Promo")]
    monkeypatch.setattr(public, "_read_public_notices", lambda: rows)
    monkeypatch.setattr("gastroflow.services.public_notices.argentina_now", lambda: datetime(2026, 11, 9))
    state = PublicOrderState(_reflex_internal_init=True)
    asyncio.run(state.load_notices())
    assert state.notice_open and state.current_notice["titulo"] == "Solo retiro"
    state.close_notice()
    assert state.current_notice["titulo"] == "Promo"
    state.show_categories()
    state.close_notice()
    assert not state.notice_open
    assert state.notice_rules  # Closing never removes the business rule.
    asyncio.run(state.load_notices())
    assert not state.notice_open
    rows[0]["mensaje"] = "Nuevo mensaje del local"
    asyncio.run(state.load_notices())
    assert len(state.notice_queue) == 1
    assert state.current_notice["mensaje"] == "Nuevo mensaje del local"


def test_delivery_button_uses_scheduled_date_not_date_of_visit():
    state = PublicOrderState(_reflex_internal_init=True)
    state.notice_rules = [row()]
    state.fecha_entrega, state.horario_entrega = "08-11-2026", "21:00"
    state.set_delivery_mode("delivery")
    assert state.delivery_mode == "retiro"
    assert "No hay envíos" in state.message
    state.fecha_entrega = "13-11-2026"
    state.set_delivery_mode("delivery")
    assert state.delivery_mode == "delivery"


def test_backend_rechecks_live_restrictions_even_after_client_closed_notice(engine, monkeypatch):
    with Session(engine) as session:
        session.add(AvisoPublico.model_validate(row()))
        session.commit()
        service = OrderService(session)
        payload = dict(nombre_apellido="Cliente", telefono="3815551234", fecha_entrega=date(2026, 11, 8),
            horario_entrega=time(21), direccion_delivery="Calle 123", forma_pago=FormaPago.EFECTIVO,
            items=[OrderItemInput(1, 1)])
        with pytest.raises(ValidationError, match="No hay envíos"):
            service.create_public_order(PublicOrderInput(**payload, zona_envio_id=1))
        # Pickup passes the restriction check and reaches ordinary order validation.
        def reached(*args):
            raise RuntimeError("ordinary order processing")
        monkeypatch.setattr(service, "_upsert_cliente", reached)
        with pytest.raises(RuntimeError, match="ordinary order processing"):
            service.create_public_order(PublicOrderInput(**payload))
        payload["fecha_entrega"] = date(2026, 11, 13)
        with pytest.raises(RuntimeError, match="ordinary order processing"):
            service.create_public_order(PublicOrderInput(**payload, zona_envio_id=1))
        # Disabling in admin immediately permits a formerly restricted delivery.
        notice = session.get(AvisoPublico, 1)
        notice.habilitado = False
        session.commit()
        payload["fecha_entrega"] = date(2026, 11, 8)
        with pytest.raises(RuntimeError, match="ordinary order processing"):
            service.create_public_order(PublicOrderInput(**payload, zona_envio_id=1))


@pytest.mark.parametrize("changes", [
    {"titulo": " "}, {"mensaje": " "}, {"fin": "2026-11-06T00:00:00"},
    {"tipo": "oferta"}, {"accion": "execute_code"},
])
def test_admin_validation_rejects_invalid_notice(changes):
    with pytest.raises(ValidationError):
        validate_notice(AvisoPublico.model_validate(row(**changes)))


def test_new_migration_creates_expected_schema_and_rolls_back():
    path = Path("alembic/versions/0017_public_notices.py")
    spec = importlib.util.spec_from_file_location("public_notice_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        rich_spec = importlib.util.spec_from_file_location("rich_notice_migration", Path("alembic/versions/0018_notice_rich_text.py"))
        rich_migration = importlib.util.module_from_spec(rich_spec)
        rich_spec.loader.exec_module(rich_migration)
        rich_migration.op = migration.op
        rich_migration.upgrade()
        with Session(connection) as session:
            session.add(AvisoPublico.model_validate(row()))
            session.commit()
            assert notice_rows(session)[0]["titulo"] == "Solo retiro"
        rich_migration.downgrade()
        migration.downgrade()


def test_admin_creates_and_disables_notice(engine, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from gastroflow.internal_app import public_notice_editor as editor
    # AppTest cannot rerun fragments in isolation.
    monkeypatch.setattr(editor, "render_public_notice_editor", editor.render_public_notice_editor.__wrapped__)
    # AppTest cannot operate a custom iframe; the actual editor is tested in Edge.
    monkeypatch.setattr(editor, "rich_text_editor", lambda initial_html, key: editor.st.text_area("Mensaje", value=initial_html, key=key))
    def page():
        import streamlit as st
        from gastroflow.internal_app.public_notice_editor import render_public_notice_editor
        render_public_notice_editor(st.session_state.test_engine)
    test = AppTest.from_function(page)
    test.session_state.test_engine = engine
    test.run()
    assert not test.exception
    assert test.date_input[1].disabled and test.time_input[1].disabled
    next(box for box in test.checkbox if box.label == "Sin fecha de fin").uncheck().run()
    assert not test.date_input[1].disabled and not test.time_input[1].disabled
    next(box for box in test.checkbox if box.label == "Sin fecha de fin").check().run()
    test.text_input[0].input("Promo de prueba")
    test.text_area[0].input("2 muzzas listas para hornear")
    next(button for button in test.button if button.label == "Visualizar vista previa").click().run()
    with Session(engine) as session:
        assert session.exec(select(AvisoPublico)).all() == []

    next(button for button in test.button if button.label == "Guardar aviso").click().run()
    assert not test.exception and test.success
    with Session(engine) as session:
        saved = session.exec(select(AvisoPublico)).one()
        assert saved.titulo == "Promo de prueba" and saved.habilitado
    test.selectbox[0].select(saved.id).run()
    test.checkbox[0].uncheck()
    next(button for button in test.button if button.label == "Guardar aviso").click().run()
    with Session(engine) as session:
        assert not session.get(AvisoPublico, saved.id).habilitado
    next(box for box in test.checkbox if "eliminar" in box.label).check().run()
    next(button for button in test.button if button.label == "Eliminar aviso").click().run()
    assert not test.exception
    with Session(engine) as session:
        assert session.exec(select(AvisoPublico)).all() == []


def test_notices_are_available_under_admin_configuration(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from gastroflow.internal_app import streamlit_app as internal
    from gastroflow.domain.enums import PermisoUsuario
    monkeypatch.setattr(internal, "_has_permission", lambda permission: permission == PermisoUsuario.CONFIGURACION)
    monkeypatch.setattr(internal, "_render_admin_zones", lambda: internal.st.text("Zonas"))
    monkeypatch.setattr(internal, "render_public_notice_editor", lambda engine: internal.st.text("Editor de avisos"))
    def page():
        from gastroflow.internal_app.streamlit_app import _render_admin
        _render_admin()
    test = AppTest.from_function(page).run()
    assert "Avisos y Campañas" in test.radio[0].options
    test.radio[0].set_value("Avisos y Campañas").run()
    assert not test.exception
    assert any(text.value == "Editor de avisos" for text in test.text)


def test_remove_menu_unpublishes_configured_image(engine, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from gastroflow.internal_app import streamlit_app as internal
    from gastroflow.models import AppConfig
    from gastroflow.services.brand_media import MENU_IMAGE_CONFIG_KEY
    AppConfig.__table__.create(engine)
    with Session(engine) as session:
        session.add(AppConfig(key=MENU_IMAGE_CONFIG_KEY, value="https://example.com/carta.jpg"))
        session.commit()
    monkeypatch.setattr(internal, "engine", engine)
    monkeypatch.setattr(internal, "_render_brand_media_editor", internal._render_brand_media_editor.__wrapped__)
    def page():
        from gastroflow.internal_app.streamlit_app import _render_brand_media_editor
        _render_brand_media_editor()
    test = AppTest.from_function(page).run()
    assert not test.exception
    next(button for button in test.button if button.label == "Quitar carta").click().run()
    assert not test.exception and test.success
    with Session(engine) as session:
        assert session.exec(select(AppConfig).where(AppConfig.key == MENU_IMAGE_CONFIG_KEY)).one().value == ""
