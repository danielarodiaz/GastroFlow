from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from sqlmodel import Session, select

from gastroflow.data.database import engine
from gastroflow.domain.enums import ReglaPrecioCombo, TipoPromocion, UnidadVenta
from gastroflow.models import Categoria, ComboRegla, Producto, ProductoCategoria, Promocion, PromocionProducto, ZonaEnvio

SEED_PATH = Path(__file__).resolve().parents[1] / "gastroflow" / "seed" / "catalog_seed.json"


def first_or_create(session: Session, model: type, lookup: dict, values: dict):
    statement = select(model)
    for field, value in lookup.items():
        statement = statement.where(getattr(model, field) == value)
    instance = session.exec(statement).first()
    if instance is not None:
        return instance

    instance = model(**lookup, **values)
    session.add(instance)
    session.flush()
    return instance


def main() -> None:
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    with Session(engine) as session:
        categories: dict[str, Categoria] = {}
        products: dict[str, Producto] = {}

        for row in data["categories"]:
            categories[row["codigo"]] = first_or_create(
                session,
                Categoria,
                {"codigo": row["codigo"]},
                {
                    "nombre": row["nombre"],
                    "descripcion_publica": row.get("descripcion_publica"),
                    "foto_url": row.get("foto_url"),
                    "orden": row.get("orden", 0),
                    "visible_cliente": row.get("visible_cliente", True),
                    "es_automatica": row.get("es_automatica", False),
                    "cantidad_minima_total": row.get("cantidad_minima_total"),
                    "prioridad": row.get("prioridad", 0),
                    "acumulable": row.get("acumulable", False),
                    "activa": row.get("activa", True),
                },
            )

        for row in data["products"]:
            products[row["codigo"]] = first_or_create(
                session,
                Producto,
                {"codigo": row["codigo"]},
                {
                    "nombre": row["nombre"],
                    "descripcion": row["descripcion"],
                    "fotos": row["fotos"],
                    "unidad_venta": UnidadVenta[row["unidad_venta"]],
                    "activo": row.get("activo", True),
                },
            )
            for price_row in row["category_prices"]:
                first_or_create(
                    session,
                    ProductoCategoria,
                    {
                        "producto_id": products[row["codigo"]].id,
                        "categoria_id": categories[price_row["categoria_codigo"]].id,
                    },
                    {
                        "precio": Decimal(price_row["precio"]),
                        "descripcion_publica": price_row.get("descripcion_publica"),
                        "foto_url": price_row.get("foto_url"),
                        "visible": price_row.get("visible", True),
                        "orden": price_row.get("orden", 0),
                        "destacado": price_row.get("destacado", False),
                        "activo": price_row.get("activo", True),
                    },
                )

        for row in data["promotions"]:
            promotion = first_or_create(
                session,
                Promocion,
                {"codigo": row["codigo"]},
                {
                    "nombre": row["nombre"],
                    "tipo": TipoPromocion[row["tipo"]],
                    "cantidad_minima": row["cantidad_minima"],
                    "precio_unitario_promocional": Decimal(row["precio_unitario_promocional"]),
                    "activa": row["activa"],
                },
            )
            for product_code in row["productos_elegibles"]:
                first_or_create(
                    session,
                    PromocionProducto,
                    {
                        "promocion_id": promotion.id,
                        "producto_id": products[product_code].id,
                    },
                    {},
                )

        for row in data["delivery_zones"]:
            first_or_create(
                session,
                ZonaEnvio,
                {"nombre": row["nombre"]},
                {"costo": Decimal(row["costo"])},
            )

        for row in data["combo_rules"]:
            first_or_create(
                session,
                ComboRegla,
                {
                    "producto_a_id": products[row["producto_a_codigo"]].id,
                    "producto_b_id": products[row["producto_b_codigo"]].id,
                },
                {
                    "requiere_confirmacion": row["requiere_confirmacion"],
                    "regla_precio": ReglaPrecioCombo[row["regla_precio"]],
                    "precio_fijo_combo": (
                        Decimal(row["precio_fijo_combo"])
                        if row["precio_fijo_combo"] is not None
                        else None
                    ),
                },
            )

        session.commit()

    print("Catalogo inicial cargado.")


if __name__ == "__main__":
    main()
