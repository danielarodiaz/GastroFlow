from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlmodel import Session, create_engine, select

from gastroflow.domain.enums import RolUsuario
from gastroflow.domain.errors import ValidationError
from gastroflow.models import (
    Gasto,
    GastoDetalle,
    GastoDocumento,
    Marca,
    MotivoGasto,
    UsuarioRead,
)
from gastroflow.services import ExpenseDetailInput, ExpenseService, ExpenseTicketInput
from gastroflow.services.expenses import normalize_catalog_name


def test_normalize_catalog_name_collapses_spaces() -> None:
    assert normalize_catalog_name("  Harina   000  ") == "Harina 000"


def test_expense_validation_rejects_negative_price() -> None:
    service = ExpenseService(session=None)  # type: ignore[arg-type]
    data = ExpenseTicketInput(
        fecha=date.today(),
        lugar_texto="Proveedor",
        items=[
            ExpenseDetailInput(
                motivo_nombre="Harina",
                marca_nombre="Marca",
                cantidad=Decimal("1"),
                unidad_medida="kg",
                precio_unitario=Decimal("-1"),
            )
        ],
    )

    with pytest.raises(ValidationError):
        service._validate(data)


def test_expense_validation_accepts_item_without_brand() -> None:
    service = ExpenseService(session=None)  # type: ignore[arg-type]
    data = ExpenseTicketInput(
        fecha=date.today(),
        lugar_texto="Verduleria",
        items=[
            ExpenseDetailInput(
                motivo_nombre="Cebolla",
                marca_nombre=None,
                cantidad=Decimal("1"),
                unidad_medida="kg",
                precio_unitario=Decimal("1000"),
            )
        ],
    )

    service._validate(data)


def test_get_or_create_brand_skips_blank_value() -> None:
    service = ExpenseService(session=None)  # type: ignore[arg-type]

    assert service._get_or_create_marca(None) is None
    assert service._get_or_create_marca("   ") is None


def test_expense_money_and_quantity_are_quantized() -> None:
    service = ExpenseService(session=None)  # type: ignore[arg-type]

    assert service._money(Decimal("10.129")) == Decimal("10.13")
    assert service._quantity(Decimal("1.2349")) == Decimal("1.235")


def test_expense_line_subtotal_uses_quantity_and_unit_price() -> None:
    service = ExpenseService(session=None)  # type: ignore[arg-type]
    item = ExpenseDetailInput(
        motivo_nombre="Harina",
        marca_nombre="Marca",
        cantidad=Decimal("2.5"),
        unidad_medida="kg",
        precio_unitario=Decimal("10.00"),
    )

    assert service._line_subtotal(item) == Decimal("25.00")


def test_expense_line_preserves_entered_total() -> None:
    service = ExpenseService(session=None)  # type: ignore[arg-type]
    item = ExpenseDetailInput(
        motivo_nombre="Harina",
        marca_nombre="Marca",
        cantidad=Decimal("3"),
        unidad_medida="kg",
        precio_unitario=Decimal("3.33"),
        subtotal=Decimal("10.00"),
    )

    assert service._line_subtotal(item) == Decimal("10.00")


def test_expense_ticket_can_be_updated_and_deleted() -> None:
    engine = create_engine("sqlite://")
    for table in (
        MotivoGasto.__table__, Marca.__table__, Gasto.__table__,
        GastoDetalle.__table__, GastoDocumento.__table__,
    ):
        table.create(engine)
    user = UsuarioRead(
        id=1,
        username="ADMIN",
        rol=RolUsuario.ADMIN,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    with Session(engine) as session:
        motive = MotivoGasto(nombre="Harina")
        session.add(motive)
        session.flush()
        expense = Gasto(
            codigo="GAS-0001",
            fecha=date(2026, 10, 15),
            lugar_texto="Proveedor anterior",
            monto_total=Decimal("100.00"),
        )
        session.add(expense)
        session.flush()
        session.add(GastoDetalle(
            gasto_id=expense.id or 0,
            motivo_gasto_id=motive.id or 0,
            marca_id=None,
            cantidad=Decimal("1"),
            unidad_medida="UNIDAD",
            precio_unitario=Decimal("100"),
            subtotal=Decimal("100"),
        ))
        session.commit()
        expense_id = expense.id or 0

        updated = ExpenseService(session).update_expense_ticket(
            expense_id,
            ExpenseTicketInput(
                fecha=date(2026, 10, 16),
                lugar_texto="Proveedor nuevo",
                medio_pago="TRANSFERENCIA",
                destinatario_pago="Titular",
                items=[ExpenseDetailInput(
                    motivo_nombre="Muzarella",
                    marca_nombre="Las Majadas",
                    descripcion="Corregido",
                    cantidad=Decimal("2"),
                    unidad_medida="KG",
                    precio_unitario=Decimal("250"),
                    subtotal=Decimal("500"),
                )],
            ),
            user,
        )
        assert updated.lugar_texto == "Proveedor nuevo"
        assert updated.monto_total == Decimal("500.00")
        details = session.exec(select(GastoDetalle).where(GastoDetalle.gasto_id == expense_id)).all()
        assert len(details) == 1 and details[0].subtotal == Decimal("500.00")

        session.add(GastoDocumento(
            gasto_id=expense_id,
            nombre_archivo="ticket.jpg",
            archivo_url="gastos/ticket.jpg",
            contenido_sha256="a" * 64,
            tipo_contenido="image/jpeg",
        ))
        session.commit()
        assert ExpenseService(session).delete_expense_ticket(expense_id, user) == "GAS-0001"
        assert session.get(Gasto, expense_id) is None
        assert session.exec(select(GastoDetalle)).all() == []
        assert session.exec(select(GastoDocumento)).all() == []
