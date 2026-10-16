"""Validate and replace a promotion's category scope and package composition."""

from sqlalchemy import delete
from sqlmodel import Session, select

from gastroflow.domain.errors import ValidationError
from gastroflow.models import Categoria, Producto, ProductoCategoria, Promocion, PromocionCategoria, PromocionItem


def configure_promotion(
    session: Session,
    promotion: Promocion,
    category_ids: list[int],
    product_ids: list[int],
    package_items: list[tuple[int, int, int]],
) -> None:
    categories, products = set(category_ids), set(product_ids)
    if not categories:
        raise ValidationError("Selecciona al menos una categoría para la promo.")
    if not products:
        raise ValidationError("Selecciona al menos un producto elegible.")
    allowed_categories = {category.id for category in session.exec(select(Categoria).where(
        Categoria.id.in_(categories), Categoria.activa == True, Categoria.es_automatica == False,
        Categoria.codigo != "EVENTOS",
    )).all()}
    if allowed_categories != categories:
        raise ValidationError("Las promos requieren categorías activas, sin Mayorista ni Eventos.")
    available = {(relation.producto_id, relation.categoria_id) for relation in session.exec(
        select(ProductoCategoria).join(Producto, Producto.id == ProductoCategoria.producto_id).where(
            ProductoCategoria.categoria_id.in_(categories), ProductoCategoria.producto_id.in_(products),
            ProductoCategoria.activo == True, Producto.activo == True,
            ProductoCategoria.permite_pedido_especial == False,
        )
    ).all()}
    if {product for product, _ in available} != products or {category for _, category in available} != categories:
        raise ValidationError("Cada producto debe pertenecer a una categoría seleccionada y cada categoría debe tener productos elegibles.")
    if promotion.cantidad_minima <= 0 or promotion.precio_unitario_promocional < 0:
        raise ValidationError("Revisa la cantidad mínima y el precio promocional.")
    if promotion.precio_total_promocional is not None and promotion.precio_total_promocional <= 0:
        raise ValidationError("El precio total del paquete debe ser mayor a cero.")
    if package_items:
        if promotion.precio_total_promocional is None:
            raise ValidationError("Un paquete combinado requiere Precio total del paquete.")
        pairs = [(product, category) for product, category, _ in package_items]
        if len(set(pairs)) != len(pairs) or any(pair not in available for pair in pairs):
            raise ValidationError("Revisa los productos y categorías del paquete combinado.")
        if any(not isinstance(quantity, int) or quantity <= 0 for _, _, quantity in package_items):
            raise ValidationError("Cada componente del paquete debe tener una cantidad entera mayor a cero.")
        if {product for product, _, _ in package_items} != products or {category for _, category, _ in package_items} != categories:
            raise ValidationError("Define las cantidades de todos los productos y categorías del paquete.")
        promotion.cantidad_minima = sum(quantity for _, _, quantity in package_items)
    session.exec(delete(PromocionItem).where(PromocionItem.promocion_id == promotion.id))
    session.exec(delete(PromocionCategoria).where(PromocionCategoria.promocion_id == promotion.id))
    session.add_all([PromocionCategoria(promocion_id=promotion.id, categoria_id=category) for category in categories])
    session.add_all([PromocionItem(promocion_id=promotion.id, producto_id=product, categoria_id=category, cantidad=quantity)
                     for product, category, quantity in package_items])
    session.add(promotion)
