from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlmodel import Session

from gastroflow.data.database import engine
from gastroflow.domain.enums import RolUsuario, UnidadVenta
from gastroflow.models import UsuarioRead
from gastroflow.services import AdminCrudService


def main() -> None:
    admin = UsuarioRead(
        id=1,
        username="smoke_admin",
        rol=RolUsuario.ADMIN,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    with Session(engine) as session:
        service = AdminCrudService(session)
        categoria = service.create_record(
            "categoria",
            {"codigo": "CRUD_SMOKE", "nombre": "CRUD Smoke"},
            admin,
        )
        producto = service.create_record(
            "producto",
            {
                "codigo": "CRUD_SMOKE_PRODUCTO",
                "nombre": "Producto CRUD Smoke",
                "descripcion": None,
                "fotos": None,
                "unidad_venta": UnidadVenta.PIEZA,
            },
            admin,
        )
        service.create_record(
            "producto_categoria",
            {
                "producto_id": producto["id"],
                "categoria_id": categoria["id"],
                "precio": Decimal("1000.00"),
                "activo": True,
            },
            admin,
        )
        updated = service.update_record(
            "producto",
            producto["id"],
            {"nombre": "Producto CRUD Smoke Editado"},
            admin,
        )
        user = service.create_record(
            "usuario",
            {
                "username": f"crud_smoke_{datetime.now(timezone.utc).timestamp()}",
                "password": "CrudSmoke123",
                "rol": RolUsuario.DUENO,
            },
            admin,
        )
        listed = service.list_records("producto", admin)
        for row in service.list_records("producto_categoria", admin):
            if row["producto_id"] == producto["id"] and row["categoria_id"] == categoria["id"]:
                service.delete_record("producto_categoria", row["id"], admin)
        service.delete_record("producto", producto["id"], admin)
        service.delete_record("categoria", categoria["id"], admin)

        print(categoria["codigo"], updated["nombre"], user["rol"], "password_hash" in user)
        print(any(item["id"] == producto["id"] for item in listed))


if __name__ == "__main__":
    main()
