"""Scheduled public notices and delivery restrictions."""

from alembic import op
import sqlalchemy as sa

revision = "0017_public_notices"
down_revision = "0016_admin_management"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "aviso_publico",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("titulo", sa.String(160), nullable=False),
        sa.Column("mensaje", sa.String(4000), nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("accion", sa.String(30), nullable=False),
        sa.Column("habilitado", sa.Boolean(), nullable=False),
        sa.Column("prioridad", sa.Integer(), nullable=False),
        sa.Column("inicio", sa.DateTime(), nullable=False),
        sa.Column("fin", sa.DateTime(), nullable=True),
        sa.CheckConstraint("tipo IN ('informativo', 'oferta')", name="ck_aviso_tipo"),
        sa.CheckConstraint("accion IN ('ninguna', 'suspender_envios')", name="ck_aviso_accion"),
        sa.CheckConstraint("fin IS NULL OR fin > inicio", name="ck_aviso_vigencia"),
        sa.CheckConstraint("accion = 'ninguna' OR tipo = 'informativo'", name="ck_aviso_accion_tipo"),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute('ALTER TABLE public.aviso_publico ENABLE ROW LEVEL SECURITY')
        op.execute('REVOKE ALL PRIVILEGES ON TABLE public.aviso_publico FROM anon, authenticated, service_role')
        op.execute('REVOKE ALL PRIVILEGES ON SEQUENCE public.aviso_publico_id_seq FROM anon, authenticated, service_role')


def downgrade():
    op.drop_table("aviso_publico")
