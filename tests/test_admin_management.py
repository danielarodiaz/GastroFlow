from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from gastroflow.domain.enums import PermisoUsuario, RolUsuario
from gastroflow.domain.errors import AuthenticationError, ValidationError
from gastroflow.models import (
    Agregado,
    AgregadoCategoria,
    CambioAdministrativo,
    Categoria,
    Usuario,
    UsuarioRead,
    ZonaEnvio,
)
from gastroflow.security import hash_password
from gastroflow.services import AdminManagementService, AuthService


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[
            Usuario.__table__,
            ZonaEnvio.__table__,
            Categoria.__table__,
            Agregado.__table__,
            AgregadoCategoria.__table__,
            CambioAdministrativo.__table__,
        ],
    )
    return engine


def _admin() -> UsuarioRead:
    now = datetime.now(timezone.utc)
    return UsuarioRead(
        id=1,
        username="ADMIN",
        rol=RolUsuario.ADMIN,
        activo=True,
        permisos=[permission.value for permission in PermisoUsuario],
        created_at=now,
        updated_at=now,
    )


def test_zone_category_and_addon_lifecycle_is_audited() -> None:
    engine = _engine()
    with Session(engine) as session:
        session.add(
            Usuario(
                id=1,
                username="ADMIN",
                rol=RolUsuario.ADMIN,
                activo=True,
                permisos=[permission.value for permission in PermisoUsuario],
                password_hash=hash_password("Admin1234"),
            )
        )
        session.commit()
        service = AdminManagementService(session)
        zone = service.create_zone("Centro", Decimal("1500"), _admin())
        service.update_zone(zone.id or 0, "Centro ampliado", Decimal("1800"), _admin())
        service.set_zone_active(zone.id or 0, False, _admin())
        category = service.create_category("Pizzas especiales", "Edición de temporada", _admin())
        addon = service.create_addon("Extra queso", Decimal("900"), [category.id or 0], _admin())
        service.set_addon_active(addon.id or 0, False, _admin())

        assert service.list_zones(_admin())[0].activa is False
        assert service.list_categories(_admin())[0].codigo == "PIZZAS_ESPECIALES"
        assert session.exec(
            select(AgregadoCategoria).where(AgregadoCategoria.agregado_id == addon.id)
        ).one().categoria_id == category.id
        assert len(session.exec(select(CambioAdministrativo)).all()) == 6


def test_last_user_manager_cannot_lose_access_or_be_deactivated() -> None:
    engine = _engine()
    permissions = [permission.value for permission in PermisoUsuario]
    with Session(engine) as session:
        session.add(
            Usuario(
                id=1,
                username="ADMIN",
                rol=RolUsuario.ADMIN,
                activo=True,
                permisos=permissions,
                password_hash=hash_password("Admin1234"),
            )
        )
        session.commit()
        service = AdminManagementService(session)

        with pytest.raises(ValidationError, match="al menos un usuario activo"):
            service.update_user(
                1,
                "ADMIN",
                "",
                [PermisoUsuario.PEDIDOS.value],
                _admin(),
            )
        with pytest.raises(ValidationError, match="propio usuario"):
            service.set_user_active(1, False, _admin())


def test_inactive_user_cannot_authenticate() -> None:
    engine = _engine()
    with Session(engine) as session:
        user = Usuario(
            username="COCINA",
            rol=RolUsuario.DUENO,
            activo=False,
            permisos=[PermisoUsuario.PEDIDOS.value],
            password_hash=hash_password("Cocina123"),
        )
        session.add(user)
        session.commit()

        with pytest.raises(AuthenticationError, match="desactivado"):
            AuthService(session).authenticate("cocina", "Cocina123")


def test_user_can_be_created_modified_and_deactivated() -> None:
    engine = _engine()
    with Session(engine) as session:
        session.add(
            Usuario(
                id=1,
                username="ADMIN",
                rol=RolUsuario.ADMIN,
                activo=True,
                permisos=[permission.value for permission in PermisoUsuario],
                password_hash=hash_password("Admin1234"),
            )
        )
        session.commit()
        service = AdminManagementService(session)
        user = service.create_user(
            "cocina",
            "Cocina123",
            [PermisoUsuario.PEDIDOS.value],
            _admin(),
        )
        assert AuthService(session).authenticate("COCINA", "Cocina123").id == user.id

        service.update_user(
            user.id or 0,
            "cocina noche",
            "Cocina456",
            [PermisoUsuario.PEDIDOS.value, PermisoUsuario.GASTOS.value],
            _admin(),
        )
        updated = AuthService(session).authenticate("COCINA NOCHE", "Cocina456")
        assert AuthService.effective_permissions(updated) == {
            PermisoUsuario.PEDIDOS.value,
            PermisoUsuario.GASTOS.value,
        }

        service.set_user_active(user.id or 0, False, _admin())
        with pytest.raises(AuthenticationError, match="desactivado"):
            AuthService(session).authenticate("COCINA NOCHE", "Cocina456")
