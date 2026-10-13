"""contextual catalog admin media

Revision ID: 0002_catalog_media
Revises: 0001_initial_schema
Create Date: 2026-10-02 00:00:00

This revision is intentionally defensive. The current baseline migration already
contains part of this schema, while older local databases may still need the
incremental changes. Keep this file idempotent so a fresh Supabase database can
run the full Alembic chain from base to head.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "0002_catalog_media"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> sa.Inspector:
    return inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return table_name in _inspector().get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return column_name in {column["name"] for column in _inspector().get_columns(table_name)}


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return index_name in {index["name"] for index in _inspector().get_indexes(table_name)}


def _has_foreign_key(table_name: str, constraint_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return constraint_name in {fk["name"] for fk in _inspector().get_foreign_keys(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if not _has_column(table_name, column.name):
        op.add_column(table_name, column)


def _drop_column_if_present(table_name: str, column_name: str) -> None:
    if _has_column(table_name, column_name):
        op.drop_column(table_name, column_name)


def _create_index_if_missing(table_name: str, index_name: str, columns: list[str], *, unique: bool = False) -> None:
    if not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    _add_column_if_missing("categoria", sa.Column("descripcion_publica", sa.String(), nullable=True))
    _add_column_if_missing("categoria", sa.Column("foto_url", sa.String(length=500), nullable=True))
    _add_column_if_missing("categoria", sa.Column("orden", sa.Integer(), nullable=False, server_default="0"))
    _add_column_if_missing(
        "categoria",
        sa.Column("visible_cliente", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    _add_column_if_missing(
        "categoria",
        sa.Column("es_automatica", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_column_if_missing("categoria", sa.Column("cantidad_minima_total", sa.Integer(), nullable=True))
    _add_column_if_missing("categoria", sa.Column("prioridad", sa.Integer(), nullable=False, server_default="0"))
    _add_column_if_missing(
        "categoria",
        sa.Column("acumulable", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_column_if_missing("categoria", sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.true()))

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

    if not _has_table("producto_categoria"):
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
    _create_index_if_missing("producto_categoria", "ix_producto_categoria_categoria_id", ["categoria_id"])
    _create_index_if_missing("producto_categoria", "ix_producto_categoria_producto_id", ["producto_id"])

    if _has_column("producto", "categoria_id") and _has_column("producto", "precio"):
        op.execute(
            """
            INSERT INTO producto_categoria (producto_id, categoria_id, precio, activo, visible, orden, destacado)
            SELECT id, categoria_id, precio, true, true, 0, false
            FROM producto
            WHERE categoria_id IS NOT NULL
            ON CONFLICT ON CONSTRAINT uq_producto_categoria DO NOTHING
            """
        )

    if _has_table("precio_mayorista_producto") and _has_table("regla_mayorista"):
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

    _add_column_if_missing("producto", sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()))
    _create_index_if_missing("producto", "ix_producto_nombre", ["nombre"])
    if _has_foreign_key("producto", "producto_categoria_id_fkey"):
        op.drop_constraint("producto_categoria_id_fkey", "producto", type_="foreignkey")
    _drop_column_if_present("producto", "categoria_id")
    _drop_column_if_present("producto", "precio")

    op.execute("DROP INDEX IF EXISTS ix_marca_nombre")
    _create_index_if_missing("marca", "ix_marca_nombre", ["nombre"])
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_marca_nombre_lower ON marca (LOWER(nombre))")
    op.execute("DROP INDEX IF EXISTS ix_motivo_gasto_nombre")
    _create_index_if_missing("motivo_gasto", "ix_motivo_gasto_nombre", ["nombre"])
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_motivo_gasto_nombre_lower ON motivo_gasto (LOWER(nombre))")

    op.execute("DROP TABLE IF EXISTS precio_mayorista_producto")
    op.execute("DROP TABLE IF EXISTS regla_mayorista")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_combo_regla_par "
        "ON combo_regla (LEAST(producto_a_id, producto_b_id), "
        "GREATEST(producto_a_id, producto_b_id))"
    )

    _add_column_if_missing("pedido_item", sa.Column("categoria_venta_id", sa.Integer(), nullable=True))
    _add_column_if_missing("pedido_item", sa.Column("subtotal", sa.Numeric(12, 2), nullable=True))
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
    if not _has_foreign_key("pedido_item", "pedido_item_categoria_venta_id_fkey"):
        op.create_foreign_key(
            "pedido_item_categoria_venta_id_fkey",
            "pedido_item",
            "categoria",
            ["categoria_venta_id"],
            ["id"],
        )
    _create_index_if_missing("pedido_item", "ix_pedido_item_pedido_id", ["pedido_id"])

    for table_name, column_name in (
        ("categoria", "orden"),
        ("categoria", "visible_cliente"),
        ("categoria", "es_automatica"),
        ("categoria", "prioridad"),
        ("categoria", "acumulable"),
        ("categoria", "activa"),
        ("producto", "activo"),
        ("producto_categoria", "visible"),
        ("producto_categoria", "orden"),
        ("producto_categoria", "destacado"),
        ("producto_categoria", "activo"),
    ):
        if _has_column(table_name, column_name):
            op.alter_column(table_name, column_name, server_default=None)


def downgrade() -> None:
    # This revision is kept as a compatibility bridge between an older
    # incremental schema and the current squashed baseline. Downgrading it
    # safely would require knowing which baseline created each column/table,
    # so the downgrade is intentionally a no-op.
    pass
