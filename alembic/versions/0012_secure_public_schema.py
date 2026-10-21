"""Secure application tables from Supabase Data API access.

Revision ID: 0012_secure_public_schema
Revises: 0011_split_payments_addons
"""

from alembic import op


revision = "0012_secure_public_schema"
down_revision = "0011_split_payments_addons"
branch_labels = None
depends_on = None


APPLICATION_TABLES = (
    "alembic_version",
    "usuario",
    "cliente",
    "pedido",
    "pedido_item",
    "pedido_pago",
    "pedido_item_agregado",
    "gasto",
    "gasto_detalle",
    "categoria",
    "producto",
    "producto_categoria",
    "promocion",
    "promocion_producto",
    "promocion_categoria",
    "promocion_item",
    "combo_regla",
    "zona_envio",
    "agregado",
    "agregado_categoria",
    "marca",
    "motivo_gasto",
    "app_config",
)

DATA_API_ROLES = "anon, authenticated, service_role"


def upgrade():
    # GastroFlow reaches these tables through its server-side PostgreSQL
    # connection. No table is intended to be reachable through PostgREST or
    # GraphQL, so RLS is enabled with no policies (default deny).
    for table_name in APPLICATION_TABLES:
        op.execute(f'ALTER TABLE public."{table_name}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'REVOKE ALL PRIVILEGES ON TABLE public."{table_name}" '
            f"FROM {DATA_API_ROLES}"
        )

    op.execute(
        f"REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public "
        f"FROM {DATA_API_ROLES}"
    )

    # Keep future Alembic-created tables and sequences private by default,
    # including on fresh projects and database resets.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
        f"REVOKE ALL ON TABLES FROM {DATA_API_ROLES}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
        f"REVOKE ALL ON SEQUENCES FROM {DATA_API_ROLES}"
    )


def downgrade():
    # This restores the former Supabase Data API exposure. Use only when an
    # intentional rollback has been reviewed as a security-sensitive change.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {DATA_API_ROLES}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
        f"GRANT USAGE, SELECT ON SEQUENCES TO {DATA_API_ROLES}"
    )
    op.execute(
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public "
        f"TO {DATA_API_ROLES}"
    )

    for table_name in reversed(APPLICATION_TABLES):
        op.execute(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public."{table_name}" '
            f"TO {DATA_API_ROLES}"
        )
        op.execute(f'ALTER TABLE public."{table_name}" DISABLE ROW LEVEL SECURITY')
