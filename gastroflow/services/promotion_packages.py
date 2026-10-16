"""Price complete packages across categories without stacking other discounts."""

from dataclasses import replace
from decimal import Decimal, ROUND_DOWN
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from gastroflow.models import Categoria, Promocion, PromocionCategoria, PromocionItem

if TYPE_CHECKING:
    from gastroflow.services.orders import PricedItem

CENT = Decimal("0.01")


def _allocate(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Distribute exact cents proportionally, including the rounding remainder."""
    weight_total = sum(weights)
    if weight_total <= 0:
        return [Decimal("0")] * len(weights)
    raw = [total * weight / weight_total for weight in weights]
    amounts = [amount.quantize(CENT, rounding=ROUND_DOWN) for amount in raw]
    cents = int((total - sum(amounts)) / CENT)
    order = sorted(range(len(weights)), key=lambda index: raw[index] - amounts[index], reverse=True)
    for index in order[:cents]:
        amounts[index] += CENT
    return amounts


def apply_package_promotions(session: Session, priced: list["PricedItem"], contexts: list[str]) -> list["PricedItem"]:
    if not priced:
        return priced
    rows = session.exec(select(Promocion, PromocionItem).join(
        PromocionItem, PromocionItem.promocion_id == Promocion.id,
    ).where(Promocion.activa == True)).all()
    if not rows:
        return priced
    scopes = {(link.promocion_id, link.categoria_id) for link in session.exec(select(PromocionCategoria)).all()}
    category_codes = {category.id: category.codigo for category in session.exec(select(Categoria)).all()}
    packages = {}
    for promotion, component in rows:
        packages.setdefault(promotion.id, (promotion, []))[1].append(component)

    # Only regular retail prices participate; wholesale, Events and half pizzas
    # keep their own pricing rules. Match product AND originating category.
    indexes_by_key = {}
    for index, line in enumerate(priced):
        if (
            line.item.producto_combo_id is None
            and not line.es_especial
            and line.categoria_venta_codigo == contexts[index]
            and contexts[index] not in {"MAYORISTA", "EVENTOS"}
        ):
            indexes_by_key.setdefault((line.item.producto_id, contexts[index]), []).append(index)

    candidates = []
    for promo_id, (promotion, components) in packages.items():
        if promotion.precio_total_promocional is None or promotion.precio_total_promocional < 0:
            continue
        requirements = {}
        for component in components:
            code = category_codes.get(component.categoria_id)
            if (promo_id, component.categoria_id) not in scopes or component.cantidad <= 0:
                break
            requirements[(component.producto_id, code)] = component.cantidad
        else:
            if not requirements:
                continue
            count = min(
                sum(priced[i].item.cantidad for i in indexes_by_key.get(key, [])) // quantity
                for key, quantity in requirements.items()
            )
            if not count:
                continue
            consumed = {}
            for key, required in requirements.items():
                remaining = required * count
                for index in indexes_by_key[key]:
                    units = min(priced[index].item.cantidad, remaining)
                    if units:
                        consumed[index] = units
                        remaining -= units
            indices = sorted(consumed)
            base_prices = [priced[i].precio_base for i in indices]
            if any(price is None for price in base_prices):
                continue
            weights = [priced[i].precio_base * consumed[i] for i in indices]
            package_total = promotion.precio_total_promocional * count
            if package_total >= sum(weights):
                continue
            shares = _allocate(package_total, weights)
            totals = {
                i: shares[position] + priced[i].precio_base * (priced[i].item.cantidad - consumed[i])
                for position, i in enumerate(indices)
            }
            saving = sum(priced[i].subtotal - totals[i] for i in indices)
            if saving > 0:
                candidates.append((saving, promo_id, promotion.nombre, totals))

    result = list(priced)
    used = set()
    # Prefer the largest saving; a line can never receive two promotions.
    for _, _, name, totals in sorted(candidates, key=lambda entry: (-entry[0], entry[1])):
        if used.intersection(totals):
            continue
        for index, subtotal in totals.items():
            result[index] = replace(
                priced[index], subtotal=subtotal.quantize(CENT),
                precio_unitario=(subtotal / priced[index].item.cantidad).quantize(CENT),
                promocion_nombre=name,
            )
        used.update(totals)
    return result
