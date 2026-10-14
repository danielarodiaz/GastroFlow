"""Preserve display casing and compare natural keys case-insensitively.

Revision ID: 0007_preserve_display_text
Revises: 0006_public_order_safety
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_preserve_display_text"
down_revision = "0006_public_order_safety"
branch_labels = None
depends_on = None

LEGACY_TABLES = (
    "categoria", "producto", "producto_categoria", "promocion", "zona_envio",
    "motivo_gasto", "marca", "usuario", "cliente", "pedido", "gasto", "gasto_detalle",
)

IDENTIFIER_FIELDS = {
    "categoria": ("codigo",), "producto": ("codigo",), "promocion": ("codigo",),
    "usuario": ("username",), "pedido": ("codigo",), "gasto": ("codigo",),
}

CASE_INSENSITIVE_UNIQUE = {"usuario": "username", "marca": "nombre", "motivo_gasto": "nombre"}


def _canonical_phone(value: str) -> str | None:
    digits = "".join(character for character in value if character.isdigit())
    if digits.startswith("00549"):
        digits = digits[5:]
    elif digits.startswith("0054"):
        digits = digits[4:]
    elif digits.startswith("549"):
        digits = digits[3:]
    elif digits.startswith("54") and len(digits) > 10:
        digits = digits[2:]
    if digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 12:
        positions = [position for position in range(2, 5) if digits[position:position + 2] == "15"]
        if len(positions) == 1:
            position = positions[0]
            digits = digits[:position] + digits[position + 2:]
    return digits if len(digits) == 10 and not digits.startswith("0") else None


def _drop_uppercase_triggers() -> None:
    for table in LEGACY_TABLES:
        op.execute(f'DROP TRIGGER IF EXISTS uppercase_{table}_text ON "{table}"')
        op.execute(f"DROP FUNCTION IF EXISTS uppercase_{table}_text()")


def upgrade() -> None:
    _drop_uppercase_triggers()
    for table, fields in IDENTIFIER_FIELDS.items():
        assignments = " ".join(f'NEW."{field}" := upper(btrim(NEW."{field}"));' for field in fields)
        op.execute(f"""CREATE FUNCTION uppercase_{table}_text() RETURNS trigger AS $$
            BEGIN {assignments} RETURN NEW; END;
            $$ LANGUAGE plpgsql""")
        op.execute(f'''CREATE TRIGGER uppercase_{table}_text BEFORE INSERT OR UPDATE ON "{table}"
            FOR EACH ROW EXECUTE FUNCTION uppercase_{table}_text()''')

    for table, field in CASE_INSENSITIVE_UNIQUE.items():
        collision = op.get_bind().execute(sa.text(
            f'''SELECT 1 FROM "{table}"
                GROUP BY upper(regexp_replace(btrim("{field}"), '\\s+', ' ', 'g'))
                HAVING count(*) > 1 LIMIT 1'''
        )).first()
        if collision:
            raise RuntimeError(f"Resolver duplicados equivalentes en {table}.{field} antes de migrar.")
        op.execute(
            f'''CREATE UNIQUE INDEX uq_{table}_{field}_normalized ON "{table}"
                (upper(regexp_replace(btrim("{field}"), '\\s+', ' ', 'g')))'''
        )

    connection = op.get_bind()
    customers = connection.execute(sa.text("SELECT id, telefono FROM cliente")).mappings().all()
    normalized_owners: dict[str, int] = {}
    phone_updates: list[tuple[int, str]] = []
    for customer in customers:
        normalized = _canonical_phone(str(customer["telefono"] or ""))
        if normalized is None:
            continue  # Keep historical invalid values visible for manual correction.
        previous_id = normalized_owners.get(normalized)
        if previous_id is not None and previous_id != customer["id"]:
            raise RuntimeError(
                f"Los clientes {previous_id} y {customer['id']} tienen el mismo celular normalizado {normalized}. "
                "Unificarlos antes de migrar."
            )
        normalized_owners[normalized] = customer["id"]
        phone_updates.append((customer["id"], normalized))
    for customer_id, normalized in phone_updates:
        connection.execute(
            sa.text("UPDATE cliente SET telefono = :telefono WHERE id = :id"),
            {"telefono": normalized, "id": customer_id},
        )


def downgrade() -> None:
    for table, field in CASE_INSENSITIVE_UNIQUE.items():
        op.execute(f'DROP INDEX IF EXISTS uq_{table}_{field}_normalized')
    _drop_uppercase_triggers()
