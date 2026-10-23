"""Add an immutable audit trail for administrative order changes."""

from alembic import op
import sqlalchemy as sa


revision = "0013_order_revision_history"
down_revision = "0012_secure_public_schema"
branch_labels = None
depends_on = None


DATA_API_ROLES = "anon, authenticated, service_role"


def upgrade():
    op.create_table(
        "pedido_revision",
        sa.Column("pedido_id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=True),
        sa.Column("usuario_nombre", sa.String(length=80), nullable=False),
        sa.Column("accion", sa.String(length=40), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("resumen_anterior", sa.Text(), nullable=False),
        sa.Column("resumen_nuevo", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["pedido_id"], ["pedido.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuario.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pedido_revision_pedido_id", "pedido_revision", ["pedido_id"])
    op.create_index("ix_pedido_revision_usuario_id", "pedido_revision", ["usuario_id"])

    # Internal-only data: keep it outside Supabase's public Data API.
    op.execute('ALTER TABLE public."pedido_revision" ENABLE ROW LEVEL SECURITY')
    op.execute(
        f'REVOKE ALL PRIVILEGES ON TABLE public."pedido_revision" FROM {DATA_API_ROLES}'
    )


def downgrade():
    op.drop_index("ix_pedido_revision_usuario_id", table_name="pedido_revision")
    op.drop_index("ix_pedido_revision_pedido_id", table_name="pedido_revision")
    op.drop_table("pedido_revision")
