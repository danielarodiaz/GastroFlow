from datetime import date
from decimal import Decimal

from gastroflow.services.expense_documents import (
    draft_from_ocr_text,
    draft_from_azure_result,
    parse_purchase_comment,
)


def test_parse_transfer_comment_creates_reviewable_items() -> None:
    items = parse_purchase_comment(
        "2 atado de albahaca a $5.000 y 1k de tomate cherry a $3.000"
    )

    assert [(item.motivo, item.cantidad, item.unidad, item.subtotal) for item in items] == [
        ("Albahaca", Decimal("2"), "ATADO", Decimal("5000.00")),
        ("Tomate Cherry", Decimal("1"), "KG", Decimal("3000.00")),
    ]
    assert items[0].precio_unitario == Decimal("2500.00")


def test_azure_transfer_result_separates_store_from_payment_recipient() -> None:
    payload = {
        "status": "succeeded",
        "analyzeResult": {
            "content": (
                "Comprobante de transferencia\n$ 8.000\n21/10/2026 - 13:23 hs\n"
                "Destinatario\nFranco Ezequiel Suarez\nMotivo\nVarios\nComentario\n"
                "2 atado de albahaca a $5.000 y 1k de tomate cherry a $3.000\n"
                "Id. Op.\nf011d651-f396-4c4d-ac4d-4a88d1c5a288"
            ),
            "documents": [{"confidence": 0.91, "fields": {}}],
        },
    }

    draft = draft_from_azure_result(payload)

    assert draft.fecha == date(2026, 10, 21)
    assert draft.monto_total == Decimal("8000.00")
    assert draft.medio_pago == "TRANSFERENCIA"
    assert draft.destinatario_pago == "Franco Ezequiel Suarez"
    assert draft.lugar == ""
    assert len(draft.items) == 2
    assert sum(item.subtotal for item in draft.items) == Decimal("8000.00")
    assert "CVU" not in draft.to_json()
    assert "texto_extraido" not in draft.to_json()


def test_local_ocr_text_uses_same_transfer_parser_without_azure() -> None:
    text = (
        "Comprobante de transferencia\n$ 8.000\n21/10/2026 - 13:23 hs\n"
        "Destinatario Franco Ezequiel Suarez\nComentario\n"
        "2 atado de albahaca a $5.000 y 1k de tomate cherry a $3.000\n"
        "Id. Op. f011d651-f396-4c4d-ac4d-4a88d1c5a288"
    )

    draft = draft_from_ocr_text(text)

    assert draft.medio_pago == "TRANSFERENCIA"
    assert draft.destinatario_pago == "Franco Ezequiel Suarez"
    assert len(draft.items) == 2
    assert draft.monto_total == Decimal("8000.00")


def test_thermal_ticket_ocr_extracts_header_items_brands_and_total() -> None:
    text = """
    DISTRIBUIDORA VID! S.R.L.
    CUIT: 30673770483
    Inicio Act.: 03/05/1990
    FECHA 21/10/2026 12:49:32
    Cantidad x Precio unit.
    1x5 7561,40
    ACEITUNA BLATI VERDE NO1 X 1 KG $ 7561,40 |
    4,900 x $ 8470,00
    MUZARELLA CILINDRO LAS MAJADAS. $ 41503,00 |
    1 HORMA
    TOTAL $ 40004,40
    Mercado Pago QR $ 49064,40
    """

    draft = draft_from_ocr_text(text)

    assert draft.fecha == date(2026, 10, 21)
    assert draft.lugar == "Distribuidora VIDT"
    assert draft.monto_total == Decimal("49064.40")
    assert [(item.motivo, item.marca, item.cantidad, item.unidad, item.subtotal) for item in draft.items] == [
        ("Aceituna Verde No1", "Blati", Decimal("1"), "KG", Decimal("7561.40")),
        ("Muzarella Cilindro", "Las Majadas", Decimal("4.900"), "KG", Decimal("41503.00")),
    ]


def test_faint_ticket_keeps_partial_header_and_requests_manual_items() -> None:
    text = """
    CUIT: 30673770483
    PLOCHA 15/10/2026 12:36
    Cantidad x Precio unit.
    Jeseripcion Importe
    Mercado Pago UR y 41950,91
    """

    draft = draft_from_ocr_text(text)

    assert draft.fecha == date(2026, 10, 15)
    assert draft.lugar == "Distribuidora VIDT"
    assert draft.monto_total == Decimal("41950.91")
    assert draft.items == []
    assert draft.advertencias
