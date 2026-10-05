from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from gastroflow.domain.enums import RolUsuario
from gastroflow.domain.errors import ValidationError
from gastroflow.models import UsuarioRead
from gastroflow.services import ExpenseInput, ExpenseService
from gastroflow.services.expenses import normalize_catalog_name


def test_normalize_catalog_name_collapses_spaces() -> None:
    assert normalize_catalog_name("  harina   000  ") == "HARINA 000"


def test_expense_validation_rejects_negative_price() -> None:
    service = ExpenseService(session=None)  # type: ignore[arg-type]
    data = ExpenseInput(
        fecha=date.today(),
        motivo_nombre="Harina",
        marca_nombre="Marca",
        cantidad=Decimal("1"),
        unidad_medida="kg",
        precio=Decimal("-1"),
        lugar_texto="Proveedor",
    )

    with pytest.raises(ValidationError):
        service._validate(data)


def test_expense_money_and_quantity_are_quantized() -> None:
    service = ExpenseService(session=None)  # type: ignore[arg-type]

    assert service._money(Decimal("10.129")) == Decimal("10.13")
    assert service._quantity(Decimal("1.2349")) == Decimal("1.235")
