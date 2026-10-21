from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4
from zoneinfo import ZoneInfo

import reflex as rx
from sqlmodel import Session, select

from gastroflow.data.database import engine
from gastroflow.domain.enums import FormaPago
from gastroflow.domain.errors import DomainError
from gastroflow.models import (
    Agregado,
    AgregadoCategoria,
    AppConfig,
    Categoria,
    ComboRegla,
    Producto,
    ProductoCategoria,
    ZonaEnvio,
)
from gastroflow.services.combo_rules import HALF_PIZZA_CONTEXTS
from gastroflow.services.media_storage import normalize_media_url
from gastroflow.services.orders import (
    DEFAULT_CONTEXT_CODE,
    EVENTS_CONTEXT_CODE,
    EVENTS_MINIMUM_MESSAGE,
    EVENTS_MINIMUM_UNITS,
    WHOLESALE_CONTEXT_CODE,
    OrderAddonInput,
    OrderItemInput,
    OrderPaymentInput,
    OrderService,
    PublicOrderInput,
    normalize_phone,
)
from gastroflow.services.public_catalog import brand_cache, catalog_cache

MONEY_QUANT = Decimal("0.01")
BRAND_SETTINGS_PATH = Path("uploaded_files") / "brand" / "settings.json"
BRAND_LOGO_CONFIG_KEY = "brand.logo_url"
STORE_NAME = os.getenv("STORE_NAME", "")
PIZZERIA_WHATSAPP_PHONE = os.getenv("PIZZERIA_WHATSAPP_PHONE", "")
TRANSFER_TITULAR = os.getenv("TRANSFER_TITULAR", "")
TRANSFER_ALIAS = os.getenv("TRANSFER_ALIAS", "")

def _money_text(value: Decimal | str | int) -> str:
    amount = Decimal(str(value)).quantize(MONEY_QUANT)
    return f"{amount:.2f}".replace(".", ",")


def _parse_money_input(value: str) -> Decimal:
    clean = value.strip().replace("$", "").replace(" ", "")
    if not clean:
        return Decimal("0.00")
    if "," in clean:
        clean = clean.replace(".", "").replace(",", ".")
    return Decimal(clean).quantize(MONEY_QUANT)


def _friendly_error(exc: Exception) -> str:
    text = str(exc)
    if "duplicate key value" in text or "UniqueViolation" in text:
        return "Ese dato ya existe. Revisa lo elegido y proba nuevamente."
    if "ConversionSyntax" in text or "decimal" in text.lower():
        return "No pude leer uno de los numeros. Podes usar coma o punto para decimales."
    if isinstance(exc, DomainError):
        return text
    if isinstance(exc, ValueError):
        return text or "Revisa los datos ingresados."
    return "No se pudo completar la accion. Revisa los datos e intenta nuevamente."


def _read_brand_logo_url() -> str:
    try:
        with Session(engine) as session:
            setting = session.exec(select(AppConfig).where(AppConfig.key == BRAND_LOGO_CONFIG_KEY)).first()
            if setting is not None and setting.value:
                return setting.value
    except Exception:
        pass
    env_logo_url = os.getenv("BRAND_LOGO_URL", "")
    if env_logo_url:
        return env_logo_url
    try:
        data = json.loads(BRAND_SETTINGS_PATH.read_text(encoding="utf-8"))
        return str(data.get("logo_url") or "")
    except Exception:
        return ""


def _normalize_upload_path(value: str | None) -> str:
    return normalize_media_url(value)


def _parse_delivery_date(value: str) -> date:
    clean = value.strip()
    # Blur/form events may arrive with the raw digits before the masked state.
    if clean.isdigit() and len(clean) in {4, 8}:
        clean = _mask_date(clean)
    if "-" in clean and len(clean.split("-")[0]) == 4:
        return date.fromisoformat(clean)
    parts = clean.replace("/", "-").split("-")
    if len(parts) == 2:
        parts.append(str(datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).year))
    day, month, year = parts
    return date(int(year), int(month), int(day))


def _date_text(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def _mask_date(value: str) -> str:
    digits = "".join(char for char in value if char.isdigit())[:8]
    if len(digits) <= 2:
        return digits
    if len(digits) <= 4:
        return f"{digits[:2]}-{digits[2:]}"
    return f"{digits[:2]}-{digits[2:4]}-{digits[4:]}"


def _mask_time(value: str) -> str:
    digits = "".join(char for char in value if char.isdigit())[:4]
    if len(digits) <= 2:
        return digits
    return f"{digits[:2]}:{digits[2:]}"


def _validate_time(value: str) -> None:
    hour, minute = value.split(":")
    if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
        raise ValueError("Ingresa un horario valido con formato HH:MM.")


def _complete_time(value: str) -> str:
    clean = value.strip()
    if clean.isdigit() and len(clean) <= 2:
        clean = f"{int(clean):02d}:00"
    elif clean.isdigit() and len(clean) == 4:
        clean = _mask_time(clean)
    _validate_time(clean)
    hour, minute = clean.split(":")
    if len(minute) != 2:
        raise ValueError("Ingresa un horario valido con formato HH:MM.")
    return f"{int(hour):02d}:{int(minute):02d}"


def _create_public_order(payload: PublicOrderInput):
    with Session(engine) as session:
        return OrderService(session).create_public_order(payload)


def _price_public_cart(inputs: list[OrderItemInput]):
    with Session(engine) as session:
        # Allow building an Events cart incrementally; checkout enforces the minimum.
        return OrderService(session)._price_items(inputs, enforce_event_minimum=False)


def _cart_input(item: dict[str, Any]) -> OrderItemInput:
    return OrderItemInput(
        producto_id=int(item["producto_id"]), cantidad=int(item["cantidad"]),
        producto_combo_id=int(item.get("producto_combo_id") or 0) or None,
        contexto_origen=str(item.get("categoria_codigo") or DEFAULT_CONTEXT_CODE),
        agregados=tuple(
            OrderAddonInput(
                agregado_id=int(addon["id"]),
                cantidad=int(addon["cantidad"]),
            )
            for addon in item.get("agregados", [])
        ),
    )


def _pizza_key(product_id: int, combo_id: int = 0) -> tuple[int, int]:
    return tuple(sorted((product_id, combo_id))) if combo_id else (product_id, 0)


def _public_catalog_rows():
    with Session(engine) as session:
        # Fetch only public products together with their categories in one round trip.
        rows = session.exec(
            select(Categoria, ProductoCategoria, Producto)
            .outerjoin(ProductoCategoria, (
                (ProductoCategoria.categoria_id == Categoria.id)
                & (ProductoCategoria.activo == True)
                & ((ProductoCategoria.visible == True) | (ProductoCategoria.permite_pedido_especial == True))
            ))
            .outerjoin(Producto, (Producto.id == ProductoCategoria.producto_id) & (Producto.activo == True))
            .where(Categoria.visible_cliente == True, Categoria.es_automatica == False, Categoria.activa == True)
        ).all()
        zones = session.exec(select(ZonaEnvio)).all()
        combos = session.exec(select(ComboRegla)).all()
        addons = session.exec(select(Agregado).where(Agregado.activo == True)).all()
        addon_categories = session.exec(select(AgregadoCategoria)).all()
    categories = {category.id: category for category, _, _ in rows}
    products = {product.id: product for _, _, product in rows if product is not None}
    relations = [relation for _, relation, product in rows if relation is not None and product is not None]
    return (
        list(categories.values()), list(products.values()), relations, zones, combos,
        addons, addon_categories,
    )


class BrandState(rx.State):
    logo_url: str = _normalize_upload_path(os.getenv("BRAND_LOGO_URL", ""))

    async def load_brand(self) -> None:
        self.logo_url = _normalize_upload_path(await asyncio.to_thread(_read_brand_logo_url))


class PublicOrderState(rx.State):
    categories: list[dict[str, Any]] = []
    products: list[dict[str, Any]] = []
    visible_products: list[dict[str, Any]] = []
    zones: list[dict[str, Any]] = []
    cart: list[dict[str, Any]] = []
    selected_product: dict[str, Any] = {}
    selected_category_id: str = ""
    view: str = "categories"
    detail_quantity: str = "1"
    pizza_mode: str = "Un solo sabor"
    selected_combo_id: str = ""
    combo_rules: list[dict[str, Any]] = []
    addons: list[dict[str, Any]] = []
    selected_addons: dict[str, int] = {}
    special_catalog: bool = False
    registered_order_is_special: bool = False
    nombre_apellido: str = ""
    telefono: str = ""
    fecha_entrega: str = ""
    horario_entrega: str = ""
    direccion_delivery: str = ""
    delivery_mode: str = "retiro"
    zona_envio_id: str = ""
    selected_zone_name: str = ""
    selected_zone_cost: str = "0,00"
    forma_pago: str = FormaPago.EFECTIVO.value
    pago_efectivo: str = ""
    pago_transferencia: str = ""
    observaciones: str = ""
    cart_total: str = "0.00"
    cart_total_display: str = "0,00"
    order_total_display: str = "0,00"
    message: str = ""
    technical_error: str = ""
    is_submitting: bool = False
    is_updating_cart: bool = False
    registered_order_code: str = ""
    whatsapp_url: str = ""
    submission_token: str = ""
    is_loading_catalog: bool = True
    catalog_error: str = ""

    @rx.var
    def has_special_catalog(self) -> bool:
        return any(str(product["categoria_id"]) == self.selected_category_id and product.get("es_especial", False) for product in self.products)

    @rx.var
    def cart_has_special_orders(self) -> bool:
        return any(item.get("es_especial", False) for item in self.cart)

    @rx.var
    def detail_is_special(self) -> bool:
        return bool(self.selected_product.get("es_especial", False)) or (
            self.pizza_mode == "Mitad y mitad" and any(option["id_str"] == self.selected_combo_id and option["es_especial"] for option in self.combo_options)
        )

    @rx.var
    def combo_options(self) -> list[dict[str, Any]]:
        product = self.selected_product
        if not product or product.get("categoria_codigo") not in HALF_PIZZA_CONTEXTS:
            return []
        by_pair = {tuple(sorted((rule["producto_a_id"], rule["producto_b_id"]))): rule for rule in self.combo_rules}
        options = []
        for other in self.products:
            if other["id"] == product["id"] or str(other["categoria_id"]) != str(product["categoria_id"]):
                continue
            if other.get("es_especial", False) and not self.special_catalog:
                continue
            rule = by_pair.get(tuple(sorted((product["id"], other["id"]))))
            if rule is None:
                continue
            price = OrderService._combo_price(ComboRegla(**rule), Decimal(product["precio"]), Decimal(other["precio"])).quantize(MONEY_QUANT)
            options.append({"id": other["id"], "id_str": str(other["id"]), "nombre": other["nombre"], "es_especial": other.get("es_especial", False),
                "precio": str(price), "precio_display": _money_text(price)})
        return options

    @rx.var
    def selected_combo_name(self) -> str:
        return next((option["nombre"] for option in self.combo_options if option["id_str"] == self.selected_combo_id), "")

    @rx.var
    def detail_price_display(self) -> str:
        if self.pizza_mode == "Mitad y mitad":
            return next((option["precio_display"] for option in self.combo_options if option["id_str"] == self.selected_combo_id), "—")
        return _money_text(self.selected_product.get("precio", "0"))

    @rx.var
    def available_addons(self) -> list[dict[str, Any]]:
        if not self.selected_product:
            return []
        category_id = str(self.selected_product.get("categoria_id", ""))
        return [
            {
                **addon,
                "cantidad": self.selected_addons.get(addon["id_str"], 0),
            }
            for addon in self.addons
            if category_id in addon["categoria_ids"]
        ]

    @rx.var
    def events_minimum_message(self) -> str:
        units = sum(
            int(item["cantidad"]) for item in self.cart
            if item.get("categoria_codigo") == EVENTS_CONTEXT_CODE
        )
        has_events = any(item.get("categoria_codigo") == EVENTS_CONTEXT_CODE for item in self.cart)
        return EVENTS_MINIMUM_MESSAGE if has_events and units < EVENTS_MINIMUM_UNITS else ""

    async def load_catalog(self):
        self.message = ""
        self.technical_error = ""
        self.is_loading_catalog = True
        self.catalog_error = ""
        yield
        try:
            # The logo must not hold up the catalog in a separate event first.
            rows, logo_url = await asyncio.gather(
                asyncio.to_thread(catalog_cache.get, _public_catalog_rows),
                asyncio.to_thread(brand_cache.get, _read_brand_logo_url),
            )
            brand = await self.get_state(BrandState)
            brand.logo_url = _normalize_upload_path(logo_url)
            if len(rows) == 5:
                categories, products, product_categories, zones, combos = rows
                addons, addon_categories = [], []
            else:
                categories, products, product_categories, zones, combos, addons, addon_categories = rows
        except Exception as exc:
            self.is_loading_catalog = False
            self.catalog_error = "No pudimos cargar el catálogo. Presioná Reintentar."
            self.technical_error = str(exc)
            return

        category_names = {category.id: category.nombre for category in categories}
        self.combo_rules = [rule.model_dump() for rule in combos]
        categories_by_addon: dict[int, list[str]] = {}
        for link in addon_categories:
            categories_by_addon.setdefault(link.agregado_id, []).append(str(link.categoria_id))
        self.addons = [
            {
                "id": addon.id,
                "id_str": str(addon.id),
                "nombre": addon.nombre,
                "precio": str(addon.precio),
                "precio_display": _money_text(addon.precio),
                "categoria_ids": categories_by_addon.get(addon.id or 0, []),
            }
            for addon in addons
        ]
        category_codes = {category.id: category.codigo for category in categories}
        product_by_id = {product.id: product for product in products if product.activo}
        product_count_by_category: dict[int, int] = {}
        for product_category in product_categories:
            if product_category.categoria_id in category_names and product_category.producto_id in product_by_id and product_category.visible and not product_category.permite_pedido_especial:
                product_count_by_category[product_category.categoria_id] = (
                    product_count_by_category.get(product_category.categoria_id, 0) + 1
                )

        self.categories = [
            {
                "id": category.id,
                "codigo": category.codigo,
                "nombre": category.nombre,
                "descripcion": category.descripcion_publica or "",
                "foto": _normalize_upload_path(category.foto_url),
                "orden": category.orden,
                "total": product_count_by_category.get(category.id or 0, 0),
            }
            for category in sorted(categories, key=lambda item: (item.orden, item.nombre))
        ]
        self.products = [
            {
                "id": product.id,
                "categoria_id": product_category.categoria_id,
                "categoria": category_names.get(product_category.categoria_id, ""),
                "categoria_codigo": category_codes.get(product_category.categoria_id, ""),
                "codigo": product.codigo,
                "nombre": product.nombre,
                "precio": str(product_category.precio),
                "descripcion": (
                    product_category.descripcion_publica
                    or product.descripcion
                    or "Producto artesanal listo para sumar a tu pedido."
                ),
                "foto": _normalize_upload_path(product_category.foto_url or ((product.fotos or [""])[0] if product.fotos else "")),
                "orden": product_category.orden,
                "destacado": product_category.destacado,
                "es_especial": product_category.permite_pedido_especial,
            }
            for product_category in sorted(product_categories, key=lambda item: (item.orden, item.id or 0))
            if product_category.categoria_id in category_names
            and (product := product_by_id.get(product_category.producto_id)) is not None
            and (product_category.visible or product_category.permite_pedido_especial)
        ]
        self.zones = [
            {
                "id": zone.id,
                "id_str": str(zone.id),
                "nombre": zone.nombre,
                "costo": str(zone.costo),
                "costo_display": _money_text(zone.costo),
            }
            for zone in zones
        ]
        if not self.view:
            self.view = "categories"
        self.is_loading_catalog = False

    def show_categories(self) -> None:
        self.special_catalog = False
        self.view = "categories"
        self.selected_category_id = ""
        self.visible_products = []
        self.selected_product = {}
        self.pizza_mode = "Un solo sabor"
        self.selected_combo_id = ""
        self.selected_addons = {}
        self.message = ""

    def show_category(self, category_id: int) -> None:
        self.special_catalog = False
        self.selected_category_id = str(category_id)
        self.visible_products = [
            product for product in self.products if str(product["categoria_id"]) == str(category_id) and not product.get("es_especial", False)
        ]
        self.selected_product = {}
        self.pizza_mode = "Un solo sabor"
        self.selected_combo_id = ""
        self.selected_addons = {}
        self.view = "products"
        self.message = ""

    def show_special_category(self, category_id: int) -> None:
        self.show_category(category_id)
        self.special_catalog = True
        self.visible_products = [product for product in self.products
            if str(product["categoria_id"]) == str(category_id) and product.get("es_especial", False)]

    def open_product(self, product_id: int, category_id: int) -> None:
        # A product can have a different presentation and price in each category.
        # Reject stale clicks from a category that is no longer being viewed.
        if str(category_id) != self.selected_category_id:
            return
        product = next((
            item for item in self.products
            if str(item["id"]) == str(product_id)
            and str(item["categoria_id"]) == str(category_id)
        ), {})
        if not product or (product.get("es_especial", False) and not self.special_catalog):
            self.selected_product = {}
            self.view = "products"
            self.message = "Este producto no está disponible en la categoría seleccionada."
            return
        self.selected_product = product
        self.pizza_mode = "Un solo sabor"
        self.selected_combo_id = ""
        self.selected_addons = {}
        self.detail_quantity = "1"
        self.view = "detail"
        self.message = ""

    def set_pizza_mode(self, value: str) -> None:
        if value not in {"Un solo sabor", "Mitad y mitad"}:
            return
        if value == "Mitad y mitad" and not self.combo_options:
            return
        self.pizza_mode = value
        self.selected_combo_id = ""
        self.message = ""

    def select_combo(self, product_id: str) -> None:
        if any(option["id_str"] == product_id for option in self.combo_options):
            self.selected_combo_id = product_id
            self.message = ""

    def increment_selected_addon(self, addon_id: int) -> None:
        if not any(addon["id"] == addon_id for addon in self.available_addons):
            return
        selected = dict(self.selected_addons)
        key = str(addon_id)
        selected[key] = selected.get(key, 0) + 1
        self.selected_addons = selected

    def decrement_selected_addon(self, addon_id: int) -> None:
        selected = dict(self.selected_addons)
        key = str(addon_id)
        quantity = selected.get(key, 0) - 1
        if quantity > 0:
            selected[key] = quantity
        else:
            selected.pop(key, None)
        self.selected_addons = selected

    async def add_selected_to_cart(self):
        if self.is_updating_cart or self.registered_order_code or self.is_submitting:
            return
        if not self.selected_product:
            self.message = "Selecciona un producto."
            return
        try:
            quantity = int(self.detail_quantity)
            if quantity <= 0:
                raise ValueError
        except ValueError:
            self.message = "La cantidad debe ser mayor a cero."
            return

        product_id = int(self.selected_product["id"])
        combo_id = 0
        price = Decimal(str(self.selected_product["precio"]))
        name = self.selected_product["nombre"]
        if self.pizza_mode == "Mitad y mitad":
            option = next((option for option in self.combo_options if option["id_str"] == self.selected_combo_id), None)
            if option is None:
                self.message = "Elegí el sabor de la otra mitad."
                return
            combo_id = int(option["id"])
            price = Decimal(option["precio"])
            # Canonical order makes A/B and B/A the same cart line.
            if product_id > combo_id:
                name = f"Mitad {option['nombre']} / mitad {name}"
                product_id, combo_id = combo_id, product_id
            else:
                name = f"Mitad {name} / mitad {option['nombre']}"
        selected_addons = [
            {
                **addon,
                "cantidad": self.selected_addons.get(addon["id_str"], 0),
            }
            for addon in self.available_addons
            if self.selected_addons.get(addon["id_str"], 0) > 0
        ]
        addon_key = tuple(sorted(
            (int(addon["id"]), int(addon["cantidad"])) for addon in selected_addons
        ))
        cart = list(self.cart)
        for index, item in enumerate(cart):
            if (
                _pizza_key(int(item["producto_id"]), int(item.get("producto_combo_id") or 0)) == _pizza_key(product_id, combo_id)
                and item["categoria_codigo"] == self.selected_product["categoria_codigo"]
                and tuple(sorted(
                    (int(addon["id"]), int(addon["cantidad"]))
                    for addon in item.get("agregados", [])
                )) == addon_key
            ):
                item["cantidad"] = int(item["cantidad"]) + quantity
                cart[index] = item
                break
        else:
            cart.append(
                {
                    "producto_id": product_id,
                    "producto_combo_id": combo_id,
                    "es_especial": self.detail_is_special,
                    "nombre": name,
                    "categoria": self.selected_product["categoria"],
                    "categoria_display": self.selected_product["categoria"],
                    "categoria_codigo": self.selected_product["categoria_codigo"],
                    "precio": str(price),
                    "precio_display": _money_text(price),
                    "cantidad": quantity,
                    "subtotal": str(price * Decimal(quantity)),
                    "subtotal_display": _money_text(price * Decimal(quantity)),
                    "base_subtotal_display": _money_text(price * Decimal(quantity)),
                    "discount": "0.00",
                    "discount_display": "0,00",
                    "promo_label": "",
                    "agregados": selected_addons,
                    "addon_key": "|".join(
                        f"{addon_id}:{addon_quantity}"
                        for addon_id, addon_quantity in addon_key
                    ),
                    "agregados_display": ", ".join(
                        f"{addon['cantidad']}x {addon['nombre']}" for addon in selected_addons
                    ),
                    "foto": self.selected_product.get("foto", ""),
                }
            )
        self.cart = cart
        self.is_updating_cart = True
        yield
        try:
            await self._refresh_cart_total()
        finally:
            self.is_updating_cart = False
        self.message = "Se agregó al carrito correctamente."
        self.selected_addons = {}
        self.view = "products"
        yield rx.toast.success(self.message)

    async def remove_cart_item(
        self,
        product_id: int,
        category_code: str,
        combo_product_id: int = 0,
        addon_key: str | None = None,
    ):
        if self.is_updating_cart or self.registered_order_code or self.is_submitting:
            return
        self.cart = [
            item for item in self.cart
            if not (
                _pizza_key(int(item["producto_id"]), int(item.get("producto_combo_id") or 0)) == _pizza_key(int(product_id), int(combo_product_id))
                and item["categoria_codigo"] == category_code
                and (addon_key is None or item.get("addon_key", "") == addon_key)
            )
        ]
        self.is_updating_cart = True
        yield
        try:
            await self._refresh_cart_total()
        finally:
            self.is_updating_cart = False
        self.message = ""

    def show_cart(self) -> None:
        self.view = "cart"
        self.message = ""

    def set_fecha_entrega(self, value: str) -> None:
        self.fecha_entrega = _mask_date(value)

    def set_horario_entrega(self, value: str) -> None:
        self.horario_entrega = _mask_time(value)

    def complete_delivery_date(self, value: str) -> None:
        # Keep partial edits intact. Infer the optional year only at checkout.
        self.fecha_entrega = _mask_date(value)

    def complete_delivery_time(self, value: str) -> None:
        # Blur can carry raw digits. Keep the mask without completing partial edits.
        self.horario_entrega = _mask_time(value)

    def set_delivery_mode(self, value: str) -> None:
        self.delivery_mode = value
        if value == "retiro":
            self.direccion_delivery = ""
            self.zona_envio_id = ""
            self.selected_zone_name = ""
            self.selected_zone_cost = "0,00"
        self._refresh_order_total()

    def select_zone(self, zone_id: int) -> None:
        selected = next((zone for zone in self.zones if str(zone["id"]) == str(zone_id)), {})
        self.zona_envio_id = str(zone_id)
        self.selected_zone_name = selected.get("nombre", "")
        self.selected_zone_cost = selected.get("costo_display", "0,00")
        self._refresh_order_total()

    def set_forma_pago(self, value: str) -> None:
        if value not in {item.value for item in FormaPago}:
            return
        self.forma_pago = value
        if value != FormaPago.MIXTO.value:
            self.pago_efectivo = ""
            self.pago_transferencia = ""

    def set_pago_efectivo(self, value: str) -> None:
        self.pago_efectivo = value

    def set_pago_transferencia(self, value: str) -> None:
        self.pago_transferencia = value

    async def submit_order(self, form_data: dict[str, Any]):
        if self.is_submitting or self.registered_order_code or self.is_updating_cart:
            return
        if self.events_minimum_message:
            self.message = self.events_minimum_message
            yield rx.toast.error(self.message)
            return
        # Read the actual inputs, including the last keystroke still awaiting debounce.
        for field in (
            "nombre_apellido", "telefono", "fecha_entrega", "horario_entrega",
            "direccion_delivery", "observaciones", "pago_efectivo", "pago_transferencia",
        ):
            if field in form_data:
                setattr(self, field, str(form_data[field]))
        self.is_submitting = True
        self.message = ""
        self.technical_error = ""
        yield
        try:
            if not self.cart:
                raise ValueError("Tu pedido esta vacio.")
            normalized_phone = normalize_phone(self.telefono)
            self.telefono = normalized_phone
            delivery_date = _parse_delivery_date(self.fecha_entrega)
            self.fecha_entrega = _date_text(delivery_date)
            self.horario_entrega = _complete_time(self.horario_entrega)
            if self.delivery_mode == "delivery" and not self.zona_envio_id:
                raise ValueError("Selecciona una zona de envio.")
            items = [_cart_input(item) for item in self.cart]
            payments: tuple[OrderPaymentInput, ...] = ()
            if self.forma_pago == FormaPago.MIXTO.value:
                cash = _parse_money_input(self.pago_efectivo)
                transfer = _parse_money_input(self.pago_transferencia)
                if cash <= 0 or transfer <= 0:
                    raise ValueError("Ingresa importes mayores a cero para efectivo y transferencia.")
                payments = (
                    OrderPaymentInput(FormaPago.EFECTIVO, cash),
                    OrderPaymentInput(FormaPago.TRANSFERENCIA, transfer),
                )
            if not self.submission_token:
                self.submission_token = str(uuid4())
            payload = PublicOrderInput(
                submission_token=self.submission_token,
                nombre_apellido=self.nombre_apellido,
                telefono=self.telefono,
                fecha_entrega=delivery_date,
                horario_entrega=time.fromisoformat(self.horario_entrega),
                direccion_delivery=self.direccion_delivery if self.delivery_mode == "delivery" else "Retiro en el local",
                zona_envio_id=int(self.zona_envio_id) if self.delivery_mode == "delivery" and self.zona_envio_id else None,
                forma_pago=FormaPago(self.forma_pago),
                pagos=payments,
                observaciones=self.observaciones or None,
                items=items,
            )
            result = await asyncio.to_thread(_create_public_order, payload)
            # Mark success before generating the link: even a later error must not resave.
            self.registered_order_code = result.pedido.codigo
            self.registered_order_is_special = getattr(result, "es_especial", self.cart_has_special_orders)
            self.whatsapp_url = self._build_whatsapp_url(result.pedido.codigo, result.pedido.monto_total)
            self.message = (
                "Recibimos tu solicitud de pedido especial. El precio es definitivo; el local debe aceptar la disponibilidad. No realices el pago hasta recibir esa aceptación."
                if self.registered_order_is_special else
                "Su pedido se registró correctamente. Te enviaremos a WhatsApp para que confirmes tu pedido."
            )
            yield
            # Same-tab navigation does not depend on popup permissions.
            yield rx.call_script(f"window.location.assign({json.dumps(self.whatsapp_url)})")
        except Exception as exc:
            self.message = _friendly_error(exc)
            self.technical_error = str(exc)
            yield rx.toast.error(self.message)
        finally:
            self.is_submitting = False

    async def _refresh_cart_total(self) -> None:
        cart = [dict(item) for item in self.cart]
        for cart_item in cart:
            cart_item["categoria_display"] = cart_item["categoria"]
        if cart:
            try:
                inputs = [_cart_input(item) for item in cart]
                priced_items = await asyncio.to_thread(_price_public_cart, inputs)
                for cart_item, priced_item in zip(cart, priced_items):
                    cart_item["es_especial"] = getattr(priced_item, "es_especial", cart_item.get("es_especial", False))
                    if priced_item.categoria_venta_codigo == WHOLESALE_CONTEXT_CODE:
                        cart_item["categoria_display"] = f"{cart_item['categoria']} / Mayorista"
                    base_unit = Decimal(str(cart_item["precio"]))
                    final_unit = Decimal(str(priced_item.precio_unitario))
                    quantity = Decimal(str(cart_item["cantidad"]))
                    base_subtotal = base_unit * quantity
                    subtotal = Decimal(str(getattr(priced_item, "total", priced_item.subtotal)))
                    addons_subtotal = sum(
                        (Decimal(str(addon.subtotal)) for addon in getattr(priced_item, "agregados", ())),
                        Decimal("0.00"),
                    )
                    discount = base_subtotal - Decimal(str(priced_item.subtotal))
                    cart_item["precio_final"] = str(final_unit)
                    cart_item["subtotal"] = str(subtotal)
                    cart_item["subtotal_display"] = _money_text(subtotal)
                    cart_item["base_subtotal_display"] = _money_text(base_subtotal)
                    cart_item["discount"] = str(discount)
                    cart_item["discount_display"] = _money_text(discount)
                    cart_item["promo_label"] = (
                        f"{getattr(priced_item, 'promocion_nombre', '') or 'Promo aplicada'}: $-{_money_text(discount)}"
                        if discount > 0 else ""
                    )
                    cart_item["agregados_display"] = ", ".join(
                        f"{addon.cantidad}x {addon.nombre}" for addon in getattr(priced_item, "agregados", ())
                    )
                    cart_item["agregados_subtotal_display"] = _money_text(addons_subtotal)
            except Exception as exc:
                if isinstance(exc, ValueError):
                    self.message = _friendly_error(exc)
                self.technical_error = str(exc)
                for cart_item in cart:
                    cart_item["categoria_display"] = cart_item["categoria"]
                    product_subtotal = Decimal(str(cart_item["precio"])) * Decimal(str(cart_item["cantidad"]))
                    addons_subtotal = sum(
                        Decimal(str(addon["precio"])) * Decimal(str(addon["cantidad"]))
                        for addon in cart_item.get("agregados", [])
                    )
                    subtotal = product_subtotal + addons_subtotal
                    cart_item["subtotal"] = str(subtotal)
                    cart_item["subtotal_display"] = _money_text(subtotal)
                    cart_item["base_subtotal_display"] = _money_text(subtotal)
                    cart_item["discount"] = "0.00"
                    cart_item["discount_display"] = "0,00"
                    cart_item["promo_label"] = ""

        items_total = sum((Decimal(str(item["subtotal"])) for item in cart), Decimal("0.00"))
        shipping = self._selected_shipping_cost()
        order_total = items_total + shipping
        self.cart = cart
        self.cart_total = str(items_total.quantize(MONEY_QUANT))
        self.cart_total_display = _money_text(items_total)
        self.order_total_display = _money_text(order_total)

    def _refresh_order_total(self) -> None:
        self.order_total_display = _money_text(Decimal(self.cart_total) + self._selected_shipping_cost())

    def start_new_order(self) -> None:
        if self.is_submitting:
            return
        self.cart = []
        self.cart_total = "0.00"
        self.cart_total_display = "0,00"
        self.registered_order_code = ""
        self.registered_order_is_special = False
        self.whatsapp_url = ""
        self.submission_token = ""
        self.message = ""
        self.telefono = ""
        self.delivery_mode = "retiro"
        self.zona_envio_id = ""
        self.selected_zone_name = ""
        self.selected_zone_cost = "0,00"
        self.forma_pago = FormaPago.EFECTIVO.value
        self.pago_efectivo = ""
        self.pago_transferencia = ""
        self._refresh_order_total()
        self.view = "categories"

    def _selected_shipping_cost(self) -> Decimal:
        if self.delivery_mode != "delivery" or not self.zona_envio_id:
            return Decimal("0.00")
        selected = next((zone for zone in self.zones if str(zone["id"]) == self.zona_envio_id), None)
        return Decimal(str(selected["costo"])) if selected else Decimal("0.00")

    def _build_whatsapp_url(self, pedido_codigo: str, total: Decimal) -> str:
        special = self.registered_order_is_special or self.cart_has_special_orders
        now = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).strftime("%d-%m-%Y - %H:%Mhs")
        delivery_label = "Delivery" if self.delivery_mode == "delivery" else "Retiro del local"
        lines = [
            "¡Hola! Te paso el resumen de mi pedido",
            "",
            f"Pedido: #{pedido_codigo}",
            f"Tienda: {STORE_NAME}",
            f"Fecha del pedido: {now}",
            f"Fecha de entrega: {self.fecha_entrega}",
            f"Nombre: {self.nombre_apellido}",
                f"Telefono: {self.telefono}",
                f"Horario ideal de entrega: {self.horario_entrega}hs",
                "",
                f"Forma de pago: {self._payment_summary()}",
        ]
        if special:
            lines.extend(["", "PEDIDO ESPECIAL — PENDIENTE DE ACEPTACIÓN DE DISPONIBILIDAD",
                "El precio indicado es definitivo. No realizar el pago hasta que el local acepte la disponibilidad."])
        if self.forma_pago == FormaPago.TRANSFERENCIA.value and not special:
            lines.extend(
                [
                    "",
                    "Datos para la transferencia",
                    f"Titular: {TRANSFER_TITULAR}",
                    f"Alias: {TRANSFER_ALIAS}",
                    "Realiza la transferencia y luego envianos el comprobante por este chat.",
                    "Esperar confirmacion antes de transferir.",
                ]
            )
        lines.extend(
            [
                "",
                f"Total: ${_money_text(total)}",
                "",
                f"Entrega: {delivery_label}",
            ]
        )
        if self.delivery_mode == "delivery":
            lines.append(f"Direccion: {self.direccion_delivery}")
            lines.append(f"Zona: {self.selected_zone_name}")
        if self.observaciones:
            lines.append(f"Referencia/observaciones: {self.observaciones}")
        lines.extend(["", "Mi pedido es", ""])
        categories = []
        for item in self.cart:
            category = item.get("categoria_display", item.get("categoria", "Productos"))
            if category not in categories:
                categories.append(category)
        for category in categories:
            lines.append(f"{category.upper()} ({category.upper()})")
            for item in self.cart:
                if item.get("categoria_display", item.get("categoria", "Productos")) != category:
                    continue
                lines.append(
                    f"{item['cantidad']}x {item['nombre']}: ${item['subtotal_display']}"
                )
                if item.get("agregados_display"):
                    lines.append(f"  Agregados: {item['agregados_display']}")
                if item.get("es_especial", False):
                    lines.append("Pedido especial — disponibilidad sujeta a aceptación del local")
                if item.get("promo_label"):
                    lines.append(item["promo_label"])
        lines.extend(
            [
                "",
                f"Subtotal: ${self.cart_total_display}",
                f"Costo de envio: +${self.selected_zone_cost if self.delivery_mode == 'delivery' else '0,00'}",
                f"TOTAL: ${_money_text(total)}",
                "",
                "Espero la aceptación de disponibilidad de mi pedido especial" if special else "Espero tu respuesta para confirmar mi pedido",
            ]
        )
        phone = "".join(char for char in PIZZERIA_WHATSAPP_PHONE if char.isdigit())
        target = f"https://wa.me/{phone}" if phone else "https://wa.me/"
        return f"{target}?text={quote(chr(10).join(lines))}"

    def _payment_summary(self) -> str:
        if self.forma_pago == FormaPago.TRANSFERENCIA.value:
            return "Transferencia"
        if self.forma_pago == FormaPago.MIXTO.value:
            return (
                f"Mixto (Efectivo ${self.pago_efectivo or '0'} + "
                f"Transferencia ${self.pago_transferencia or '0'})"
            )
        return "Efectivo"
