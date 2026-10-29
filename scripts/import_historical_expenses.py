from __future__ import annotations

import argparse
import hashlib
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, text
from sqlmodel import Session, select

from gastroflow.data.database import engine
from gastroflow.domain.enums import RolUsuario
from gastroflow.models import Gasto, GastoDetalle, Usuario, UsuarioRead
from gastroflow.services.expenses import (
    ExpenseDetailInput,
    ExpenseService,
    ExpenseTicketInput,
)
from scripts.prepare_historical_expenses import (
    EXPECTED_SOURCE_ROWS,
    EXPECTED_TICKET_GROUPS,
    EXPECTED_TOTAL,
    PreparedExpenseRow,
    load_and_prepare,
)


EXPECTED_ALEMBIC_REVISION = "0014_optional_expense_brand"
IMPORT_MARKER_PREFIX = "GASTOS-HISTORICOS-SHA256:"


def _description(row: PreparedExpenseRow) -> str | None:
    parts: list[str] = []
    if row.quantity_original:
        parts.append(f"Cantidad fuente: {row.quantity_original}")
    if row.presentation and row.presentation != row.quantity_original:
        parts.append(f"Presentación: {row.presentation}")
    if row.note:
        parts.append(row.note)
    return " | ".join(parts) or None


def build_ticket_inputs(
    rows: list[PreparedExpenseRow], *, source_hash: str
) -> list[ExpenseTicketInput]:
    grouped: dict[str, list[PreparedExpenseRow]] = defaultdict(list)
    for row in rows:
        grouped[row.ticket_group].append(row)

    tickets: list[ExpenseTicketInput] = []
    for ticket_group, group in grouped.items():
        first = group[0]
        source_rows = ",".join(str(row.excel_row) for row in group)
        tickets.append(
            ExpenseTicketInput(
                fecha=first.expense_date,
                lugar_texto=first.place_normalized,
                observaciones=(
                    f"{IMPORT_MARKER_PREFIX}{source_hash} | "
                    f"grupo={ticket_group} | filas={source_rows}"
                ),
                items=[
                    ExpenseDetailInput(
                        motivo_nombre=row.motive_normalized,
                        marca_nombre=row.brand_normalized,
                        cantidad=row.quantity,
                        unidad_medida=row.unit,
                        precio_unitario=row.unit_price,
                        subtotal=row.line_total,
                        descripcion=_description(row),
                    )
                    for row in group
                ],
            )
        )
    return tickets


def _as_user_read(user: Usuario) -> UsuarioRead:
    return UsuarioRead(
        id=user.id or 0,
        username=user.username,
        rol=user.rol,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def _select_operator(session: Session, username: str | None) -> Usuario | None:
    statement = select(Usuario).where(
        Usuario.rol.in_([RolUsuario.ADMIN, RolUsuario.DUENO])  # type: ignore[union-attr]
    )
    if username:
        statement = statement.where(func.upper(Usuario.username) == username.strip().upper())
    return session.exec(statement.order_by(Usuario.id)).first()


def _validate_source(rows: list[PreparedExpenseRow], tickets: list[ExpenseTicketInput]) -> None:
    review_rows = [row.excel_row for row in rows if row.status != "LISTO"]
    if review_rows:
        raise RuntimeError(f"Quedan filas pendientes de revisión: {review_rows}")
    if len(rows) != EXPECTED_SOURCE_ROWS:
        raise RuntimeError(f"Cantidad de ítems inesperada: {len(rows)}")
    if len(tickets) != EXPECTED_TICKET_GROUPS:
        raise RuntimeError(f"Cantidad de tickets inesperada: {len(tickets)}")
    total = sum(
        (item.subtotal or Decimal("0.00") for ticket in tickets for item in ticket.items),
        Decimal("0.00"),
    )
    if total != EXPECTED_TOTAL:
        raise RuntimeError(f"Total inesperado: {total}; esperado: {EXPECTED_TOTAL}")
    validator = ExpenseService(session=None)  # type: ignore[arg-type]
    for ticket in tickets:
        validator._validate(ticket)


def import_expenses(path: Path, *, apply: bool, username: str | None = None) -> dict[str, object]:
    source = path.resolve()
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    rows, _ = load_and_prepare(source)
    tickets = build_ticket_inputs(rows, source_hash=source_hash)
    _validate_source(rows, tickets)
    marker = f"{IMPORT_MARKER_PREFIX}{source_hash}"

    print(
        f"Fuente validada: {len(rows)} ítems, {len(tickets)} tickets, "
        f"total ${EXPECTED_TOTAL}, SHA256 {source_hash}",
        flush=True,
    )

    with Session(engine) as session:
        revision = session.exec(text("SELECT version_num FROM alembic_version")).one()[0]
        if revision != EXPECTED_ALEMBIC_REVISION:
            raise RuntimeError(
                f"Revisión Alembic inesperada: {revision}. "
                f"Se requiere {EXPECTED_ALEMBIC_REVISION}."
            )

        already_imported = session.exec(
            select(func.count()).select_from(Gasto).where(Gasto.observaciones.contains(marker))
        ).one()
        if already_imported:
            raise RuntimeError("Esta fuente ya fue importada total o parcialmente.")

        first_date = min(row.expense_date for row in rows)
        last_date = max(row.expense_date for row in rows)
        overlapping = session.exec(
            select(func.count()).select_from(Gasto).where(
                Gasto.fecha >= first_date,
                Gasto.fecha <= last_date,
            )
        ).one()
        if overlapping:
            raise RuntimeError(
                f"Hay {overlapping} gastos existentes entre {first_date} y {last_date}; "
                "se aborta para evitar duplicados."
            )

        operator = _select_operator(session, username)
        if operator is None:
            requested = f" con username {username!r}" if username else ""
            raise RuntimeError(f"No existe un usuario admin/dueño{requested} para auditar la carga.")

        print(
            f"Base validada en revisión {revision}; operador {operator.username}; "
            "sin solapamientos ni importaciones previas.",
            flush=True,
        )

        if not apply:
            print("ENSAYO OK: no se insertó ni modificó ningún dato.", flush=True)
            return {
                "mode": "dry-run",
                "tickets": len(tickets),
                "items": len(rows),
                "total": EXPECTED_TOTAL,
                "source_hash": source_hash,
            }

        service = ExpenseService(session)
        current_user = _as_user_read(operator)
        created_ids: list[int] = []
        try:
            for ticket in tickets:
                created = service.create_expense_ticket(ticket, current_user, commit=False)
                created_ids.append(created.id)

            inserted_items = session.exec(
                select(func.count()).select_from(GastoDetalle).where(
                    GastoDetalle.gasto_id.in_(created_ids)  # type: ignore[union-attr]
                )
            ).one()
            inserted_total = session.exec(
                select(func.coalesce(func.sum(Gasto.monto_total), 0)).where(Gasto.id.in_(created_ids))  # type: ignore[union-attr]
            ).one()
            if len(created_ids) != EXPECTED_TICKET_GROUPS:
                raise RuntimeError("No se generó la cantidad esperada de tickets.")
            if inserted_items != EXPECTED_SOURCE_ROWS:
                raise RuntimeError("No se generó la cantidad esperada de ítems.")
            if Decimal(inserted_total).quantize(Decimal("0.01")) != EXPECTED_TOTAL:
                raise RuntimeError("El total insertado no coincide con el total de control.")
            session.commit()
        except Exception:
            session.rollback()
            raise

    print(
        f"IMPORTACIÓN COMPLETA: {len(tickets)} tickets, {len(rows)} ítems, ${EXPECTED_TOTAL}.",
        flush=True,
    )
    return {
        "mode": "apply",
        "tickets": len(tickets),
        "items": len(rows),
        "total": EXPECTED_TOTAL,
        "source_hash": source_hash,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ensaya o ejecuta la importación transaccional de gastos históricos."
    )
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--username")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Confirma la escritura. Sin esta opción se ejecuta un ensayo sin cambios.",
    )
    args = parser.parse_args()
    import_expenses(args.file, apply=args.apply, username=args.username)


if __name__ == "__main__":
    main()
