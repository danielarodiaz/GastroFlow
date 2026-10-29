"""Allow expense details without a brand."""

from alembic import op
import sqlalchemy as sa


revision = "0014_optional_expense_brand"
down_revision = "0013_order_revision_history"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "gasto_detalle",
        "marca_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade():
    # A rollback needs a valid foreign key for details that were intentionally
    # stored without a brand. The sentinel only exists in that rollback path.
    op.execute(
        """
        INSERT INTO marca (nombre)
        SELECT 'SIN MARCA'
        WHERE NOT EXISTS (
            SELECT 1 FROM marca WHERE LOWER(nombre) = LOWER('SIN MARCA')
        )
        """
    )
    op.execute(
        """
        UPDATE gasto_detalle
        SET marca_id = (
            SELECT id FROM marca WHERE LOWER(nombre) = LOWER('SIN MARCA') LIMIT 1
        )
        WHERE marca_id IS NULL
        """
    )
    op.alter_column(
        "gasto_detalle",
        "marca_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
