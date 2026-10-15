from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime
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
from gastroflow.models import AppConfig, Categoria, Producto, ProductoCategoria, ZonaEnvio
from gastroflow.services.media_storage import normalize_media_url
from gastroflow.services.orders import (
    DEFAULT_CONTEXT_CODE,
    OrderItemInput,
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
    if "-" in clean and len(clean.split("-")[0]) == 4:
        return date.fromisoformat(clean)
    parts = clean.split("/")
    if len(parts) == 2:
        parts.append(str(datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).year))
    day, month, year = parts
    return date(int(year), int(month), int(day))


def _date_text(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def _mask_date(value: str) -> str:
    digits = "".join(char for char in value if char.isdigit())[:8]
    if len(digits) <= 2:
        return digits
    if len(digits) <= 4:
        return f"{digits[:2]}/{digits[2:]}"
    return f"{digits[:2]}/{digits[2:4]}/{digits[4:]}"


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
    _validate_time(clean)
    return clean


def _create_public_order(payload: PublicOrderInput):
    with Session(engine) as session:
        return OrderService(session).create_public_order(payload)


def _price_public_cart(inputs: list[OrderItemInput]):
    with Session(engine) as session:
        return OrderService(session)._price_items(inputs)


def _public_catalog_rows():
    with Session(engine) as session:
        # Fetch only public products together with their categories in one round trip.
        rows = session.exec(
            select(Categoria, ProductoCategoria, Producto)
            .outerjoin(ProductoCategoria, (
                (ProductoCategoria.categoria_id == Categoria.id)
                & (ProductoCategoria.activo == True)
                & (ProductoCategoria.visible == True)
            ))
            .outerjoin(Producto, (Producto.id == ProductoCategoria.producto_id) & (Producto.activo == True))
            .where(Categoria.visible_cliente == True, Categoria.es_automatica == False, Categoria.activa == True)
        ).all()
        zones = session.exec(select(ZonaEnvio)).all()
    categories = {category.id: category for category, _, _ in rows}
    products = {product.id: product for _, _, product in rows if product is not None}
    relations = [relation for _, relation, product in rows if relation is not None and product is not None]
    return list(categories.values()), list(products.values()), relations, zones


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
    nombre_apellido: str = ""
    telefono: str = ""
    telefono_confirmacion: str = ""
    fecha_entrega: str = ""
    horario_entrega: str = ""
    direccion_delivery: str = ""
    delivery_mode: str = "retiro"
    zona_envio_id: str = ""
    selected_zone_name: str = ""
    selected_zone_cost: str = "0,00"
    forma_pago: str = FormaPago.EFECTIVO.value
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
            categories, products, product_categories, zones = rows
        except Exception as exc:
            self.is_loading_catalog = False
            self.catalog_error = "No pudimos cargar el catálogo. Presioná Reintentar."
            self.technical_error = str(exc)
            return

        category_names = {category.id: category.nombre for category in categories}
        category_codes = {category.id: category.codigo for category in categories}
        product_by_id = {product.id: product for product in products if product.activo}
        product_count_by_category: dict[int, int] = {}
        for product_category in product_categories:
            if product_category.categoria_id in category_names and product_category.producto_id in product_by_id:
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
            }
            for product_category in sorted(product_categories, key=lambda item: (item.orden, item.id or 0))
            if product_category.categoria_id in category_names
            and (product := product_by_id.get(product_category.producto_id)) is not None
            and product_category.visible
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
        self.view = "categories"
        self.selected_category_id = ""
        self.visible_products = []
        self.selected_product = {}
        self.message = ""

    def show_category(self, category_id: int) -> None:
        self.selected_category_id = str(category_id)
        self.visible_products = [
            product for product in self.products if str(product["categoria_id"]) == str(category_id)
        ]
        self.selected_product = {}
        self.view = "products"
        self.message = ""

    def open_product(self, product_id: int) -> None:
        product = next((item for item in self.products if str(item["id"]) == str(product_id)), {})
        self.selected_product = product
        self.detail_quantity = "1"
        self.view = "detail"
        self.message = ""

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
        cart = list(self.cart)
        for index, item in enumerate(cart):
            if int(item["producto_id"]) == product_id:
                item["cantidad"] = int(item["cantidad"]) + quantity
                cart[index] = item
                break
        else:
            price = Decimal(str(self.selected_product["precio"]))
            cart.append(
                {
                    "producto_id": product_id,
                    "nombre": self.selected_product["nombre"],
                    "categoria": self.selected_product["categoria"],
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
        self.view = "products"
        yield rx.toast.success(self.message)

    async def remove_cart_item(self, product_id: int):
        if self.is_updating_cart or self.registered_order_code or self.is_submitting:
            return
        self.cart = [item for item in self.cart if int(item["producto_id"]) != int(product_id)]
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
        try:
            self.fecha_entrega = _date_text(_parse_delivery_date(value))
        except ValueError:
            self.fecha_entrega = value

    def complete_delivery_time(self, value: str) -> None:
        try:
            self.horario_entrega = _complete_time(value)
        except ValueError:
            self.horario_entrega = value

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
        self.forma_pago = value

    async def submit_order(self, form_data: dict[str, Any]):
        if self.is_submitting or self.registered_order_code or self.is_updating_cart:
            return
        # Read the actual inputs, including the last keystroke still awaiting debounce.
        for field in ("nombre_apellido", "telefono", "telefono_confirmacion", "fecha_entrega", "horario_entrega", "direccion_delivery", "observaciones"):
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
            confirmation_phone = normalize_phone(self.telefono_confirmacion)
            if normalized_phone != confirmation_phone:
                raise ValueError("Los números de celular no coinciden. Revisalos antes de continuar.")
            self.telefono = normalized_phone
            self.telefono_confirmacion = normalized_phone
            delivery_date = _parse_delivery_date(self.fecha_entrega)
            self.fecha_entrega = _date_text(delivery_date)
            self.horario_entrega = _complete_time(self.horario_entrega)
            if self.delivery_mode == "delivery" and not self.zona_envio_id:
                raise ValueError("Selecciona una zona de envio.")
            items = [
                OrderItemInput(
                    producto_id=int(item["producto_id"]),
                    cantidad=int(item["cantidad"]),
                    contexto_origen=str(item.get("categoria_codigo") or DEFAULT_CONTEXT_CODE),
                )
                for item in self.cart
            ]
            if not self.submission_token:
                self.submission_token = str(uuid4())
            payload = PublicOrderInput(
                submission_token=self.submission_token,
                nombre_apellido=self.nombre_apellido,
                telefono=self.telefono,
                fecha_entrega=delivery_date,
                direccion_delivery=self.direccion_delivery if self.delivery_mode == "delivery" else "Retiro en el local",
                zona_envio_id=int(self.zona_envio_id) if self.delivery_mode == "delivery" and self.zona_envio_id else None,
                forma_pago=FormaPago(self.forma_pago),
                observaciones=self.observaciones or None,
                items=items,
            )
            result = await asyncio.to_thread(_create_public_order, payload)
            # Mark success before generating the link: even a later error must not resave.
            self.registered_order_code = result.pedido.codigo
            self.whatsapp_url = self._build_whatsapp_url(result.pedido.codigo, result.pedido.monto_total)
            self.message = "Su pedido se registró correctamente. Te enviaremos a WhatsApp para que confirmes tu pedido."
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
        if cart:
            try:
                inputs = [
                    OrderItemInput(
                        producto_id=int(item["producto_id"]),
                        cantidad=int(item["cantidad"]),
                        contexto_origen=str(item.get("categoria_codigo") or DEFAULT_CONTEXT_CODE),
                    )
                    for item in cart
                ]
                priced_items = await asyncio.to_thread(_price_public_cart, inputs)
                for cart_item, priced_item in zip(cart, priced_items):
                    base_unit = Decimal(str(cart_item["precio"]))
                    final_unit = Decimal(str(priced_item.precio_unitario))
                    quantity = Decimal(str(cart_item["cantidad"]))
                    base_subtotal = base_unit * quantity
                    subtotal = Decimal(str(priced_item.subtotal))
                    discount = base_subtotal - subtotal
                    cart_item["precio_final"] = str(final_unit)
                    cart_item["subtotal"] = str(subtotal)
                    cart_item["subtotal_display"] = _money_text(subtotal)
                    cart_item["base_subtotal_display"] = _money_text(base_subtotal)
                    cart_item["discount"] = str(discount)
                    cart_item["discount_display"] = _money_text(discount)
                    cart_item["promo_label"] = (
                        f"Promo aplicada: $-{_money_text(discount)}" if discount > 0 else ""
                    )
            except Exception as exc:
                if isinstance(exc, ValueError):
                    self.message = _friendly_error(exc)
                self.technical_error = str(exc)
                for cart_item in cart:
                    subtotal = Decimal(str(cart_item["precio"])) * Decimal(str(cart_item["cantidad"]))
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
        self.whatsapp_url = ""
        self.submission_token = ""
        self.message = ""
        self.telefono = ""
        self.telefono_confirmacion = ""
        self.delivery_mode = "retiro"
        self.zona_envio_id = ""
        self.selected_zone_name = ""
        self.selected_zone_cost = "0,00"
        self._refresh_order_total()
        self.view = "categories"

    def _selected_shipping_cost(self) -> Decimal:
        if self.delivery_mode != "delivery" or not self.zona_envio_id:
            return Decimal("0.00")
        selected = next((zone for zone in self.zones if str(zone["id"]) == self.zona_envio_id), None)
        return Decimal(str(selected["costo"])) if selected else Decimal("0.00")

    def _build_whatsapp_url(self, pedido_codigo: str, total: Decimal) -> str:
        now = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).strftime("%d/%m/%y - %H:%Mhs")
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
                f"Forma de pago: {'Transferencia' if self.forma_pago == FormaPago.TRANSFERENCIA.value else 'Efectivo'}",
        ]
        if self.forma_pago == FormaPago.TRANSFERENCIA.value:
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
            category = item.get("categoria", "Productos")
            if category not in categories:
                categories.append(category)
        for category in categories:
            lines.append(f"{category.upper()} ({category.upper()})")
            for item in self.cart:
                if item.get("categoria", "Productos") != category:
                    continue
                lines.append(
                    f"{item['cantidad']}x {item['nombre']}: ${item['subtotal_display']}"
                )
                if item.get("promo_label"):
                    lines.append(item["promo_label"])
        lines.extend(
            [
                "",
                f"Subtotal: ${self.cart_total_display}",
                f"Costo de envio: +${self.selected_zone_cost if self.delivery_mode == 'delivery' else '0,00'}",
                f"TOTAL: ${_money_text(total)}",
                "",
                "Espero tu respuesta para confirmar mi pedido",
            ]
        )
        phone = "".join(char for char in PIZZERIA_WHATSAPP_PHONE if char.isdigit())
        target = f"https://wa.me/{phone}" if phone else "https://wa.me/"
        return f"{target}?text={quote(chr(10).join(lines))}"
