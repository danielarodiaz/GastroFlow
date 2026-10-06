from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from urllib.parse import quote

from sqlmodel import Session, select

from gastroflow.domain.enums import EstadoPedido, FormaPago, ReglaPrecioCombo, TipoPromocion
from gastroflow.domain.errors import ValidationError
from gastroflow.domain.order_state import assert_valid_order_transition
from gastroflow.models import (
    Categoria,
    Cliente,
    ComboRegla,
    Pedido,
    PedidoItem,
    PedidoRead,
    Producto,
    ProductoCategoria,
    Promocion,
    PromocionProducto,
    UsuarioRead,
    ZonaEnvio,
)
from gastroflow.services.auth import AuthService
from gastroflow.services.codes import next_business_code

MONEY_QUANT = Decimal("0.01")
DEFAULT_CONTEXT_CODE = "LISTA_HORNO"
EVENTS_CONTEXT_CODE = "EVENTOS"
WHOLESALE_CONTEXT_CODE = "MAYORISTA"
WHOLESALE_ELIGIBLE_CONTEXTS = frozenset({DEFAULT_CONTEXT_CODE})


@dataclass(frozen=True)
class OrderItemInput:
    producto_id: int
    cantidad: int
    producto_combo_id: int | None = None
    contexto_origen: str | None = None


@dataclass(frozen=True)
class PublicOrderInput:
    nombre_apellido: str
    telefono: str
    fecha_entrega: date
    direccion_delivery: str
    forma_pago: FormaPago
    items: list[OrderItemInput]
    zona_envio_id: int | None = None
    direccion_lat: Decimal | None = None
    direccion_lng: Decimal | None = None
    observaciones: str | None = None
    contexto_origen: str = DEFAULT_CONTEXT_CODE


@dataclass(frozen=True)
class CreatedOrderResult:
    pedido: PedidoRead
    whatsapp_url: str | None


@dataclass(frozen=True)
class PricedItem:
    item: OrderItemInput
    precio_unitario: Decimal
    categoria_venta_id: int
    subtotal: Decimal
    requiere_confirmacion: bool


@dataclass(frozen=True)
class AppliedPromotion:
    precio_unitario: Decimal
    cantidad_minima: int
    precio_total: Decimal | None = None


class OrderService:
    def __init__(self, session: Session):
        self.session = session

    def create_public_order(self, data: PublicOrderInput) -> CreatedOrderResult:
        if not data.items:
            raise ValidationError("El pedido debe tener al menos un item.")

        cliente = self._upsert_cliente(data.nombre_apellido, data.telefono)
        codigo = next_business_code(self.session, "pedido_codigo_seq", "PED")
        costo_envio = self._snapshot_delivery_cost(data.zona_envio_id)
        priced_items = self._price_items(data.items, data.contexto_origen)
        monto_items = sum((priced_item.subtotal for priced_item in priced_items), Decimal("0"))
        monto_total = self._money(monto_items + costo_envio)
        requires_confirmation = any(item.requiere_confirmacion for item in priced_items)
        estado = (
            EstadoPedido.PENDIENTE_CONFIRMACION
            if requires_confirmation
            else EstadoPedido.PEDIDO
        )

        pedido = Pedido(
            codigo=codigo,
            fecha_entrega=data.fecha_entrega,
            cliente_id=cliente.id or 0,
            direccion_delivery=data.direccion_delivery.strip(),
            direccion_lat=data.direccion_lat,
            direccion_lng=data.direccion_lng,
            zona_envio_id=data.zona_envio_id,
            costo_envio=costo_envio,
            forma_pago=data.forma_pago,
            estado=estado,
            observaciones=data.observaciones,
            monto_total=monto_total,
        )
        self.session.add(pedido)
        self.session.flush()

        for priced_item in priced_items:
            self.session.add(
                PedidoItem(
                    pedido_id=pedido.id or 0,
                    producto_id=priced_item.item.producto_id,
                    producto_combo_id=priced_item.item.producto_combo_id,
                    categoria_venta_id=priced_item.categoria_venta_id,
                    cantidad=priced_item.item.cantidad,
                    precio_unitario=priced_item.precio_unitario,
                    subtotal=priced_item.subtotal,
                )
            )

        self.session.commit()
        self.session.refresh(pedido)
        whatsapp_url = self._build_whatsapp_url(pedido, data, priced_items) if requires_confirmation else None
        return CreatedOrderResult(pedido=self._to_read(pedido), whatsapp_url=whatsapp_url)

    def transition_order(
        self,
        pedido_id: int,
        next_state: EstadoPedido,
        current_user: UsuarioRead,
    ) -> PedidoRead:
        AuthService(self.session).require_owner_or_admin(current_user)
        pedido = self.session.get(Pedido, pedido_id)
        if pedido is None:
            raise ValidationError("Pedido inexistente.")

        assert_valid_order_transition(pedido.estado, next_state)
        pedido.estado = next_state
        self.session.add(pedido)
        self.session.commit()
        self.session.refresh(pedido)
        return self._to_read(pedido)

    def _upsert_cliente(self, nombre_apellido: str, telefono: str) -> Cliente:
        normalized_phone = normalize_phone(telefono)
        if not normalized_phone:
            raise ValidationError("El telefono del cliente es obligatorio.")

        cliente = self.session.exec(
            select(Cliente).where(Cliente.telefono == normalized_phone)
        ).first()
        if cliente is None:
            cliente = Cliente(
                nombre_apellido=nombre_apellido.strip(),
                telefono=normalized_phone,
            )
            self.session.add(cliente)
            self.session.flush()
        else:
            cliente.nombre_apellido = nombre_apellido.strip() or cliente.nombre_apellido
            self.session.add(cliente)
            self.session.flush()
        return cliente

    def _snapshot_delivery_cost(self, zona_envio_id: int | None) -> Decimal:
        if zona_envio_id is None:
            return Decimal("0.00")

        zona = self.session.get(ZonaEnvio, zona_envio_id)
        if zona is None:
            raise ValidationError("Zona de envio inexistente.")
        return self._money(zona.costo)

    def _price_items(
        self,
        items: list[OrderItemInput],
        contexto_origen: str = DEFAULT_CONTEXT_CODE,
    ) -> list[PricedItem]:
        context_by_index = [
            item.contexto_origen or contexto_origen
            for item in items
        ]
        unique_contexts = set(context_by_index)
        if len(unique_contexts) == 1:
            contexto_origen = next(iter(unique_contexts))
        if len(set(context_by_index)) > 1:
            grouped_results: dict[int, PricedItem] = {}
            for context in dict.fromkeys(context_by_index):
                indexed_group = [
                    (index, item)
                    for index, item in enumerate(items)
                    if context_by_index[index] == context
                ]
                group_items = [
                    OrderItemInput(
                        producto_id=item.producto_id,
                        cantidad=item.cantidad,
                        producto_combo_id=item.producto_combo_id,
                    )
                    for _, item in indexed_group
                ]
                priced_group = self._price_items(group_items, context)
                for (index, _), priced_item in zip(indexed_group, priced_group):
                    grouped_results[index] = PricedItem(
                        item=items[index],
                        precio_unitario=priced_item.precio_unitario,
                        categoria_venta_id=priced_item.categoria_venta_id,
                        subtotal=priced_item.subtotal,
                        requiere_confirmacion=priced_item.requiere_confirmacion,
                    )
            return [grouped_results[index] for index in range(len(items))]

        products = self._load_products(items)
        origin_category = self._get_category_by_code(contexto_origen)
        sale_category = self._resolve_sale_category(items, contexto_origen, origin_category)
        category_prices = self._prices_for_category(sale_category.id or 0)
        promotional_prices = (
            {}
            if sale_category.codigo in {EVENTS_CONTEXT_CODE, WHOLESALE_CONTEXT_CODE}
            else self._eligible_promotions(items, category_prices)
        )

        priced_items: list[PricedItem] = []
        for item in items:
            if item.cantidad <= 0:
                raise ValidationError("La cantidad debe ser mayor a cero.")
            product = products[item.producto_id]
            base_price = self._item_base_price(product.id or 0, category_prices, is_combo=False)

            requires_confirmation = False
            unit_price = self._money(base_price)
            subtotal = self._money(base_price * item.cantidad)
            promotion = promotional_prices.get(product.id or 0)
            if promotion is not None and item.producto_combo_id is None:
                unit_price, subtotal = self._apply_promotion_to_line(
                    base_price=base_price,
                    quantity=item.cantidad,
                    promotion=promotion,
                )
            if item.producto_combo_id is not None:
                combo_product = products[item.producto_combo_id]
                combo_base_price = self._item_base_price(combo_product.id or 0, category_prices, is_combo=True)
                combo_rule = self._get_combo_rule(product.id or 0, combo_product.id or 0)
                unit_price = self._combo_price(combo_rule, base_price, combo_base_price)
                subtotal = unit_price * item.cantidad
                requires_confirmation = combo_rule.requiere_confirmacion

            unit_price = self._money(unit_price)
            priced_items.append(
                PricedItem(
                    item=item,
                    precio_unitario=unit_price,
                    categoria_venta_id=sale_category.id or 0,
                    subtotal=self._money(subtotal),
                    requiere_confirmacion=requires_confirmation,
                )
            )
        return priced_items

    def _resolve_sale_category(
        self,
        items: list[OrderItemInput],
        contexto_origen: str,
        origin_category: Categoria,
    ) -> Categoria:
        if not origin_category.activa:
            raise ValidationError("El contexto de venta no esta activo.")
        if origin_category.es_automatica:
            raise ValidationError("El contexto automatico no puede seleccionarse manualmente.")

        if contexto_origen == EVENTS_CONTEXT_CODE:
            minimum = origin_category.cantidad_minima_total or 0
            if self._total_order_units(items) < minimum:
                raise ValidationError(
                    f"El contexto EVENTOS requiere un minimo de {minimum} unidades."
                )
            return origin_category

        if contexto_origen in WHOLESALE_ELIGIBLE_CONTEXTS:
            wholesale_category = self._get_category_by_code(WHOLESALE_CONTEXT_CODE)
            wholesale_minimum = wholesale_category.cantidad_minima_total or 0
            if (
                wholesale_category.activa
                and wholesale_minimum > 0
                and self._total_order_units(items) >= wholesale_minimum
            ):
                return wholesale_category

        return origin_category

    @staticmethod
    def _total_order_units(items: list[OrderItemInput]) -> int:
        return sum(item.cantidad for item in items)

    def _load_products(self, items: list[OrderItemInput]) -> dict[int, Producto]:
        product_ids = {item.producto_id for item in items}
        product_ids.update(item.producto_combo_id for item in items if item.producto_combo_id is not None)
        products = self.session.exec(select(Producto).where(Producto.id.in_(product_ids))).all()
        product_by_id = {product.id or 0: product for product in products}
        missing = product_ids - set(product_by_id)
        if missing:
            raise ValidationError(f"Productos inexistentes: {sorted(missing)}.")
        return product_by_id

    def _get_category_by_code(self, code: str) -> Categoria:
        category = self.session.exec(select(Categoria).where(Categoria.codigo == code)).first()
        if category is None:
            raise ValidationError(f"Contexto de venta inexistente: {code}.")
        return category

    def _prices_for_category(self, category_id: int) -> dict[int, Decimal]:
        rows = self.session.exec(
            select(ProductoCategoria).where(
                ProductoCategoria.categoria_id == category_id,
                ProductoCategoria.activo == True,  # noqa: E712
            )
        ).all()
        return {row.producto_id: row.precio for row in rows}

    def _item_base_price(
        self,
        product_id: int,
        category_prices: dict[int, Decimal],
        *,
        is_combo: bool,
    ) -> Decimal:
        if product_id not in category_prices:
            raise ValidationError("El producto no tiene precio configurado para el contexto.")
        return category_prices[product_id]

    def _apply_promotion_to_line(
        self,
        *,
        base_price: Decimal,
        quantity: int,
        promotion: AppliedPromotion,
    ) -> tuple[Decimal, Decimal]:
        if promotion.precio_total is None:
            unit_price = self._money(promotion.precio_unitario)
            return unit_price, self._money(unit_price * quantity)

        package_count = quantity // promotion.cantidad_minima
        remainder = quantity % promotion.cantidad_minima
        subtotal = (promotion.precio_total * package_count) + (base_price * remainder)
        effective_unit = subtotal / Decimal(quantity)
        return self._money(effective_unit), self._money(subtotal)

    def _eligible_promotions(
        self,
        items: list[OrderItemInput],
        category_prices: dict[int, Decimal],
    ) -> dict[int, AppliedPromotion]:
        quantities_by_product = {
            item.producto_id: sum(
                i.cantidad
                for i in items
                if i.producto_id == item.producto_id and i.producto_combo_id is None
            )
            for item in items
            if item.producto_combo_id is None
        }
        promotions = self.session.exec(
            select(Promocion).where(
                Promocion.activa == True,  # noqa: E712
                Promocion.tipo == TipoPromocion.PRECIO_UNITARIO_POR_CANTIDAD,
            )
        ).all()

        prices: dict[int, AppliedPromotion] = {}
        for promotion in promotions:
            links = self.session.exec(
                select(PromocionProducto).where(PromocionProducto.promocion_id == promotion.id)
            ).all()
            eligible_product_ids = {link.producto_id for link in links}
            eligible_quantity = sum(
                quantity
                for product_id, quantity in quantities_by_product.items()
                if product_id in eligible_product_ids
            )
            if eligible_quantity < promotion.cantidad_minima:
                continue
            for product_id in eligible_product_ids:
                if product_id not in quantities_by_product:
                    continue
                candidate = AppliedPromotion(
                    precio_unitario=promotion.precio_unitario_promocional,
                    cantidad_minima=promotion.cantidad_minima,
                    precio_total=promotion.precio_total_promocional,
                )
                current = prices.get(product_id)
                if current is None or self._promotion_line_total(
                    quantities_by_product[product_id],
                    category_price=category_prices.get(product_id),
                    promotion=candidate,
                ) < self._promotion_line_total(
                    quantities_by_product[product_id],
                    category_price=category_prices.get(product_id),
                    promotion=current,
                ):
                    prices[product_id] = candidate
        return prices

    @staticmethod
    def _promotion_line_total(
        quantity: int,
        category_price: Decimal | None,
        promotion: AppliedPromotion,
    ) -> Decimal:
        if promotion.precio_total is None:
            return promotion.precio_unitario * quantity
        package_count = quantity // promotion.cantidad_minima
        remainder = quantity % promotion.cantidad_minima
        remainder_price = (category_price or promotion.precio_unitario) * remainder
        return (promotion.precio_total * package_count) + remainder_price

    def _get_combo_rule(self, product_a_id: int, product_b_id: int) -> ComboRegla:
        combo_rule = self.session.exec(
            select(ComboRegla).where(
                (
                    (ComboRegla.producto_a_id == product_a_id)
                    & (ComboRegla.producto_b_id == product_b_id)
                )
                | (
                    (ComboRegla.producto_a_id == product_b_id)
                    & (ComboRegla.producto_b_id == product_a_id)
                )
            )
        ).first()
        if combo_rule is None:
            raise ValidationError("La combinacion de productos no esta habilitada.")
        return combo_rule

    def _combo_price(
        self,
        combo_rule: ComboRegla,
        product_a_price: Decimal,
        product_b_price: Decimal,
    ) -> Decimal:
        if combo_rule.regla_precio == ReglaPrecioCombo.MAYOR_VALOR:
            return max(product_a_price, product_b_price)
        if combo_rule.regla_precio == ReglaPrecioCombo.PROMEDIO:
            return (product_a_price + product_b_price) / Decimal("2")
        if combo_rule.precio_fijo_combo is None:
            raise ValidationError("El combo con precio fijo no tiene precio configurado.")
        return combo_rule.precio_fijo_combo

    def _build_whatsapp_url(
        self,
        pedido: Pedido,
        data: PublicOrderInput,
        priced_items: list[PricedItem],
    ) -> str:
        lines = [
            f"Pedido {pedido.codigo} requiere confirmacion",
            f"Cliente: {data.nombre_apellido}",
            f"Telefono: {normalize_phone(data.telefono)}",
            f"Entrega: {data.fecha_entrega.isoformat()}",
            f"Total: {pedido.monto_total}",
        ]
        for priced_item in priced_items:
            lines.append(
                f"- Producto {priced_item.item.producto_id}"
                f"{' + ' + str(priced_item.item.producto_combo_id) if priced_item.item.producto_combo_id else ''}"
                f" x{priced_item.item.cantidad}: {priced_item.precio_unitario}"
            )
        return f"https://wa.me/?text={quote(chr(10).join(lines))}"

    @staticmethod
    def _money(value: Decimal) -> Decimal:
        return Decimal(value).quantize(MONEY_QUANT)

    @staticmethod
    def _to_read(pedido: Pedido) -> PedidoRead:
        return PedidoRead(
            id=pedido.id or 0,
            codigo=pedido.codigo,
            fecha_entrega=pedido.fecha_entrega,
            cliente_id=pedido.cliente_id,
            direccion_delivery=pedido.direccion_delivery,
            direccion_lat=pedido.direccion_lat,
            direccion_lng=pedido.direccion_lng,
            zona_envio_id=pedido.zona_envio_id,
            costo_envio=pedido.costo_envio,
            forma_pago=pedido.forma_pago,
            estado=pedido.estado,
            observaciones=pedido.observaciones,
            monto_total=pedido.monto_total,
            created_at=pedido.created_at,
            updated_at=pedido.updated_at,
        )


def normalize_phone(phone: str) -> str:
    normalized = "".join(char for char in phone.strip() if char.isdigit() or char == "+")
    if normalized.startswith("00"):
        normalized = f"+{normalized[2:]}"
    return normalized
