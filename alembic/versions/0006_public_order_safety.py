"""Idempotent public checkout and normalized technical identifiers."""

from alembic import op
import sqlalchemy as sa

revision = "0006_public_order_safety"
down_revision = "0005_expense_ticket_details"
branch_labels = None
depends_on = None

# Explicit list: passwords, URLs, configuration keys and enum values are technical data.
FIELDS = {
    "categoria": ("codigo",),
    "producto": ("codigo",),
    "promocion": ("codigo",),
    "usuario": ("username",),
    "pedido": ("codigo",),
    "gasto": ("codigo",),
}


def upgrade():
    # Do not silently merge identities if legacy rows differ only in case.
    unique_fields = {
        "categoria": "codigo", "producto": "codigo", "promocion": "codigo",
        "usuario": "username", "cliente": "telefono", "pedido": "codigo",
        "gasto": "codigo", "marca": "nombre", "motivo_gasto": "nombre",
    }
    for table, field in unique_fields.items():
        collision = op.get_bind().execute(sa.text(
            f'SELECT 1 FROM "{table}" GROUP BY upper("{field}") HAVING count(*) > 1 LIMIT 1'
        )).first()
        if collision:
            raise RuntimeError(f"Resolver duplicados que difieren solo en mayúsculas en {table}.{field} antes de migrar.")
    op.add_column("pedido", sa.Column("submission_token", sa.String(36), nullable=True))
    op.create_unique_constraint("uq_pedido_submission_token", "pedido", ["submission_token"])
    for table, fields in FIELDS.items():
        assignments = " ".join(f'NEW."{field}" := upper(NEW."{field}");' for field in fields)
        op.execute(f"""CREATE FUNCTION uppercase_{table}_text() RETURNS trigger AS $$
            BEGIN {assignments} RETURN NEW; END;
            $$ LANGUAGE plpgsql;""")
        op.execute(f'''CREATE TRIGGER uppercase_{table}_text BEFORE INSERT OR UPDATE ON "{table}"
            FOR EACH ROW EXECUTE FUNCTION uppercase_{table}_text()''')
        updates = ", ".join(f'"{field}" = upper("{field}")' for field in fields)
        op.execute(f'UPDATE "{table}" SET {updates}')


def downgrade():
    for table in FIELDS:
        op.execute(f'DROP TRIGGER uppercase_{table}_text ON "{table}"')
        op.execute(f"DROP FUNCTION uppercase_{table}_text()")
    op.drop_constraint("uq_pedido_submission_token", "pedido", type_="unique")
    op.drop_column("pedido", "submission_token")
