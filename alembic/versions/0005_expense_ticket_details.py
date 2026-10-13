"""expense ticket details

Revision ID: 0005_expense_ticket_details
Revises: 0004_app_config
Create Date: 2026-10-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "0005_expense_ticket_details"
down_revision: str | None = "0004_app_config"
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


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if not _has_column(table_name, column.name):
        op.add_column(table_name, column)


def _drop_column_if_present(table_name: str, column_name: str) -> None:
    if _has_column(table_name, column_name):
        op.drop_column(table_name, column_name)


def upgrade() -> None:
    _add_column_if_missing("gasto", sa.Column("observaciones", sa.String(), nullable=True))
    _add_column_if_missing("gasto", sa.Column("monto_total", sa.Numeric(12, 2), nullable=True))

    if not _has_table("gasto_detalle"):
        op.create_table(
            "gasto_detalle",
            sa.Column("gasto_id", sa.Integer(), nullable=False),
            sa.Column("motivo_gasto_id", sa.Integer(), nullable=False),
            sa.Column("marca_id", sa.Integer(), nullable=False),
            sa.Column("descripcion", sa.String(), nullable=True),
            sa.Column("cantidad", sa.Numeric(12, 3), nullable=False),
            sa.Column("unidad_medida", sa.String(length=40), nullable=False),
            sa.Column("precio_unitario", sa.Numeric(12, 2), nullable=False),
            sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["gasto_id"], ["gasto.id"]),
            sa.ForeignKeyConstraint(["marca_id"], ["marca.id"]),
            sa.ForeignKeyConstraint(["motivo_gasto_id"], ["motivo_gasto.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_gasto_detalle_gasto_id", "gasto_detalle", ["gasto_id"])

    old_detail_columns = {
        "motivo_gasto_id",
        "marca_id",
        "cantidad",
        "unidad_medida",
        "precio",
    }
    if all(_has_column("gasto", column) for column in old_detail_columns):
        op.execute(
            """
            INSERT INTO gasto_detalle (
                gasto_id, motivo_gasto_id, marca_id, descripcion, cantidad,
                unidad_medida, precio_unitario, subtotal
            )
            SELECT g.id, g.motivo_gasto_id, g.marca_id, NULL, g.cantidad,
                   g.unidad_medida, g.precio, g.cantidad * g.precio
            FROM gasto g
            WHERE NOT EXISTS (
                SELECT 1
                FROM gasto_detalle gd
                WHERE gd.gasto_id = g.id
            )
            """
        )
        op.execute(
            """
            UPDATE gasto g
            SET monto_total = totals.total
            FROM (
                SELECT gasto_id, SUM(subtotal) AS total
                FROM gasto_detalle
                GROUP BY gasto_id
            ) totals
            WHERE totals.gasto_id = g.id
              AND g.monto_total IS NULL
            """
        )

    op.execute("UPDATE gasto SET monto_total = 0 WHERE monto_total IS NULL")
    op.alter_column("gasto", "monto_total", nullable=False)

    _drop_column_if_present("gasto", "motivo_gasto_id")
    _drop_column_if_present("gasto", "marca_id")
    _drop_column_if_present("gasto", "cantidad")
    _drop_column_if_present("gasto", "unidad_medida")
    _drop_column_if_present("gasto", "precio")


def downgrade() -> None:
    _add_column_if_missing("gasto", sa.Column("motivo_gasto_id", sa.Integer(), nullable=True))
    _add_column_if_missing("gasto", sa.Column("marca_id", sa.Integer(), nullable=True))
    _add_column_if_missing("gasto", sa.Column("cantidad", sa.Numeric(12, 3), nullable=True))
    _add_column_if_missing("gasto", sa.Column("unidad_medida", sa.String(length=40), nullable=True))
    _add_column_if_missing("gasto", sa.Column("precio", sa.Numeric(12, 2), nullable=True))

    if _has_table("gasto_detalle"):
        op.execute(
            """
            UPDATE gasto g
            SET motivo_gasto_id = first_detail.motivo_gasto_id,
                marca_id = first_detail.marca_id,
                cantidad = first_detail.cantidad,
                unidad_medida = first_detail.unidad_medida,
                precio = first_detail.precio_unitario
            FROM (
                SELECT DISTINCT ON (gasto_id)
                       gasto_id, motivo_gasto_id, marca_id, cantidad, unidad_medida, precio_unitario
                FROM gasto_detalle
                ORDER BY gasto_id, id
            ) first_detail
            WHERE first_detail.gasto_id = g.id
            """
        )
        op.drop_index("ix_gasto_detalle_gasto_id", table_name="gasto_detalle")
        op.drop_table("gasto_detalle")

    op.execute("UPDATE gasto SET cantidad = 0 WHERE cantidad IS NULL")
    op.execute("UPDATE gasto SET precio = 0 WHERE precio IS NULL")
    op.execute("UPDATE gasto SET unidad_medida = 'UNIDAD' WHERE unidad_medida IS NULL")
    op.alter_column("gasto", "motivo_gasto_id", nullable=False)
    op.alter_column("gasto", "marca_id", nullable=False)
    op.alter_column("gasto", "cantidad", nullable=False)
    op.alter_column("gasto", "unidad_medida", nullable=False)
    op.alter_column("gasto", "precio", nullable=False)

    _drop_column_if_present("gasto", "monto_total")
    _drop_column_if_present("gasto", "observaciones")
