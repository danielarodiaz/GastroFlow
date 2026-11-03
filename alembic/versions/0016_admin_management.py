"""Add safe admin configuration, user permissions and audit history."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0016_admin_management"
down_revision = "0015_expense_documents_payments"
branch_labels = None
depends_on = None


ALL_PERMISSIONS = (
    '["pedidos", "gastos", "catalogo", "promociones", '
    '"configuracion", "usuarios"]'
)
BASIC_PERMISSIONS = '["pedidos", "gastos"]'


def upgrade() -> None:
    op.add_column(
        "zona_envio",
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "usuario",
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "usuario",
        sa.Column(
            "permisos",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.execute(
        sa.text("UPDATE usuario SET permisos = CAST(:permissions AS jsonb) WHERE rol = 'ADMIN'")
        .bindparams(permissions=ALL_PERMISSIONS)
    )
    op.execute(
        sa.text("UPDATE usuario SET permisos = CAST(:permissions AS jsonb) WHERE rol = 'DUENO'")
        .bindparams(permissions=BASIC_PERMISSIONS)
    )
    op.create_table(
        "cambio_administrativo",
        sa.Column("usuario_id", sa.Integer(), nullable=True),
        sa.Column("usuario_nombre", sa.String(length=80), nullable=False),
        sa.Column("seccion", sa.String(length=60), nullable=False),
        sa.Column("accion", sa.String(length=30), nullable=False),
        sa.Column("registro_id", sa.Integer(), nullable=True),
        sa.Column("resumen", sa.Text(), nullable=False),
        sa.Column("datos_anteriores", sa.Text(), nullable=True),
        sa.Column("datos_nuevos", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuario.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_cambio_administrativo_usuario_id",
        "cambio_administrativo",
        ["usuario_id"],
    )
    op.create_index(
        "ix_cambio_administrativo_seccion",
        "cambio_administrativo",
        ["seccion"],
    )


def downgrade() -> None:
    op.drop_index("ix_cambio_administrativo_seccion", table_name="cambio_administrativo")
    op.drop_index("ix_cambio_administrativo_usuario_id", table_name="cambio_administrativo")
    op.drop_table("cambio_administrativo")
    op.drop_column("usuario", "permisos")
    op.drop_column("usuario", "activo")
    op.drop_column("zona_envio", "activa")
