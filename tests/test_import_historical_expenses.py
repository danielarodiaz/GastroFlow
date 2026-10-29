from datetime import date
from decimal import Decimal

from scripts.import_historical_expenses import build_ticket_inputs
from scripts.prepare_historical_expenses import PreparedExpenseRow


def _row(excel_row: int, *, brand: str | None, total: str) -> PreparedExpenseRow:
    return PreparedExpenseRow(
        excel_row=excel_row,
        source_id=str(excel_row - 1),
        ticket_group="2026-06-12|proveedor",
        expense_date=date(2026, 6, 12),
        place_original="Proveedor",
        place_normalized="Proveedor",
        motive_original="Harina",
        motive_normalized="Harina",
        brand_original=brand,
        brand_normalized=brand,
        quantity_original="2kg",
        quantity=Decimal("2.000"),
        unit="KG",
        presentation=None,
        line_total=Decimal(total),
        unit_price=(Decimal(total) / Decimal("2")).quantize(Decimal("0.01")),
        status="LISTO",
        note=None,
    )


def test_build_ticket_inputs_groups_items_and_preserves_optional_brand() -> None:
    tickets = build_ticket_inputs(
        [_row(2, brand="Marca", total="100.00"), _row(3, brand=None, total="80.00")],
        source_hash="abc123",
    )

    assert len(tickets) == 1
    assert len(tickets[0].items) == 2
    assert tickets[0].items[1].marca_nombre is None
    assert tickets[0].items[0].subtotal == Decimal("100.00")
    assert "GASTOS-HISTORICOS-SHA256:abc123" in (tickets[0].observaciones or "")
    assert "filas=2,3" in (tickets[0].observaciones or "")
