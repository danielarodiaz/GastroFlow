from datetime import datetime, timezone

from gastroflow.domain.enums import RolUsuario
from gastroflow.models import Usuario
from gastroflow.services.admin_crud import CRUD_TABLES, AdminCrudService


def test_crud_registry_contains_all_model_tables() -> None:
    assert set(CRUD_TABLES) == {
        "categoria",
        "producto",
        "producto_categoria",
        "promocion",
        "promocion_producto",
        "combo_regla",
        "zona_envio",
        "motivo_gasto",
        "marca",
        "usuario",
        "cliente",
        "pedido",
        "pedido_item",
        "gasto",
    }


def test_user_serialization_excludes_password_hash() -> None:
    user = Usuario(
        id=1,
        username="admin",
        rol=RolUsuario.ADMIN,
        password_hash="secret-hash",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    service = AdminCrudService(session=None)  # type: ignore[arg-type]

    serialized = service._serialize(user, CRUD_TABLES["usuario"])

    assert serialized["username"] == "admin"
    assert serialized["rol"] == "admin"
    assert "password_hash" not in serialized
