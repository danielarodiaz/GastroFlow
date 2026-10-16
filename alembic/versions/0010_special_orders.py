"""Enable special-order availability by product/category and snapshot order lines."""

from alembic import op
import sqlalchemy as sa

revision = "0010_special_orders"
down_revision = "0009_promotion_categories"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("producto_categoria", sa.Column("permite_pedido_especial", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("pedido_item", sa.Column("es_especial", sa.Boolean(), nullable=False, server_default=sa.false()))
    # Enable only the four requested presentations, retaining their configured prices.
    op.execute(sa.text("""
        UPDATE producto_categoria SET permite_pedido_especial = true, visible = false
        WHERE categoria_id IN (SELECT id FROM categoria WHERE codigo IN ('LISTA_HORNO', 'EVENTOS'))
          AND producto_id IN (
              SELECT id FROM producto WHERE LOWER(TRIM(nombre)) IN ('fugazzetta', 'fugazzeta', 'napolitana')
          )
    """))


def downgrade():
    op.drop_column("pedido_item", "es_especial")
    op.drop_column("producto_categoria", "permite_pedido_especial")
