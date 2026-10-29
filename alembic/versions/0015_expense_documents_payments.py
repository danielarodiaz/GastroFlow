"""Add expense evidence documents and payment destination metadata."""

from alembic import op
import sqlalchemy as sa


revision = "0015_expense_documents_payments"
down_revision = "0014_optional_expense_brand"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gasto", sa.Column("medio_pago", sa.String(length=40), nullable=True))
    op.add_column("gasto", sa.Column("destinatario_pago", sa.String(length=160), nullable=True))
    op.add_column("gasto", sa.Column("identificador_pago", sa.String(length=120), nullable=True))
    op.create_index("ix_gasto_identificador_pago", "gasto", ["identificador_pago"])
    op.create_table(
        "gasto_documento",
        sa.Column("gasto_id", sa.Integer(), nullable=True),
        sa.Column("nombre_archivo", sa.String(length=255), nullable=False),
        sa.Column("archivo_url", sa.String(length=500), nullable=False),
        sa.Column("contenido_sha256", sa.String(length=64), nullable=False),
        sa.Column("tipo_contenido", sa.String(length=120), nullable=False),
        sa.Column("estado", sa.String(length=30), nullable=False),
        sa.Column("motor_lectura", sa.String(length=50), nullable=True),
        sa.Column("qr_contenido", sa.Text(), nullable=True),
        sa.Column("texto_extraido", sa.Text(), nullable=True),
        sa.Column("datos_extraidos", sa.Text(), nullable=True),
        sa.Column("confianza", sa.Numeric(5, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["gasto_id"], ["gasto.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contenido_sha256"),
    )
    op.create_index("ix_gasto_documento_gasto_id", "gasto_documento", ["gasto_id"])
    op.create_index(
        "ix_gasto_documento_contenido_sha256",
        "gasto_documento",
        ["contenido_sha256"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_gasto_documento_contenido_sha256", table_name="gasto_documento")
    op.drop_index("ix_gasto_documento_gasto_id", table_name="gasto_documento")
    op.drop_table("gasto_documento")
    op.drop_index("ix_gasto_identificador_pago", table_name="gasto")
    op.drop_column("gasto", "identificador_pago")
    op.drop_column("gasto", "destinatario_pago")
    op.drop_column("gasto", "medio_pago")
