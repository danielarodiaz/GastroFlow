"""Store the requested delivery time on orders.

Revision ID: 0008_order_delivery_time
Revises: 0007_preserve_display_text
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_order_delivery_time"
down_revision = "0007_preserve_display_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pedido", sa.Column("horario_entrega", sa.Time(), nullable=True))


def downgrade() -> None:
    op.drop_column("pedido", "horario_entrega")
