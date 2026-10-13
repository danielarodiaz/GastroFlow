from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlmodel import Session, select

from gastroflow.data.database import engine
from gastroflow.domain.enums import RolUsuario
from gastroflow.models import GastoDetalle, Marca, MotivoGasto, UsuarioRead
from gastroflow.services import ExpenseInput, ExpenseService


def main() -> None:
    user = UsuarioRead(
        id=1,
        username="smoke_admin",
        rol=RolUsuario.ADMIN,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    with Session(engine) as session:
        service = ExpenseService(session)
        gasto = service.create_expense(
            ExpenseInput(
                fecha=date.today(),
                motivo_nombre="  Harina   000 ",
                marca_nombre=" Molino Smoke ",
                cantidad=Decimal("25"),
                unidad_medida="kg",
                precio=Decimal("12000.50"),
                lugar_texto="Proveedor Smoke",
            ),
            current_user=user,
        )
        repeated = service.create_expense(
            ExpenseInput(
                fecha=date.today(),
                motivo_nombre="harina 000",
                marca_nombre="molino smoke",
                cantidad=Decimal("1.5"),
                unidad_medida="kg",
                precio=Decimal("900.00"),
                lugar_texto="Proveedor Smoke",
            ),
            current_user=user,
        )
        motivos = session.exec(select(MotivoGasto).where(MotivoGasto.nombre == "Harina 000")).all()
        marcas = session.exec(select(Marca).where(Marca.nombre == "Molino Smoke")).all()

        gasto_detail = session.exec(select(GastoDetalle).where(GastoDetalle.gasto_id == gasto.id)).first()
        repeated_detail = session.exec(select(GastoDetalle).where(GastoDetalle.gasto_id == repeated.id)).first()

        print(gasto.codigo, gasto.monto_total, gasto_detail.subtotal if gasto_detail else None)
        print(repeated.codigo, repeated.monto_total, repeated_detail.subtotal if repeated_detail else None)
        print(len(motivos), len(marcas))


if __name__ == "__main__":
    main()
