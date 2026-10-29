from decimal import Decimal

from scripts.prepare_historical_expenses import (
    normalize_brand,
    normalize_motive,
    normalize_place,
    parse_quantity,
)


def test_confirmed_place_corrections_do_not_merge_vidt_and_vdi() -> None:
    assert normalize_place("Veduleria Sofia") == "Verduleria Sofia"
    assert normalize_place("Verduleria Sofia") == "Verduleria Sofia"
    assert normalize_place("Elisa") == "Distribuidora Elisa"
    assert normalize_place("Distribuidora Elisa") == "Distribuidora Elisa"
    assert normalize_place("YPF autopista") == "YPF"
    assert normalize_place("Distribuidora VIDT") == "Distribuidora VIDT"
    assert normalize_place("Distribuidora VDI") == "Distribuidora VDI"


def test_motive_and_brand_normalization() -> None:
    assert normalize_motive(" Pure   de tomate ") == "Pure de Tomate"
    assert normalize_motive(" Harina ") == "Harina"
    assert normalize_brand(None) is None
    assert normalize_brand("Sin marca") is None
    assert normalize_brand(" Las   Majadas ") == "Las Majadas"


def test_quantity_parser_standardizes_weight_volume_and_packages() -> None:
    assert parse_quantity("500gr", motive="Levadura").quantity == Decimal("0.500")
    assert parse_quantity("500gr", motive="Levadura").unit == "KG"
    assert parse_quantity("4,5lt", motive="Aceite").quantity == Decimal("4.500")
    assert parse_quantity("4,5lt", motive="Aceite").unit == "L"
    assert parse_quantity("Media Horma/2.5kg", motive="Queso Muzza").quantity == Decimal("2.500")
    assert parse_quantity("4x100gr", motive="Aceituna verde").quantity == Decimal("0.400")
    assert parse_quantity("1/2kg", motive="Folex").quantity == Decimal("0.500")


def test_quantity_parser_marks_source_corrections_for_review() -> None:
    result = parse_quantity("850lt", motive="Aceite")
    assert result.quantity == Decimal("0.850")
    assert result.unit == "L"
    assert result.review_required is False
    assert "confirmada" in (result.note or "")

    missing = parse_quantity(None, motive="Nafta super")
    assert missing.quantity == Decimal("1.000")
    assert missing.unit == "CARGA"
    assert missing.review_required is False
    assert "confirmada" in (missing.note or "")
