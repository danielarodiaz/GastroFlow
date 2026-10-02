"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-23 00:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


rol_usuario = postgresql.ENUM("ADMIN", "DUENO", name="rol_usuario", create_type=False)
estado_pedido = postgresql.ENUM(
    "PEDIDO",
    "PENDIENTE_CONFIRMACION",
    "EN_PROCESO",
    "ENTREGADO",
    "CANCELADO",
    name="estado_pedido",
    create_type=False,
)
forma_pago = postgresql.ENUM("TRANSFERENCIA", "EFECTIVO", name="forma_pago", create_type=False)
unidad_venta = postgresql.ENUM("PIEZA", "UNIDAD", "DOCENA", name="unidad_venta", create_type=False)
regla_precio_combo = postgresql.ENUM(
    "MAYOR_VALOR",
    "PROMEDIO",
    "PRECIO_FIJO",
    name="regla_precio_combo",
    create_type=False,
)
tipo_promocion = postgresql.ENUM(
    "PRECIO_UNITARIO_POR_CANTIDAD",
    name="tipo_promocion",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    rol_usuario.create(bind, checkfirst=True)
    estado_pedido.create(bind, checkfirst=True)
    forma_pago.create(bind, checkfirst=True)
    unidad_venta.create(bind, checkfirst=True)
    regla_precio_combo.create(bind, checkfirst=True)
    tipo_promocion.create(bind, checkfirst=True)

    op.execute("CREATE SEQUENCE IF NOT EXISTS pedido_codigo_seq START WITH 1 INCREMENT BY 1")
    op.execute("CREATE SEQUENCE IF NOT EXISTS gasto_codigo_seq START WITH 1 INCREMENT BY 1")

    op.create_table(
        "categoria",
        sa.Column("codigo", sa.String(length=50), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("descripcion_publica", sa.String(), nullable=True),
        sa.Column("foto_url", sa.String(length=500), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("visible_cliente", sa.Boolean(), nullable=False),
        sa.Column("es_automatica", sa.Boolean(), nullable=False),
        sa.Column("cantidad_minima_total", sa.Integer(), nullable=True),
        sa.Column("prioridad", sa.Integer(), nullable=False),
        sa.Column("acumulable", sa.Boolean(), nullable=False),
        sa.Column("activa", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_categoria_codigo", "categoria", ["codigo"], unique=True)

    op.create_table(
        "cliente",
        sa.Column("nombre_apellido", sa.String(length=160), nullable=False),
        sa.Column("telefono", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cliente_telefono", "cliente", ["telefono"], unique=True)

    op.create_table(
        "marca",
        sa.Column("nombre", sa.String(length=140), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_marca_nombre", "marca", ["nombre"], unique=False)
    op.execute("CREATE UNIQUE INDEX uq_marca_nombre_lower ON marca (LOWER(nombre))")

    op.create_table(
        "motivo_gasto",
        sa.Column("nombre", sa.String(length=140), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_motivo_gasto_nombre", "motivo_gasto", ["nombre"], unique=False)
    op.execute("CREATE UNIQUE INDEX uq_motivo_gasto_nombre_lower ON motivo_gasto (LOWER(nombre))")

    op.create_table(
        "usuario",
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("rol", rol_usuario, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usuario_username", "usuario", ["username"], unique=True)

    op.create_table(
        "zona_envio",
        sa.Column("nombre", sa.String(length=140), nullable=False),
        sa.Column("costo", sa.Numeric(12, 2), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "producto",
        sa.Column("codigo", sa.String(length=50), nullable=False),
        sa.Column("nombre", sa.String(length=140), nullable=False),
        sa.Column("descripcion", sa.String(), nullable=True),
        sa.Column("fotos", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("unidad_venta", unidad_venta, nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_producto_codigo", "producto", ["codigo"], unique=True)
    op.create_index("ix_producto_nombre", "producto", ["nombre"], unique=False)

    op.create_table(
        "producto_categoria",
        sa.Column("producto_id", sa.Integer(), nullable=False),
        sa.Column("categoria_id", sa.Integer(), nullable=False),
        sa.Column("precio", sa.Numeric(12, 2), nullable=False),
        sa.Column("descripcion_publica", sa.String(), nullable=True),
        sa.Column("foto_url", sa.String(length=500), nullable=True),
        sa.Column("visible", sa.Boolean(), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("destacado", sa.Boolean(), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["categoria_id"], ["categoria.id"]),
        sa.ForeignKeyConstraint(["producto_id"], ["producto.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("producto_id", "categoria_id", name="uq_producto_categoria"),
    )
    op.create_index("ix_producto_categoria_categoria_id", "producto_categoria", ["categoria_id"])
    op.create_index("ix_producto_categoria_producto_id", "producto_categoria", ["producto_id"])

    op.create_table(
        "promocion",
        sa.Column("codigo", sa.String(length=80), nullable=False),
        sa.Column("nombre", sa.String(length=140), nullable=False),
        sa.Column("tipo", tipo_promocion, nullable=False),
        sa.Column("cantidad_minima", sa.Integer(), nullable=False),
        sa.Column("precio_unitario_promocional", sa.Numeric(12, 2), nullable=False),
        sa.Column("activa", sa.Boolean(), nullable=False),
        sa.Column("vigencia_desde", sa.DateTime(), nullable=True),
        sa.Column("vigencia_hasta", sa.DateTime(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_promocion_codigo", "promocion", ["codigo"], unique=True)

    op.create_table(
        "combo_regla",
        sa.Column("producto_a_id", sa.Integer(), nullable=False),
        sa.Column("producto_b_id", sa.Integer(), nullable=False),
        sa.Column("requiere_confirmacion", sa.Boolean(), nullable=False),
        sa.Column("regla_precio", regla_precio_combo, nullable=False),
        sa.Column("precio_fijo_combo", sa.Numeric(12, 2), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["producto_a_id"], ["producto.id"]),
        sa.ForeignKeyConstraint(["producto_b_id"], ["producto.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_combo_regla_par "
        "ON combo_regla (LEAST(producto_a_id, producto_b_id), "
        "GREATEST(producto_a_id, producto_b_id))"
    )

    op.create_table(
        "pedido",
        sa.Column("codigo", sa.String(length=30), nullable=False),
        sa.Column("fecha_entrega", sa.Date(), nullable=False),
        sa.Column("cliente_id", sa.Integer(), nullable=False),
        sa.Column("direccion_delivery", sa.String(), nullable=False),
        sa.Column("direccion_lat", sa.Numeric(10, 7), nullable=True),
        sa.Column("direccion_lng", sa.Numeric(10, 7), nullable=True),
        sa.Column("zona_envio_id", sa.Integer(), nullable=True),
        sa.Column("costo_envio", sa.Numeric(12, 2), nullable=False),
        sa.Column("forma_pago", forma_pago, nullable=False),
        sa.Column("estado", estado_pedido, nullable=False),
        sa.Column("observaciones", sa.String(), nullable=True),
        sa.Column("monto_total", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["cliente_id"], ["cliente.id"]),
        sa.ForeignKeyConstraint(["zona_envio_id"], ["zona_envio.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pedido_codigo", "pedido", ["codigo"], unique=True)

    op.create_table(
        "promocion_producto",
        sa.Column("promocion_id", sa.Integer(), nullable=False),
        sa.Column("producto_id", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["producto_id"], ["producto.id"]),
        sa.ForeignKeyConstraint(["promocion_id"], ["promocion.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("promocion_id", "producto_id"),
    )

    op.create_table(
        "gasto",
        sa.Column("codigo", sa.String(length=30), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("motivo_gasto_id", sa.Integer(), nullable=False),
        sa.Column("marca_id", sa.Integer(), nullable=False),
        sa.Column("cantidad", sa.Numeric(12, 3), nullable=False),
        sa.Column("unidad_medida", sa.String(length=40), nullable=False),
        sa.Column("precio", sa.Numeric(12, 2), nullable=False),
        sa.Column("lugar_texto", sa.String(), nullable=False),
        sa.Column("lugar_lat", sa.Numeric(10, 7), nullable=True),
        sa.Column("lugar_lng", sa.Numeric(10, 7), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["marca_id"], ["marca.id"]),
        sa.ForeignKeyConstraint(["motivo_gasto_id"], ["motivo_gasto.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gasto_codigo", "gasto", ["codigo"], unique=True)

    op.create_table(
        "pedido_item",
        sa.Column("pedido_id", sa.Integer(), nullable=False),
        sa.Column("producto_id", sa.Integer(), nullable=False),
        sa.Column("producto_combo_id", sa.Integer(), nullable=True),
        sa.Column("categoria_venta_id", sa.Integer(), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.Column("precio_unitario", sa.Numeric(12, 2), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["categoria_venta_id"], ["categoria.id"]),
        sa.ForeignKeyConstraint(["pedido_id"], ["pedido.id"]),
        sa.ForeignKeyConstraint(["producto_combo_id"], ["producto.id"]),
        sa.ForeignKeyConstraint(["producto_id"], ["producto.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pedido_item_pedido_id", "pedido_item", ["pedido_id"])


def downgrade() -> None:
    op.drop_index("ix_pedido_item_pedido_id", table_name="pedido_item")
    op.drop_table("pedido_item")
    op.drop_index("ix_gasto_codigo", table_name="gasto")
    op.drop_table("gasto")
    op.drop_table("promocion_producto")
    op.drop_index("ix_pedido_codigo", table_name="pedido")
    op.drop_table("pedido")
    op.execute("DROP INDEX IF EXISTS uq_combo_regla_par")
    op.drop_table("combo_regla")
    op.drop_index("ix_promocion_codigo", table_name="promocion")
    op.drop_table("promocion")
    op.drop_index("ix_producto_categoria_producto_id", table_name="producto_categoria")
    op.drop_index("ix_producto_categoria_categoria_id", table_name="producto_categoria")
    op.drop_table("producto_categoria")
    op.drop_index("ix_producto_nombre", table_name="producto")
    op.drop_index("ix_producto_codigo", table_name="producto")
    op.drop_table("producto")
    op.drop_table("zona_envio")
    op.drop_index("ix_usuario_username", table_name="usuario")
    op.drop_table("usuario")
    op.execute("DROP INDEX IF EXISTS uq_motivo_gasto_nombre_lower")
    op.drop_index("ix_motivo_gasto_nombre", table_name="motivo_gasto")
    op.drop_table("motivo_gasto")
    op.execute("DROP INDEX IF EXISTS uq_marca_nombre_lower")
    op.drop_index("ix_marca_nombre", table_name="marca")
    op.drop_table("marca")
    op.drop_index("ix_cliente_telefono", table_name="cliente")
    op.drop_table("cliente")
    op.drop_index("ix_categoria_codigo", table_name="categoria")
    op.drop_table("categoria")

    op.execute("DROP SEQUENCE IF EXISTS gasto_codigo_seq")
    op.execute("DROP SEQUENCE IF EXISTS pedido_codigo_seq")

    tipo_promocion.drop(op.get_bind(), checkfirst=True)
    regla_precio_combo.drop(op.get_bind(), checkfirst=True)
    unidad_venta.drop(op.get_bind(), checkfirst=True)
    forma_pago.drop(op.get_bind(), checkfirst=True)
    estado_pedido.drop(op.get_bind(), checkfirst=True)
    rol_usuario.drop(op.get_bind(), checkfirst=True)
