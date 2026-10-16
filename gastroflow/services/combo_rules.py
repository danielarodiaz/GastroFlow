"""Idempotent registration of the ten approved half-pizza combinations."""

from itertools import combinations
import unicodedata

from sqlmodel import Session, select

from gastroflow.domain.enums import ReglaPrecioCombo
from gastroflow.domain.errors import ValidationError
from gastroflow.models import ComboRegla, Producto

HALF_PIZZA_CONTEXTS = frozenset({"LISTA_HORNO", "LISTA_COMER"})
HALF_PIZZA_FLAVORS = ("Muzzarella", "Especial", "Calabresa", "Fugazzetta", "Napolitana")


def _flavor_name(name: str) -> str:
    clean = " ".join(unicodedata.normalize("NFKC", name).casefold().split())
    return "fugazzetta" if clean == "fugazzeta" else clean


def ensure_half_pizza_rules(session: Session) -> list[ComboRegla]:
    products = session.exec(select(Producto).where(Producto.activo == True)).all()
    selected = []
    for flavor in HALF_PIZZA_FLAVORS:
        matches = [product for product in products if _flavor_name(product.nombre) == _flavor_name(flavor)]
        if len(matches) != 1:
            raise ValidationError(f"Se requiere un único producto activo para {flavor}; encontrados: {len(matches)}.")
        selected.append(matches[0])
    existing = {}
    for rule in session.exec(select(ComboRegla)).all():
        key = tuple(sorted((rule.producto_a_id, rule.producto_b_id)))
        if key in existing:
            raise ValidationError("Hay combinaciones duplicadas en combo_regla; revisá los pares invertidos.")
        existing[key] = rule
    rules = []
    for first, second in combinations(selected, 2):
        key = tuple(sorted((first.id, second.id)))
        rule = existing.get(key) or ComboRegla(producto_a_id=key[0], producto_b_id=key[1], regla_precio=ReglaPrecioCombo.PROMEDIO)
        rule.regla_precio = ReglaPrecioCombo.PROMEDIO
        rule.precio_fijo_combo = None
        rule.requiere_confirmacion = False
        session.add(rule)
        rules.append(rule)
    session.flush()
    return rules
