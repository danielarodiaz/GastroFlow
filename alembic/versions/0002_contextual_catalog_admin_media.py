"""contextual catalog admin media

Revision ID: 0002_catalog_media
Revises: 0001_initial_schema
Create Date: 2026-10-02 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002_catalog_media"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("categoria", sa.Column("descripcion_publica", sa.String(), nullable=True))
    op.add_column("categoria", sa.Column("foto_url", sa.String(length=500), nullable=True))
    op.add_column("categoria", sa.Column("orden", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("categoria", sa.Column("visible_cliente", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("categoria", sa.Column("es_automatica", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("categoria", sa.Column("cantidad_minima_total", sa.Integer(), nullable=True))
    op.add_column("categoria", sa.Column("prioridad", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("categoria", sa.Column("acumulable", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("categoria", sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.true()))

    op.execute(
        """
        UPDATE categoria
        SET visible_cliente = false,
            es_automatica = true,
            cantidad_minima_total = COALESCE(cantidad_minima_total, 10),
            prioridad = 100,
            acumulable = false
        WHERE codigo = 'MAYORISTA'
        """
    )
    op.execute(
        """
        INSERT INTO categoria (
            codigo, nombre, visible_cliente, es_automatica, cantidad_minima_total,
            prioridad, acumulable, activa, orden
        )
        SELECT 'EVENTOS', 'Eventos', true, false, 10, 50, false, true, 0
        WHERE NOT EXISTS (SELECT 1 FROM categoria WHERE codigo = 'EVENTOS')
        """
    )

    op.create_table(
        "producto_categoria",
        sa.Column("producto_id", sa.Integer(), nullable=False),
        sa.Column("categoria_id", sa.Integer(), nullable=False),
        sa.Column("precio", sa.Numeric(12, 2), nullable=False),
        sa.Column("descripcion_publica", sa.String(), nullable=True),
        sa.Column("foto_url", sa.String(length=500), nullable=True),
        sa.Column("visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("orden", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("destacado", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["categoria_id"], ["categoria.id"]),
        sa.ForeignKeyConstraint(["producto_id"], ["producto.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("producto_id", "categoria_id", name="uq_producto_categoria"),
    )
    op.create_index("ix_producto_categoria_categoria_id", "producto_categoria", ["categoria_id"])
    op.create_index("ix_producto_categoria_producto_id", "producto_categoria", ["producto_id"])

    op.execute(
        """
        INSERT INTO producto_categoria (producto_id, categoria_id, precio, activo, visible, orden, destacado)
        SELECT id, categoria_id, precio, true, true, 0, false
        FROM producto
        WHERE categoria_id IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO producto_categoria (producto_id, categoria_id, precio, activo, visible, orden, destacado)
        SELECT pmp.producto_id, c.id, pmp.precio_unitario_mayorista, true, false, 0, false
        FROM precio_mayorista_producto pmp
        JOIN regla_mayorista rm ON rm.id = pmp.regla_mayorista_id
        JOIN categoria c ON c.codigo = 'MAYORISTA'
        ON CONFLICT ON CONSTRAINT uq_producto_categoria DO NOTHING
        """
    )

    op.add_column("producto", sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_index("ix_producto_nombre", "producto", ["nombre"], unique=False)
    op.drop_constraint("producto_categoria_id_fkey", "producto", type_="foreignkey")
    op.drop_column("producto", "categoria_id")
    op.drop_column("producto", "precio")

    op.execute("DROP INDEX IF EXISTS ix_marca_nombre")
    op.create_index("ix_marca_nombre", "marca", ["nombre"], unique=False)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_marca_nombre_lower ON marca (LOWER(nombre))")
    op.execute("DROP INDEX IF EXISTS ix_motivo_gasto_nombre")
    op.create_index("ix_motivo_gasto_nombre", "motivo_gasto", ["nombre"], unique=False)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_motivo_gasto_nombre_lower ON motivo_gasto (LOWER(nombre))"
    )

    op.execute("DROP TABLE IF EXISTS precio_mayorista_producto")
    op.execute("DROP TABLE IF EXISTS regla_mayorista")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_combo_regla_par "
        "ON combo_regla (LEAST(producto_a_id, producto_b_id), "
        "GREATEST(producto_a_id, producto_b_id))"
    )

    op.add_column("pedido_item", sa.Column("categoria_venta_id", sa.Integer(), nullable=True))
    op.add_column("pedido_item", sa.Column("subtotal", sa.Numeric(12, 2), nullable=True))
    op.execute(
        """
        UPDATE pedido_item pi
        SET categoria_venta_id = pc.categoria_id,
            subtotal = pi.precio_unitario * pi.cantidad
        FROM producto_categoria pc
        WHERE pc.producto_id = pi.producto_id
          AND pi.categoria_venta_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE pedido_item
        SET subtotal = precio_unitario * cantidad
        WHERE subtotal IS NULL
        """
    )
    op.alter_column("pedido_item", "categoria_venta_id", nullable=False)
    op.alter_column("pedido_item", "subtotal", nullable=False)
    op.create_foreign_key(
        "pedido_item_categoria_venta_id_fkey",
        "pedido_item",
        "categoria",
        ["categoria_venta_id"],
        ["id"],
    )
    op.create_index("ix_pedido_item_pedido_id", "pedido_item", ["pedido_id"])

    op.alter_column("categoria", "orden", server_default=None)
    op.alter_column("categoria", "visible_cliente", server_default=None)
    op.alter_column("categoria", "es_automatica", server_default=None)
    op.alter_column("categoria", "prioridad", server_default=None)
    op.alter_column("categoria", "acumulable", server_default=None)
    op.alter_column("categoria", "activa", server_default=None)
    op.alter_column("producto", "activo", server_default=None)
    op.alter_column("producto_categoria", "visible", server_default=None)
    op.alter_column("producto_categoria", "orden", server_default=None)
    op.alter_column("producto_categoria", "destacado", server_default=None)
    op.alter_column("producto_categoria", "activo", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_pedido_item_pedido_id", table_name="pedido_item")
    op.drop_constraint("pedido_item_categoria_venta_id_fkey", "pedido_item", type_="foreignkey")
    op.drop_column("pedido_item", "subtotal")
    op.drop_column("pedido_item", "categoria_venta_id")

    op.execute("DROP INDEX IF EXISTS uq_combo_regla_par")
    op.create_table(
        "regla_mayorista",
        sa.Column("codigo", sa.String(length=80), nullable=False),
        sa.Column("categoria_id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=160), nullable=False),
        sa.Column("cantidad_minima_total", sa.Integer(), nullable=False),
        sa.Column("activa", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["categoria_id"], ["categoria.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_regla_mayorista_codigo", "regla_mayorista", ["codigo"], unique=True)
    op.create_table(
        "precio_mayorista_producto",
        sa.Column("regla_mayorista_id", sa.Integer(), nullable=False),
        sa.Column("producto_id", sa.Integer(), nullable=False),
        sa.Column("precio_unitario_mayorista", sa.Numeric(12, 2), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["producto_id"], ["producto.id"]),
        sa.ForeignKeyConstraint(["regla_mayorista_id"], ["regla_mayorista.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("regla_mayorista_id", "producto_id"),
    )

    op.add_column("producto", sa.Column("precio", sa.Numeric(12, 2), nullable=True))
    op.add_column("producto", sa.Column("categoria_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE producto p
        SET precio = pc.precio,
            categoria_id = pc.categoria_id
        FROM producto_categoria pc
        WHERE pc.producto_id = p.id
          AND p.precio IS NULL
        """
    )
    op.alter_column("producto", "precio", nullable=False)
    op.alter_column("producto", "categoria_id", nullable=False)
    op.create_foreign_key("producto_categoria_id_fkey", "producto", "categoria", ["categoria_id"], ["id"])
    op.drop_index("ix_producto_nombre", table_name="producto")
    op.drop_column("producto", "activo")

    op.drop_index("ix_producto_categoria_producto_id", table_name="producto_categoria")
    op.drop_index("ix_producto_categoria_categoria_id", table_name="producto_categoria")
    op.drop_table("producto_categoria")

    op.execute("DROP INDEX IF EXISTS uq_motivo_gasto_nombre_lower")
    op.drop_index("ix_motivo_gasto_nombre", table_name="motivo_gasto")
    op.create_index("ix_motivo_gasto_nombre", "motivo_gasto", ["nombre"], unique=True)
    op.execute("DROP INDEX IF EXISTS uq_marca_nombre_lower")
    op.drop_index("ix_marca_nombre", table_name="marca")
    op.create_index("ix_marca_nombre", "marca", ["nombre"], unique=True)

    op.drop_column("categoria", "activa")
    op.drop_column("categoria", "acumulable")
    op.drop_column("categoria", "prioridad")
    op.drop_column("categoria", "cantidad_minima_total")
    op.drop_column("categoria", "es_automatica")
    op.drop_column("categoria", "visible_cliente")
    op.drop_column("categoria", "orden")
    op.drop_column("categoria", "foto_url")
    op.drop_column("categoria", "descripcion_publica")
