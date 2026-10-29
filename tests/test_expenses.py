from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from gastroflow.domain.enums import RolUsuario
from gastroflow.domain.errors import ValidationError
from gastroflow.models import UsuarioRead
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
