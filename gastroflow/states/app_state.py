from __future__ import annotations

import io
import json
import os
from pathlib import Path
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import reflex as rx
from openpyxl import Workbook
from sqlmodel import Session, select

from gastroflow.data.database import engine
from gastroflow.domain.enums import EstadoPedido, FormaPago, RolUsuario
from gastroflow.domain.enums import TipoPromocion
from gastroflow.domain.errors import DomainError
from gastroflow.models import (
    Categoria,
    Cliente,
    Gasto,
    Pedido,
    PedidoItem,
    Producto,
    ProductoCategoria,
    Marca,
    MotivoGasto,
    Promocion,
    PromocionProducto,
    UsuarioRead,
    ZonaEnvio,
)
from gastroflow.services import (
    AdminCrudService,
    AuthService,
    CRUD_TABLES,
    ExpenseInput,
    ExpenseService,
    OrderItemInput,
    OrderService,
    PublicOrderInput,
)

MONEY_QUANT = Decimal("0.01")
QUANTITY_QUANT = Decimal("0.001")
MONTH_OPTIONS = ["Todos", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
MONTH_NUMBERS = {
    "Enero": "01",
    "Febrero": "02",
    "Marzo": "03",
    "Abril": "04",
    "Mayo": "05",
    "Junio": "06",
    "Julio": "07",
    "Agosto": "08",
    "Septiembre": "09",
    "Octubre": "10",
    "Noviembre": "11",
    "Diciembre": "12",
}
UPLOAD_ROOT = Path("uploads")
BRAND_SETTINGS_PATH = Path("uploaded_files") / "brand" / "settings.json"
STORE_NAME = os.getenv("STORE_NAME", "")
PIZZERIA_WHATSAPP_PHONE = os.getenv("PIZZERIA_WHATSAPP_PHONE", "")
TRANSFER_TITULAR = os.getenv("TRANSFER_TITULAR", "")
TRANSFER_ALIAS = os.getenv("TRANSFER_ALIAS", "")


def _display(value: Any) -> Any:
    if isinstance(value, (date, datetime, Decimal)):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    return value


def _display_record(record: dict[str, Any]) -> dict[str, Any]:
    return {key: _display(value) for key, value in record.items()}


def _display_record_row(record: dict[str, Any]) -> dict[str, Any]:
    display_record = _display_record(record)
    return {
        "id": str(display_record.get("id", "")),
        "display": json.dumps(display_record, ensure_ascii=False, default=str),
    }


def _money_text(value: Decimal | str | int) -> str:
    amount = Decimal(str(value)).quantize(MONEY_QUANT)
    return f"{amount:.2f}".replace(".", ",")


def _quantity_text(value: Decimal | str | int) -> str:
    amount = Decimal(str(value)).quantize(QUANTITY_QUANT)
    text = f"{amount:.3f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _upper_text(value: str) -> str:
    return " ".join(value.strip().split()).upper()


def _parse_quantity_input(value: str) -> Decimal:
    clean = value.strip().replace(" ", "").replace(",", ".")
    return Decimal(clean).quantize(QUANTITY_QUANT)


def _parse_money_input(value: str) -> Decimal:
    clean = value.strip().replace("$", "").replace(" ", "")
    if "," in clean:
        clean = clean.replace(".", "").replace(",", ".")
    elif clean.count(".") == 1:
        left, right = clean.split(".", 1)
        if len(right) == 3 and len(left) <= 3:
            clean = left + right
    return Decimal(clean).quantize(MONEY_QUANT)


def _xlsx_download(rows: list[dict[str, Any]], filename: str) -> rx.event.EventSpec:
    workbook = Workbook()
    sheet = workbook.active
    if rows:
        headers = list(rows[0].keys())
        sheet.append(headers)
        for row in rows:
            sheet.append([row.get(header, "") for header in headers])
    else:
        sheet.append(["sin_datos"])
    stream = io.BytesIO()
    workbook.save(stream)
    return rx.download(
        data=stream.getvalue(),
        filename=filename,
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _contains(value: str, filter_value: str) -> bool:
    return not filter_value.strip() or filter_value.strip().lower() in value.lower()


def _read_brand_logo_url() -> str:
    try:
        data = json.loads(BRAND_SETTINGS_PATH.read_text(encoding="utf-8"))
        return str(data.get("logo_url") or "")
    except Exception:
        return ""


def _write_brand_logo_url(url: str) -> None:
    BRAND_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    BRAND_SETTINGS_PATH.write_text(json.dumps({"logo_url": url}, ensure_ascii=False), encoding="utf-8")


def _normalize_upload_path(value: str | None) -> str:
    if not value:
        return ""
    return value.replace("/uploaded_files/", "").lstrip("/")


def _parse_delivery_date(value: str) -> date:
    clean = value.strip()
    if "-" in clean and len(clean.split("-")[0]) == 4:
        return date.fromisoformat(clean)
    day, month, year = clean.split("/")
    return date(int(year), int(month), int(day))


def _date_text(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def _date_key(value: str) -> str:
    if not value.strip():
        return ""
    try:
        return _parse_delivery_date(value).isoformat()
    except Exception:
        return value.strip()


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


class AuthState(rx.State):
    username: str = ""
    password: str = ""
    user_id: int = 0
    role: str = ""
    message: str = ""

    @rx.var
    def is_authenticated(self) -> bool:
        return self.user_id > 0

    @rx.var
    def is_admin(self) -> bool:
        return self.role == RolUsuario.ADMIN.value

    def current_user(self) -> UsuarioRead:
        role = RolUsuario(self.role or RolUsuario.DUENO.value)
        return UsuarioRead(
            id=self.user_id,
            username=self.username,
            rol=role,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    def login(self) -> rx.event.EventSpec | None:
        try:
            with Session(engine) as session:
                user = AuthService(session).authenticate(self.username, self.password)
            self.user_id = user.id
            self.username = user.username
            self.role = user.rol.value
            self.password = ""
            self.message = "Sesion iniciada."
            return rx.redirect("/pedidos")
        except DomainError as exc:
            self.message = str(exc)
            return None

    def logout(self) -> rx.event.EventSpec:
        self.username = ""
        self.password = ""
        self.user_id = 0
        self.role = ""
        self.message = "Sesion cerrada."
        return rx.redirect("/login")


class BrandState(rx.State):
    logo_url: str = _normalize_upload_path(_read_brand_logo_url())

    def load_brand(self) -> None:
        self.logo_url = _normalize_upload_path(_read_brand_logo_url())


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

    def load_catalog(self) -> None:
        with Session(engine) as session:
            categories = session.exec(
                select(Categoria).where(
                    Categoria.visible_cliente == True,  # noqa: E712
                    Categoria.es_automatica == False,  # noqa: E712
                    Categoria.activa == True,  # noqa: E712
                )
            ).all()
            products = session.exec(select(Producto)).all()
            product_categories = session.exec(
                select(ProductoCategoria).where(ProductoCategoria.activo == True)  # noqa: E712
            ).all()
            zones = session.exec(select(ZonaEnvio)).all()

        category_names = {category.id: category.nombre for category in categories}
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

    def add_selected_to_cart(self) -> None:
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
        self._refresh_cart_total()
        self.message = "Producto agregado al pedido."
        self.view = "products"

    def remove_cart_item(self, product_id: int) -> None:
        self.cart = [item for item in self.cart if int(item["producto_id"]) != int(product_id)]
        self._refresh_cart_total()
        self.message = ""

    def show_cart(self) -> None:
        self.view = "cart"
        self.message = ""

    def set_fecha_entrega(self, value: str) -> None:
        self.fecha_entrega = _mask_date(value)

    def set_horario_entrega(self, value: str) -> None:
        self.horario_entrega = _mask_time(value)

    def set_delivery_mode(self, value: str) -> None:
        self.delivery_mode = value
        if value == "retiro":
            self.direccion_delivery = ""
            self.zona_envio_id = ""
            self.selected_zone_name = ""
            self.selected_zone_cost = "0,00"
        self._refresh_cart_total()

    def select_zone(self, zone_id: int) -> None:
        selected = next((zone for zone in self.zones if str(zone["id"]) == str(zone_id)), {})
        self.zona_envio_id = str(zone_id)
        self.selected_zone_name = selected.get("nombre", "")
        self.selected_zone_cost = selected.get("costo_display", "0,00")
        self._refresh_cart_total()

    def set_forma_pago(self, value: str) -> None:
        self.forma_pago = value

    def submit_order(self) -> rx.event.EventSpec | None:
        try:
            if not self.cart:
                raise ValueError("Tu pedido esta vacio.")
            delivery_date = _parse_delivery_date(self.fecha_entrega)
            _validate_time(self.horario_entrega)
            if self.delivery_mode == "delivery" and not self.zona_envio_id:
                raise ValueError("Selecciona una zona de envio.")
            items = [
                OrderItemInput(
                    producto_id=int(item["producto_id"]),
                    cantidad=int(item["cantidad"]),
                )
                for item in self.cart
            ]
            payload = PublicOrderInput(
                nombre_apellido=self.nombre_apellido,
                telefono=self.telefono,
                fecha_entrega=delivery_date,
                direccion_delivery=self.direccion_delivery if self.delivery_mode == "delivery" else "Retiro en el local",
                zona_envio_id=int(self.zona_envio_id) if self.delivery_mode == "delivery" and self.zona_envio_id else None,
                forma_pago=FormaPago(self.forma_pago),
                observaciones=self.observaciones or None,
                items=items,
            )
            with Session(engine) as session:
                result = OrderService(session).create_public_order(payload)
            whatsapp_url = self._build_whatsapp_url(result.pedido.codigo, result.pedido.monto_total)
            self.message = "Pedido creado. Te llevamos a WhatsApp para enviar el resumen."
            return rx.redirect(whatsapp_url, is_external=True)
        except Exception as exc:
            self.message = str(exc)
            return None

    def _refresh_cart_total(self) -> None:
        cart = [dict(item) for item in self.cart]
        if cart:
            try:
                inputs = [
                    OrderItemInput(producto_id=int(item["producto_id"]), cantidad=int(item["cantidad"]))
                    for item in cart
                ]
                with Session(engine) as session:
                    priced_items = OrderService(session)._price_items(inputs)
                for cart_item, priced_item in zip(cart, priced_items):
                    base_unit = Decimal(str(cart_item["precio"]))
                    final_unit = Decimal(str(priced_item.precio_unitario))
                    quantity = Decimal(str(cart_item["cantidad"]))
                    base_subtotal = base_unit * quantity
                    subtotal = final_unit * quantity
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
            except Exception:
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
            f"Fecha: {now}",
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


class OperationsState(rx.State):
    orders: list[dict[str, Any]] = []
    order_rows: list[dict[str, Any]] = []
    order_kpis: dict[str, str] = {
        "total_pedidos": "0",
        "items": "0",
        "ticket_promedio": "0,00",
        "facturacion": "0,00",
    }
    filter_month: str = "Todos"
    filter_date_from: str = ""
    filter_date_to: str = ""
    filter_category: str = "Todos"
    filter_client: str = ""
    filter_payment: str = "Todos"
    filter_state: str = "Todos"
    month_options: list[str] = MONTH_OPTIONS
    category_options: list[str] = []
    payment_options: list[str] = ["Todos", FormaPago.EFECTIVO.value, FormaPago.TRANSFERENCIA.value]
    state_options: list[str] = ["Todos"] + [state.value for state in EstadoPedido]
    no_order_data: bool = False
    no_active_order_data: bool = False
    message: str = ""

    def load_orders(self) -> None:
        with Session(engine) as session:
            pedidos = session.exec(select(Pedido)).all()
            clientes = {cliente.id: cliente for cliente in session.exec(select(Cliente)).all()}
            items = session.exec(select(PedidoItem)).all()
            categorias = {categoria.id: categoria for categoria in session.exec(select(Categoria)).all()}
            productos = {producto.id: producto for producto in session.exec(select(Producto)).all()}

        items_by_order: dict[int, list[Any]] = {}
        for item in items:
            items_by_order.setdefault(item.pedido_id, []).append(item)

        rows: list[dict[str, Any]] = []
        cards: list[dict[str, Any]] = []
        for pedido in pedidos:
            cliente = clientes.get(pedido.cliente_id)
            pedido_items = items_by_order.get(pedido.id or 0, [])
            item_count = sum(item.cantidad for item in pedido_items)
            category_names = sorted(
                {
                    categorias[item.categoria_venta_id].nombre
                    for item in pedido_items
                    if item.categoria_venta_id in categorias
                }
            )
            product_names = [
                productos[item.producto_id].nombre
                for item in pedido_items
                if item.producto_id in productos
            ]
            row = {
                "id": pedido.id,
                "codigo": pedido.codigo,
                "cliente": cliente.nombre_apellido if cliente else "",
                "telefono": cliente.telefono if cliente else "",
                "estado": pedido.estado.value,
                "forma_pago": pedido.forma_pago.value,
                "fecha": _date_text(pedido.fecha_entrega),
                "fecha_key": pedido.fecha_entrega.isoformat(),
                "mes": pedido.fecha_entrega.strftime("%Y-%m"),
                "categorias": ", ".join(category_names),
                "productos": ", ".join(product_names),
                "items": item_count,
                "envio": str(pedido.costo_envio),
                "total": str(pedido.monto_total),
                "total_display": _money_text(pedido.monto_total),
            }
            rows.append(row)
            if pedido.estado not in {EstadoPedido.ENTREGADO, EstadoPedido.CANCELADO}:
                cards.append(row)

        filtered = [row for row in rows if self._matches_order_filters(row)]
        total = sum((Decimal(str(row["total"])) for row in filtered), Decimal("0.00"))
        item_total = sum(int(row["items"]) for row in filtered)
        average = total / Decimal(len(filtered)) if filtered else Decimal("0.00")
        self.order_rows = filtered
        self.orders = [row for row in cards if self._matches_order_filters(row)]
        self.no_order_data = len(filtered) == 0
        self.no_active_order_data = len(self.orders) == 0
        self.order_kpis = {
            "total_pedidos": str(len(filtered)),
            "items": str(item_total),
            "ticket_promedio": _money_text(average),
            "facturacion": _money_text(total),
        }
        self.category_options = ["Todos"] + sorted({category.nombre for category in categorias.values()})

    def _matches_order_filters(self, row: dict[str, Any]) -> bool:
        if self.filter_month.strip() and self.filter_month != "Todos" and row["mes"][5:7] != MONTH_NUMBERS.get(self.filter_month, ""):
            return False
        if self.filter_date_from.strip() and row["fecha_key"] < _date_key(self.filter_date_from):
            return False
        if self.filter_date_to.strip() and row["fecha_key"] > _date_key(self.filter_date_to):
            return False
        if self.filter_payment.strip() and self.filter_payment != "Todos" and row["forma_pago"] != self.filter_payment.strip():
            return False
        if self.filter_state.strip() and self.filter_state != "Todos" and row["estado"] != self.filter_state.strip():
            return False
        return (
            (
                not self.filter_category.strip()
                or self.filter_category == "Todos"
                or self.filter_category in row["categorias"].split(", ")
            )
            and _contains(row["cliente"], self.filter_client)
        )

    def set_filter_date_from(self, value: str) -> None:
        self.filter_date_from = _mask_date(value)

    def set_filter_date_to(self, value: str) -> None:
        self.filter_date_to = _mask_date(value)

    def clear_order_filters(self) -> None:
        self.filter_month = "Todos"
        self.filter_date_from = ""
        self.filter_date_to = ""
        self.filter_category = "Todos"
        self.filter_client = ""
        self.filter_payment = "Todos"
        self.filter_state = "Todos"
        self.load_orders()

    def export_orders_xlsx(self) -> rx.event.EventSpec:
        export_rows = [
            {
                "codigo": row["codigo"],
                "fecha": row["fecha"],
                "cliente": row["cliente"],
                "telefono": row["telefono"],
                "estado": row["estado"],
                "forma_pago": row["forma_pago"],
                "categorias": row["categorias"],
                "productos": row["productos"],
                "items": row["items"],
                "envio": row["envio"],
                "total": row["total"],
            }
            for row in self.order_rows
        ]
        return _xlsx_download(export_rows, "pedidos_filtrados.xlsx")

    async def transition(self, pedido_id: int, next_state: str) -> None:
        auth = await self.get_state(AuthState)
        if not auth.user_id:
            self.message = "Inicia sesion para operar pedidos."
            return
        try:
            with Session(engine) as session:
                OrderService(session).transition_order(
                    pedido_id=pedido_id,
                    next_state=EstadoPedido(next_state),
                    current_user=auth.current_user(),
                )
            self.message = "Estado actualizado."
            self.load_orders()
        except DomainError as exc:
            self.message = str(exc)


class ExpenseState(rx.State):
    editing_expense_id: str = ""
    fecha: str = ""
    motivo_nombre: str = ""
    marca_nombre: str = ""
    cantidad: str = "1"
    unidad_medida: str = "kg"
    precio: str = "0"
    lugar_texto: str = ""
    message: str = ""
    expenses: list[dict[str, Any]] = []
    expense_rows: list[dict[str, Any]] = []
    expense_kpis: dict[str, str] = {
        "total_gastos": "0",
        "monto_total": "0,00",
        "ticket_promedio": "0,00",
    }
    filter_month: str = ""
    filter_date_from: str = ""
    filter_date_to: str = ""
    filter_motivo: str = ""
    filter_marca: str = ""
    filter_lugar: str = ""
    month_options: list[str] = MONTH_OPTIONS
    no_expense_data: bool = False
    show_form: bool = False
    pending_delete_id: str = ""
    pending_save: bool = False

    def load_expenses(self) -> None:
        with Session(engine) as session:
            gastos = session.exec(select(Gasto)).all()
            motivos = {motivo.id: motivo for motivo in session.exec(select(MotivoGasto)).all()}
            marcas = {marca.id: marca for marca in session.exec(select(Marca)).all()}

        rows = [
            {
                "id": gasto.id,
                "codigo": gasto.codigo,
                "fecha": _date_text(gasto.fecha),
                "fecha_key": gasto.fecha.isoformat(),
                "mes": gasto.fecha.strftime("%Y-%m"),
                "motivo": motivos[gasto.motivo_gasto_id].nombre if gasto.motivo_gasto_id in motivos else "",
                "marca": marcas[gasto.marca_id].nombre if gasto.marca_id in marcas else "",
                "cantidad": str(gasto.cantidad),
                "cantidad_display": _quantity_text(gasto.cantidad),
                "unidad": gasto.unidad_medida,
                "precio": str(gasto.precio),
                "precio_display": _money_text(gasto.precio),
                "lugar": gasto.lugar_texto,
            }
            for gasto in gastos
        ]
        filtered = [row for row in rows if self._matches_expense_filters(row)]
        total = sum((Decimal(str(row["precio"])) for row in filtered), Decimal("0.00"))
        average = total / Decimal(len(filtered)) if filtered else Decimal("0.00")
        self.expense_rows = filtered
        self.expenses = filtered
        self.no_expense_data = len(filtered) == 0
        self.expense_kpis = {
            "total_gastos": str(len(filtered)),
            "monto_total": _money_text(total),
            "ticket_promedio": _money_text(average),
        }

    def _matches_expense_filters(self, row: dict[str, Any]) -> bool:
        if self.filter_month.strip() and self.filter_month != "Todos" and row["mes"][5:7] != MONTH_NUMBERS.get(self.filter_month, ""):
            return False
        if self.filter_date_from.strip() and row["fecha_key"] < _date_key(self.filter_date_from):
            return False
        if self.filter_date_to.strip() and row["fecha_key"] > _date_key(self.filter_date_to):
            return False
        return (
            _contains(row["motivo"], self.filter_motivo)
            and _contains(row["marca"], self.filter_marca)
            and _contains(row["lugar"], self.filter_lugar)
        )

    def clear_expense_filters(self) -> None:
        self.filter_month = "Todos"
        self.filter_date_from = ""
        self.filter_date_to = ""
        self.filter_motivo = ""
        self.filter_marca = ""
        self.filter_lugar = ""
        self.load_expenses()

    def set_fecha(self, value: str) -> None:
        self.fecha = _mask_date(value)

    def set_motivo_nombre(self, value: str) -> None:
        self.motivo_nombre = value.upper()

    def set_marca_nombre(self, value: str) -> None:
        self.marca_nombre = value.upper()

    def set_unidad_medida(self, value: str) -> None:
        self.unidad_medida = value.upper()

    def set_lugar_texto(self, value: str) -> None:
        self.lugar_texto = value.upper()

    def set_filter_date_from(self, value: str) -> None:
        self.filter_date_from = _mask_date(value)

    def set_filter_date_to(self, value: str) -> None:
        self.filter_date_to = _mask_date(value)

    def open_new_expense(self) -> None:
        self.editing_expense_id = ""
        self.fecha = ""
        self.motivo_nombre = ""
        self.marca_nombre = ""
        self.cantidad = "1"
        self.unidad_medida = "kg"
        self.precio = "0"
        self.lugar_texto = ""
        self.show_form = True
        self.message = ""

    def open_edit_expense(self, expense_id: int) -> None:
        selected = next((row for row in self.expense_rows if str(row["id"]) == str(expense_id)), None)
        if selected is None:
            self.message = "Gasto inexistente."
            return
        self.editing_expense_id = str(expense_id)
        self.fecha = selected["fecha"]
        self.motivo_nombre = selected["motivo"]
        self.marca_nombre = selected["marca"]
        self.cantidad = selected["cantidad"]
        self.unidad_medida = selected["unidad"]
        self.precio = selected["precio"]
        self.lugar_texto = selected["lugar"]
        self.show_form = True

    def close_form(self) -> None:
        self.show_form = False
        self.pending_save = False

    def request_save_expense(self) -> None:
        self.pending_save = True

    def cancel_save_expense(self) -> None:
        self.pending_save = False

    def request_delete_expense(self, expense_id: int) -> None:
        self.pending_delete_id = str(expense_id)

    def cancel_delete_expense(self) -> None:
        self.pending_delete_id = ""

    def export_expenses_xlsx(self) -> rx.event.EventSpec:
        export_rows = [
            {
                "codigo": row["codigo"],
                "fecha": row["fecha"],
                "motivo": row["motivo"],
                "marca": row["marca"],
                "cantidad": row["cantidad_display"],
                "unidad": row["unidad"],
                "precio": row["precio"],
                "lugar": row["lugar"],
            }
            for row in self.expense_rows
        ]
        return _xlsx_download(export_rows, "gastos_filtrados.xlsx")

    async def submit_expense(self) -> rx.event.EventSpec | None:
        auth = await self.get_state(AuthState)
        if not auth.user_id:
            self.message = "Inicia sesion para cargar gastos."
            return None
        try:
            expense_date = _parse_delivery_date(self.fecha)
            with Session(engine) as session:
                if self.editing_expense_id:
                    gasto = session.get(Gasto, int(self.editing_expense_id))
                    if gasto is None:
                        raise ValueError("Gasto inexistente.")
                    motivo = ExpenseService(session)._get_or_create_motivo(self.motivo_nombre)
                    marca = ExpenseService(session)._get_or_create_marca(self.marca_nombre)
                    gasto.fecha = expense_date
                    gasto.motivo_gasto_id = motivo.id or 0
                    gasto.marca_id = marca.id or 0
                    gasto.cantidad = _parse_quantity_input(self.cantidad)
                    gasto.unidad_medida = _upper_text(self.unidad_medida)
                    gasto.precio = _parse_money_input(self.precio)
                    gasto.lugar_texto = _upper_text(self.lugar_texto)
                    session.add(gasto)
                    session.commit()
                    message = f"Gasto {gasto.codigo} modificado."
                else:
                    payload = ExpenseInput(
                        fecha=expense_date,
                        motivo_nombre=_upper_text(self.motivo_nombre),
                        marca_nombre=_upper_text(self.marca_nombre),
                        cantidad=_parse_quantity_input(self.cantidad),
                        unidad_medida=_upper_text(self.unidad_medida),
                        precio=_parse_money_input(self.precio),
                        lugar_texto=_upper_text(self.lugar_texto),
                    )
                    gasto_read = ExpenseService(session).create_expense(payload, auth.current_user())
                    message = f"Gasto {gasto_read.codigo} agregado."
            self.message = message
            self.show_form = False
            self.pending_save = False
            self.load_expenses()
            return rx.toast.success(message)
        except Exception as exc:
            self.message = str(exc)
            self.pending_save = False
            return rx.toast.error(str(exc))

    async def delete_expense(self) -> rx.event.EventSpec | None:
        auth = await self.get_state(AuthState)
        if not auth.user_id:
            self.message = "Inicia sesion para borrar gastos."
            return None
        try:
            with Session(engine) as session:
                gasto = session.get(Gasto, int(self.pending_delete_id))
                if gasto is None:
                    raise ValueError("Gasto inexistente.")
                code = gasto.codigo
                session.delete(gasto)
                session.commit()
            self.pending_delete_id = ""
            self.message = f"Gasto {code} eliminado."
            self.load_expenses()
            return rx.toast.success(f"Gasto {code} eliminado.")
        except Exception as exc:
            self.message = str(exc)
            self.pending_delete_id = ""
            return rx.toast.error(str(exc))


class CatalogAdminState(rx.State):
    categories: list[dict[str, Any]] = []
    products: list[dict[str, Any]] = []
    available_products: list[str] = []
    promotions: list[dict[str, Any]] = []
    promo_product_options: list[str] = []
    promo_selected_product: str = ""
    promo_selected_products: list[dict[str, Any]] = []
    selected_category_id: str = ""
    selected_product_category_id: str = ""
    selected_available_product_id: str = ""
    category_nombre: str = ""
    category_descripcion: str = ""
    category_orden: str = "0"
    category_visible: bool = True
    product_price: str = "0"
    product_description: str = ""
    product_order: str = "0"
    product_visible: bool = True
    product_featured: bool = False
    promo_id: str = ""
    promo_codigo: str = ""
    promo_nombre: str = ""
    promo_cantidad_minima: str = "2"
    promo_precio: str = "0"
    promo_activa: bool = True
    promo_product_ids: str = ""
    pending_delete_product_category_id: str = ""
    pending_delete_promo_id: str = ""
    pending_save_category: bool = False
    pending_save_product: bool = False
    logo_url: str = _normalize_upload_path(_read_brand_logo_url())
    message: str = ""

    async def load_catalog_admin(self) -> None:
        auth = await self.get_state(AuthState)
        if auth.role != RolUsuario.ADMIN.value:
            self.message = "Solo Admin puede editar catalogo."
            return
        self._load_catalog_data()

    def _load_catalog_data(self) -> None:
        with Session(engine) as session:
            categories = session.exec(select(Categoria)).all()
            product_categories = session.exec(select(ProductoCategoria)).all()
            products = {product.id: product for product in session.exec(select(Producto)).all()}
            promotions = session.exec(select(Promocion)).all()
            promotion_links = session.exec(select(PromocionProducto)).all()

        counts: dict[int, int] = {}
        for product_category in product_categories:
            counts[product_category.categoria_id] = counts.get(product_category.categoria_id, 0) + 1

        self.categories = [
            {
                "id": category.id,
                "codigo": category.codigo,
                "nombre": category.nombre,
                "descripcion": category.descripcion_publica or "",
                "foto": _normalize_upload_path(category.foto_url),
                "orden": str(category.orden),
                "visible": category.visible_cliente,
                "automatica": category.es_automatica,
                "total": counts.get(category.id or 0, 0),
            }
            for category in sorted(categories, key=lambda item: (item.orden, item.nombre))
        ]
        selected_category = int(self.selected_category_id) if self.selected_category_id else 0
        self.products = [
            {
                "id": product_category.id,
                "producto_id": product.id,
                "categoria_id": product_category.categoria_id,
                "nombre": product.nombre,
                "codigo": product.codigo,
                "precio": str(product_category.precio),
                "precio_display": _money_text(product_category.precio),
                "descripcion": product_category.descripcion_publica or product.descripcion or "",
                "foto": _normalize_upload_path(product_category.foto_url),
                "visible": product_category.visible,
                "orden": str(product_category.orden),
                "destacado": product_category.destacado,
                "activo": product_category.activo,
            }
            for product_category in sorted(product_categories, key=lambda item: (item.orden, item.id or 0))
            if (not selected_category or product_category.categoria_id == selected_category)
            and (product := products.get(product_category.producto_id)) is not None
        ]
        linked_product_ids = {
            product_category.producto_id
            for product_category in product_categories
            if selected_category and product_category.categoria_id == selected_category
        }
        self.available_products = [
            f"{product.id} - {product.nombre} ({product.codigo})"
            for product in sorted(products.values(), key=lambda item: item.nombre)
            if product.activo and product.id not in linked_product_ids
        ]
        product_names = {product_id: product.nombre for product_id, product in products.items()}
        self.promo_product_options = [
            f"{product.id} - {product.nombre} ({product.codigo})"
            for product in sorted(products.values(), key=lambda item: item.nombre)
            if product.activo
        ]
        links_by_promo: dict[int, list[str]] = {}
        for link in promotion_links:
            links_by_promo.setdefault(link.promocion_id, []).append(product_names.get(link.producto_id, str(link.producto_id)))
        self.promotions = [
            {
                "id": promo.id,
                "codigo": promo.codigo,
                "nombre": promo.nombre,
                "cantidad_minima": str(promo.cantidad_minima),
                "precio": str(promo.precio_unitario_promocional),
                "precio_display": _money_text(promo.precio_unitario_promocional),
                "activa": promo.activa,
                "productos": ", ".join(links_by_promo.get(promo.id or 0, [])),
            }
            for promo in sorted(promotions, key=lambda item: item.codigo)
        ]
        self._sync_promo_selected_products(product_names)
        self.logo_url = _normalize_upload_path(_read_brand_logo_url())

    def _selected_promo_product_ids(self) -> list[int]:
        ids: list[int] = []
        for value in self.promo_product_ids.split(","):
            clean = value.strip()
            if clean and clean.isdigit() and int(clean) not in ids:
                ids.append(int(clean))
        return ids

    def _sync_promo_selected_products(self, product_names: dict[int | None, str] | None = None) -> None:
        if product_names is None:
            with Session(engine) as session:
                product_names = {product.id: product.nombre for product in session.exec(select(Producto)).all()}
        self.promo_selected_products = [
            {"id": product_id, "nombre": product_names.get(product_id, f"Producto {product_id}")}
            for product_id in self._selected_promo_product_ids()
        ]

    def select_category(self, category_id: int) -> None:
        self.selected_category_id = str(category_id)
        selected = next((category for category in self.categories if str(category["id"]) == str(category_id)), {})
        self.category_nombre = selected.get("nombre", "")
        self.category_descripcion = selected.get("descripcion", "")
        self.category_orden = selected.get("orden", "0")
        self.category_visible = bool(selected.get("visible", True))
        self.selected_product_category_id = ""
        self._load_catalog_data()

    def select_product_category(self, product_category_id: int) -> None:
        self.selected_product_category_id = str(product_category_id)
        selected = next(
            (item for item in self.products if str(item["id"]) == str(product_category_id)),
            {},
        )
        self.product_price = selected.get("precio", "0")
        self.product_description = selected.get("descripcion", "")
        self.product_order = selected.get("orden", "0")
        self.product_visible = bool(selected.get("visible", True))
        self.product_featured = bool(selected.get("destacado", False))

    def set_category_nombre(self, value: str) -> None:
        self.category_nombre = value.upper()

    def set_category_descripcion(self, value: str) -> None:
        self.category_descripcion = value.upper()

    def set_product_description(self, value: str) -> None:
        self.product_description = value.upper()

    def set_promo_codigo(self, value: str) -> None:
        self.promo_codigo = value.upper()

    def set_promo_nombre(self, value: str) -> None:
        self.promo_nombre = value.upper()

    def set_promo_product_ids(self, value: str) -> None:
        self.promo_product_ids = value
        self._sync_promo_selected_products()

    async def save_category(self) -> None:
        auth = await self.get_state(AuthState)
        if auth.role != RolUsuario.ADMIN.value:
            self.message = "Solo Admin puede editar catalogo."
            return
        if not self.selected_category_id:
            self.message = "Selecciona una categoria."
            return
        try:
            with Session(engine) as session:
                category = session.get(Categoria, int(self.selected_category_id))
                if category is None:
                    raise ValueError("Categoria inexistente.")
                category.nombre = _upper_text(self.category_nombre) or category.nombre
                category.descripcion_publica = _upper_text(self.category_descripcion) or None
                category.orden = int(self.category_orden or "0")
                category.visible_cliente = self.category_visible
                session.add(category)
                session.commit()
            self.message = "Categoria modificada."
            self.pending_save_category = False
            self._load_catalog_data()
            return rx.toast.success("Categoria modificada.")
        except Exception as exc:
            self.pending_save_category = False
            self.message = str(exc)
            return rx.toast.error(str(exc))

    def request_save_category(self) -> None:
        self.pending_save_category = True

    def cancel_save_category(self) -> None:
        self.pending_save_category = False

    async def save_product_category(self) -> None:
        auth = await self.get_state(AuthState)
        if auth.role != RolUsuario.ADMIN.value:
            self.message = "Solo Admin puede editar catalogo."
            return
        if not self.selected_product_category_id:
            self.message = "Selecciona un producto de la categoria."
            return
        try:
            with Session(engine) as session:
                product_category = session.get(ProductoCategoria, int(self.selected_product_category_id))
                if product_category is None:
                    raise ValueError("Producto de categoria inexistente.")
                product_category.precio = _parse_money_input(self.product_price)
                product_category.descripcion_publica = _upper_text(self.product_description) or None
                product_category.orden = int(self.product_order or "0")
                product_category.visible = self.product_visible
                product_category.destacado = self.product_featured
                session.add(product_category)
                session.commit()
            self.message = "Producto actualizado."
            self.pending_save_product = False
            self._load_catalog_data()
            return rx.toast.success("Producto modificado.")
        except Exception as exc:
            self.pending_save_product = False
            self.message = str(exc)
            return rx.toast.error(str(exc))

    def request_save_product_category(self) -> None:
        self.pending_save_product = True

    def cancel_save_product_category(self) -> None:
        self.pending_save_product = False

    async def add_product_to_category(self) -> rx.event.EventSpec | None:
        auth = await self.get_state(AuthState)
        if auth.role != RolUsuario.ADMIN.value:
            self.message = "Solo Admin puede editar catalogo."
            return None
        if not self.selected_category_id or not self.selected_available_product_id:
            self.message = "Selecciona categoria y producto."
            return rx.toast.warning(self.message)
        try:
            product_id = int(self.selected_available_product_id.split(" - ", 1)[0])
            with Session(engine) as session:
                existing = session.exec(
                    select(ProductoCategoria).where(
                        ProductoCategoria.producto_id == product_id,
                        ProductoCategoria.categoria_id == int(self.selected_category_id),
                    )
                ).first()
                if existing is not None:
                    raise ValueError("Ese producto ya esta en la categoria.")
                relation = ProductoCategoria(
                    producto_id=product_id,
                    categoria_id=int(self.selected_category_id),
                    precio=_parse_money_input(self.product_price or "0"),
                    descripcion_publica=_upper_text(self.product_description) or None,
                    foto_url=None,
                    visible=self.product_visible,
                    orden=int(self.product_order or "0"),
                    destacado=self.product_featured,
                    activo=True,
                )
                session.add(relation)
                session.commit()
            self.message = "Producto agregado a la categoria."
            self.selected_available_product_id = ""
            self._load_catalog_data()
            return rx.toast.success("Producto agregado a la categoria.")
        except Exception as exc:
            self.message = str(exc)
            return rx.toast.error(str(exc))

    def request_delete_product_category(self, product_category_id: int) -> None:
        self.pending_delete_product_category_id = str(product_category_id)

    def cancel_delete_product_category(self) -> None:
        self.pending_delete_product_category_id = ""

    async def delete_product_category(self) -> rx.event.EventSpec | None:
        auth = await self.get_state(AuthState)
        if auth.role != RolUsuario.ADMIN.value:
            self.message = "Solo Admin puede editar catalogo."
            return None
        try:
            with Session(engine) as session:
                relation = session.get(ProductoCategoria, int(self.pending_delete_product_category_id))
                if relation is None:
                    raise ValueError("Relacion inexistente.")
                session.delete(relation)
                session.commit()
            self.pending_delete_product_category_id = ""
            self.selected_product_category_id = ""
            self.message = "Producto eliminado de la categoria."
            self._load_catalog_data()
            return rx.toast.success("Producto eliminado de la categoria.")
        except Exception as exc:
            self.pending_delete_product_category_id = ""
            self.message = str(exc)
            return rx.toast.error(str(exc))

    async def upload_category_photo(self, files: list[rx.UploadFile]) -> None:
        auth = await self.get_state(AuthState)
        if auth.role != RolUsuario.ADMIN.value or not self.selected_category_id:
            self.message = "Selecciona una categoria antes de subir foto."
            return
        if not files:
            return
        relative_path = await self._save_upload(files[0], "categories")
        with Session(engine) as session:
            category = session.get(Categoria, int(self.selected_category_id))
            if category is not None:
                category.foto_url = relative_path
                session.add(category)
                session.commit()
        self.message = "Foto de categoria actualizada."
        self._load_catalog_data()
        return rx.toast.success("Foto de categoria actualizada.")

    async def upload_product_photo(self, files: list[rx.UploadFile]) -> None:
        auth = await self.get_state(AuthState)
        if auth.role != RolUsuario.ADMIN.value or not self.selected_product_category_id:
            self.message = "Selecciona un producto antes de subir foto."
            return
        if not files:
            return
        relative_path = await self._save_upload(files[0], "product-categories")
        with Session(engine) as session:
            product_category = session.get(ProductoCategoria, int(self.selected_product_category_id))
            if product_category is not None:
                product_category.foto_url = relative_path
                session.add(product_category)
                session.commit()
        self.message = "Foto del producto actualizada."
        self._load_catalog_data()
        return rx.toast.success("Foto del producto actualizada.")

    async def upload_logo(self, files: list[rx.UploadFile]) -> rx.event.EventSpec | None:
        auth = await self.get_state(AuthState)
        if auth.role != RolUsuario.ADMIN.value:
            self.message = "Solo Admin puede editar el logo."
            return None
        if not files:
            return None
        relative_path = await self._save_upload(files[0], "brand")
        _write_brand_logo_url(relative_path)
        brand = await self.get_state(BrandState)
        brand.load_brand()
        self.logo_url = relative_path
        self.message = "Logo actualizado."
        return rx.toast.success("Logo actualizado.")

    async def delete_category_photo(self) -> rx.event.EventSpec | None:
        if not self.selected_category_id:
            return None
        with Session(engine) as session:
            category = session.get(Categoria, int(self.selected_category_id))
            if category is not None:
                category.foto_url = None
                session.add(category)
                session.commit()
        self._load_catalog_data()
        self.message = "Foto de categoria eliminada."
        return rx.toast.success("Foto de categoria eliminada.")

    async def delete_product_photo(self) -> rx.event.EventSpec | None:
        if not self.selected_product_category_id:
            return None
        with Session(engine) as session:
            relation = session.get(ProductoCategoria, int(self.selected_product_category_id))
            if relation is not None:
                relation.foto_url = None
                session.add(relation)
                session.commit()
        self._load_catalog_data()
        self.message = "Foto de producto eliminada."
        return rx.toast.success("Foto de producto eliminada.")

    async def delete_logo(self) -> rx.event.EventSpec:
        _write_brand_logo_url("")
        brand = await self.get_state(BrandState)
        brand.load_brand()
        self.logo_url = ""
        self.message = "Logo eliminado."
        return rx.toast.success("Logo eliminado.")

    def new_promo(self) -> None:
        self.promo_id = ""
        self.promo_codigo = ""
        self.promo_nombre = ""
        self.promo_cantidad_minima = "2"
        self.promo_precio = "0"
        self.promo_activa = True
        self.promo_product_ids = ""
        self.promo_selected_product = ""
        self.promo_selected_products = []

    def select_promo(self, promo_id: int) -> None:
        selected = next((promo for promo in self.promotions if str(promo["id"]) == str(promo_id)), None)
        if selected is None:
            return
        self.promo_id = str(promo_id)
        self.promo_codigo = selected["codigo"]
        self.promo_nombre = selected["nombre"]
        self.promo_cantidad_minima = selected["cantidad_minima"]
        self.promo_precio = selected["precio"]
        self.promo_activa = bool(selected["activa"])
        with Session(engine) as session:
            links = session.exec(select(PromocionProducto).where(PromocionProducto.promocion_id == promo_id)).all()
        self.promo_product_ids = ",".join(str(link.producto_id) for link in links)
        self._sync_promo_selected_products()

    def set_promo_selected_product(self, value: str) -> None:
        self.promo_selected_product = value

    def add_selected_promo_product(self) -> rx.event.EventSpec | None:
        if not self.promo_selected_product:
            self.message = "Selecciona un producto para la promocion."
            return rx.toast.warning(self.message)
        product_id = int(self.promo_selected_product.split(" - ", 1)[0])
        ids = self._selected_promo_product_ids()
        if product_id not in ids:
            ids.append(product_id)
        self.promo_product_ids = ",".join(str(item) for item in ids)
        self.promo_selected_product = ""
        self._sync_promo_selected_products()
        return None

    def remove_promo_product(self, product_id: int) -> None:
        ids = [item for item in self._selected_promo_product_ids() if item != product_id]
        self.promo_product_ids = ",".join(str(item) for item in ids)
        self._sync_promo_selected_products()

    async def save_promo(self) -> rx.event.EventSpec | None:
        auth = await self.get_state(AuthState)
        if auth.role != RolUsuario.ADMIN.value:
            self.message = "Solo Admin puede editar promociones."
            return None
        try:
            product_ids = [
                int(value.strip())
                for value in self.promo_product_ids.split(",")
                if value.strip()
            ]
            with Session(engine) as session:
                if self.promo_id:
                    promo = session.get(Promocion, int(self.promo_id))
                    if promo is None:
                        raise ValueError("Promocion inexistente.")
                    action = "modificada"
                else:
                    promo = Promocion(
                        codigo=_upper_text(self.promo_codigo),
                        nombre=_upper_text(self.promo_nombre),
                        tipo=TipoPromocion.PRECIO_UNITARIO_POR_CANTIDAD,
                        cantidad_minima=int(self.promo_cantidad_minima),
                        precio_unitario_promocional=_parse_money_input(self.promo_precio),
                        activa=self.promo_activa,
                    )
                    session.add(promo)
                    session.flush()
                    action = "agregada"
                promo.codigo = _upper_text(self.promo_codigo)
                promo.nombre = _upper_text(self.promo_nombre)
                promo.cantidad_minima = int(self.promo_cantidad_minima)
                promo.precio_unitario_promocional = _parse_money_input(self.promo_precio)
                promo.activa = self.promo_activa
                session.add(promo)
                session.flush()
                for link in session.exec(select(PromocionProducto).where(PromocionProducto.promocion_id == promo.id)).all():
                    session.delete(link)
                for product_id in product_ids:
                    session.add(PromocionProducto(promocion_id=promo.id or 0, producto_id=product_id))
                session.commit()
            self.message = f"Promocion {action}."
            self.new_promo()
            self._load_catalog_data()
            return rx.toast.success(self.message)
        except Exception as exc:
            self.message = str(exc)
            return rx.toast.error(str(exc))

    def request_delete_promo(self, promo_id: int) -> None:
        self.pending_delete_promo_id = str(promo_id)

    def cancel_delete_promo(self) -> None:
        self.pending_delete_promo_id = ""

    async def delete_promo(self) -> rx.event.EventSpec | None:
        auth = await self.get_state(AuthState)
        if auth.role != RolUsuario.ADMIN.value:
            self.message = "Solo Admin puede editar promociones."
            return None
        try:
            with Session(engine) as session:
                promo = session.get(Promocion, int(self.pending_delete_promo_id))
                if promo is None:
                    raise ValueError("Promocion inexistente.")
                for link in session.exec(select(PromocionProducto).where(PromocionProducto.promocion_id == promo.id)).all():
                    session.delete(link)
                session.delete(promo)
                session.commit()
            self.pending_delete_promo_id = ""
            self.message = "Promocion eliminada."
            self._load_catalog_data()
            return rx.toast.success("Promocion eliminada.")
        except Exception as exc:
            self.pending_delete_promo_id = ""
            self.message = str(exc)
            return rx.toast.error(str(exc))

    async def _save_upload(self, file: rx.UploadFile, folder: str) -> str:
        upload_dir = Path(rx.get_upload_dir()) / folder
        upload_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(char for char in file.filename if char.isalnum() or char in {".", "-", "_"})
        filename = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}_{safe_name}"
        path = upload_dir / filename
        content = await file.read()
        path.write_bytes(content)
        return f"{folder}/{filename}"


class AdminCrudState(rx.State):
    table_name: str = "categoria"
    tables: list[str] = list(CRUD_TABLES.keys())
    records: list[dict[str, Any]] = []
    payload_json: str = "{}"
    selected_id: str = ""
    message: str = ""

    async def load_records(self) -> None:
        auth = await self.get_state(AuthState)
        if auth.role != RolUsuario.ADMIN.value:
            self.message = "Solo Admin puede administrar datos."
            return
        try:
            with Session(engine) as session:
                records = AdminCrudService(session).list_records(self.table_name, auth.current_user())
            self.records = [_display_record_row(record) for record in records]
            self.message = f"{len(self.records)} registros."
        except Exception as exc:
            self.message = str(exc)

    def set_table(self, table_name: str) -> None:
        self.table_name = table_name
        self.records = []
        self.selected_id = ""
        self.payload_json = "{}"

    async def create_record(self) -> None:
        await self._save_record(create=True)

    async def update_record(self) -> None:
        await self._save_record(create=False)

    async def delete_record(self) -> None:
        auth = await self.get_state(AuthState)
        if auth.role != RolUsuario.ADMIN.value:
            self.message = "Solo Admin puede borrar datos."
            return
        try:
            with Session(engine) as session:
                AdminCrudService(session).delete_record(self.table_name, int(self.selected_id), auth.current_user())
            self.message = "Registro borrado."
            await self.load_records()
        except Exception as exc:
            self.message = str(exc)

    async def _save_record(self, *, create: bool) -> None:
        auth = await self.get_state(AuthState)
        if auth.role != RolUsuario.ADMIN.value:
            self.message = "Solo Admin puede guardar datos."
            return
        try:
            data = json.loads(self.payload_json)
            with Session(engine) as session:
                service = AdminCrudService(session)
                if create:
                    record = service.create_record(self.table_name, data, auth.current_user())
                else:
                    record = service.update_record(self.table_name, int(self.selected_id), data, auth.current_user())
            self.message = f"Guardado: {_display_record(record)}"
            await self.load_records()
        except Exception as exc:
            self.message = str(exc)
