"""Scope promotions by category and support packages with a fixed composition.

Existing promotions with ambiguous scope remain unassigned (never global).
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_promotion_categories"
down_revision = "0008_order_delivery_time"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "promocion_categoria",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("promocion_id", sa.Integer(), sa.ForeignKey("promocion.id"), nullable=False),
        sa.Column("categoria_id", sa.Integer(), sa.ForeignKey("categoria.id"), nullable=False),
        sa.UniqueConstraint("promocion_id", "categoria_id", name="uq_promocion_categoria"),
    )
    op.create_index("ix_promocion_categoria_promocion_id", "promocion_categoria", ["promocion_id"])
    op.create_index("ix_promocion_categoria_categoria_id", "promocion_categoria", ["categoria_id"])
    op.create_table(
        "promocion_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("promocion_id", sa.Integer(), sa.ForeignKey("promocion.id"), nullable=False),
        sa.Column("producto_id", sa.Integer(), sa.ForeignKey("producto.id"), nullable=False),
        sa.Column("categoria_id", sa.Integer(), sa.ForeignKey("categoria.id"), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.UniqueConstraint("promocion_id", "producto_id", "categoria_id", name="uq_promocion_item"),
        sa.CheckConstraint("cantidad > 0", name="ck_promocion_item_cantidad"),
    )
    op.create_index("ix_promocion_item_promocion_id", "promocion_item", ["promocion_id"])
    if op.get_context().as_sql:
        return  # Data backfill requires an online migration.
    connection = op.get_bind()
    categories = dict(connection.execute(sa.text("SELECT codigo, id FROM categoria WHERE es_automatica = false")).all())
    products_by_promo = {}
    for promo_id, product_id in connection.execute(sa.text("SELECT promocion_id, producto_id FROM promocion_producto")):
        products_by_promo.setdefault(promo_id, set()).add(product_id)
    categories_by_product = {}
    for product_id, category_id in connection.execute(sa.text("SELECT producto_id, categoria_id FROM producto_categoria WHERE activo = true")):
        categories_by_product.setdefault(product_id, set()).add(category_id)
    for promo_id, code in connection.execute(sa.text("SELECT id, codigo FROM promocion")):
        code = f"_{code.upper()}_"
        hinted_codes = {category for token, category in [
            ("_HORNO_", "LISTA_HORNO"), ("_COMER_", "LISTA_COMER"),
            ("_PRE_PIZZA_", "PRE_PIZZAS"), ("_PREPIZZA_", "PRE_PIZZAS"),
        ] if token in code}
        hinted_code = next(iter(hinted_codes)) if len(hinted_codes) == 1 else None
        product_ids = products_by_promo.get(promo_id, set())
        common = set(categories.values())
        for product_id in product_ids:
            common &= categories_by_product.get(product_id, set())
        category_id = categories.get(hinted_code) if hinted_code else None
        if category_id not in common:
            category_id = None
        if not hinted_codes and len(common) == 1 and product_ids:
            category_id = next(iter(common))
        if category_id is not None and product_ids:
            connection.execute(sa.text(
                "INSERT INTO promocion_categoria (promocion_id, categoria_id) VALUES (:promo, :category)"
            ), {"promo": promo_id, "category": category_id})


def downgrade():
    op.drop_table("promocion_item")
    op.drop_table("promocion_categoria")
