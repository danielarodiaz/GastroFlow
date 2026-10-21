"""Add split payments, item add-ons, and nullable historical phones."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0011_split_payments_addons"
down_revision = "0010_special_orders"
branch_labels = None
depends_on = None

forma_pago = postgresql.ENUM(
    "TRANSFERENCIA", "EFECTIVO", "MIXTO", name="forma_pago", create_type=False
)


def upgrade():
    # PostgreSQL only allows a newly-added enum value to be used after the
    # transaction that introduced it has committed.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE forma_pago ADD VALUE IF NOT EXISTS 'MIXTO'")
    op.alter_column("cliente", "telefono", existing_type=sa.String(length=40), nullable=True)

    op.create_table(
        "agregado",
        sa.Column("codigo", sa.String(length=50), nullable=False),
        sa.Column("nombre", sa.String(length=140), nullable=False),
        sa.Column("precio", sa.Numeric(12, 2), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agregado_codigo", "agregado", ["codigo"], unique=True)
    op.create_index("ix_agregado_nombre", "agregado", ["nombre"], unique=False)

    op.create_table(
        "agregado_categoria",
        sa.Column("agregado_id", sa.Integer(), nullable=False),
        sa.Column("categoria_id", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["agregado_id"], ["agregado.id"]),
        sa.ForeignKeyConstraint(["categoria_id"], ["categoria.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agregado_id", "categoria_id", name="uq_agregado_categoria"),
    )
    op.create_index("ix_agregado_categoria_agregado_id", "agregado_categoria", ["agregado_id"])
    op.create_index("ix_agregado_categoria_categoria_id", "agregado_categoria", ["categoria_id"])

    op.create_table(
        "pedido_pago",
        sa.Column("pedido_id", sa.Integer(), nullable=False),
        sa.Column("forma_pago", forma_pago, nullable=False),
        sa.Column("monto", sa.Numeric(12, 2), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["pedido_id"], ["pedido.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pedido_pago_pedido_id", "pedido_pago", ["pedido_id"])
    op.execute(sa.text("""
        INSERT INTO pedido_pago (pedido_id, forma_pago, monto)
        SELECT id, forma_pago, monto_total FROM pedido
    """))

    op.create_table(
        "pedido_item_agregado",
        sa.Column("pedido_item_id", sa.Integer(), nullable=False),
        sa.Column("agregado_id", sa.Integer(), nullable=False),
        sa.Column("agregado_nombre", sa.String(length=140), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.Column("precio_unitario", sa.Numeric(12, 2), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["agregado_id"], ["agregado.id"]),
        sa.ForeignKeyConstraint(["pedido_item_id"], ["pedido_item.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pedido_item_agregado_pedido_item_id", "pedido_item_agregado", ["pedido_item_id"])

    op.execute(sa.text("""
        INSERT INTO agregado (codigo, nombre, precio, activo)
        VALUES ('HUEVO', 'Huevo', 1000.00, true)
        ON CONFLICT (codigo) DO NOTHING
    """))
    op.execute(sa.text("""
        INSERT INTO agregado_categoria (agregado_id, categoria_id)
        SELECT a.id, c.id
        FROM agregado a
        JOIN categoria c ON c.codigo = 'LISTA_COMER'
        WHERE a.codigo = 'HUEVO'
        ON CONFLICT (agregado_id, categoria_id) DO NOTHING
    """))


def downgrade():
    op.drop_index("ix_pedido_item_agregado_pedido_item_id", table_name="pedido_item_agregado")
    op.drop_table("pedido_item_agregado")
    op.drop_index("ix_pedido_pago_pedido_id", table_name="pedido_pago")
    op.drop_table("pedido_pago")
    op.drop_index("ix_agregado_categoria_categoria_id", table_name="agregado_categoria")
    op.drop_index("ix_agregado_categoria_agregado_id", table_name="agregado_categoria")
    op.drop_table("agregado_categoria")
    op.drop_index("ix_agregado_nombre", table_name="agregado")
    op.drop_index("ix_agregado_codigo", table_name="agregado")
    op.drop_table("agregado")
    op.alter_column("cliente", "telefono", existing_type=sa.String(length=40), nullable=False)
    # PostgreSQL enum values are intentionally not removed during downgrade.
