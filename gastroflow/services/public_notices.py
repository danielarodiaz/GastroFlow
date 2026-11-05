"""Notice ordering, scheduling and delivery restrictions shared by both apps."""

from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from gastroflow.domain.errors import ValidationError
from gastroflow.models import AvisoPublico
from gastroflow.services.notice_formatting import clean_notice_html


def argentina_now() -> datetime:
    return datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).replace(tzinfo=None)


def notice_rows(session: Session) -> list[dict[str, Any]]:
    return [row.model_dump(mode="json") for row in session.exec(
        select(AvisoPublico).where(AvisoPublico.habilitado == True)
    ).all()]


def in_window(row: dict[str, Any], instant: datetime) -> bool:
    return bool(row.get("habilitado", True)) and datetime.fromisoformat(row["inicio"]) <= instant and (
        not row.get("fin") or instant < datetime.fromisoformat(row["fin"])
    )


def active_notices(rows: list[dict[str, Any]], now: datetime | None = None) -> list[dict[str, Any]]:
    instant = now or argentina_now()
    return sorted((row for row in rows if in_window(row, instant)), key=lambda row: (
        row["tipo"] == "oferta", row["prioridad"], row["id"],
    ))


def delivery_block(rows: list[dict[str, Any]], day: date, hour: time | None = None) -> str:
    # A date without a time checks the entire day (the server requires a time
    # for delivery when any restriction overlaps that date).
    instant = datetime.combine(day, hour or time.min)
    for row in sorted(rows, key=lambda item: (item["prioridad"], item["id"])):
        if row["accion"] != "suspender_envios" or not row.get("habilitado", True):
            continue
        overlaps = in_window(row, instant)
        if hour is None:
            start = datetime.fromisoformat(row["inicio"])
            end = datetime.fromisoformat(row["fin"]) if row.get("fin") else datetime.max
            overlaps = start.date() <= day and end > instant
        if overlaps:
            return f"No hay envíos para la fecha y horario elegidos. {row['mensaje']} Podés retirar en el local."
    return ""


def validate_notice(notice: AvisoPublico) -> None:
    if not notice.titulo.strip() or not notice.mensaje.strip():
        raise ValidationError("Completá el título y el mensaje.")
    if len(notice.titulo) > 160 or len(notice.mensaje) > 4000:
        raise ValidationError("El título admite hasta 160 caracteres y el mensaje hasta 4000.")
    if notice.mensaje_html is not None:
        if len(notice.mensaje_html) > 20000:
            raise ValidationError("El mensaje tiene demasiado formato. Simplificá su contenido.")
        notice.mensaje_html, notice.mensaje = clean_notice_html(notice.mensaje_html)
        if not notice.mensaje.strip():
            raise ValidationError("Completá el mensaje.")
        if len(notice.mensaje) > 4000:
            raise ValidationError("El mensaje admite hasta 4000 caracteres.")
    if notice.tipo not in {"informativo", "oferta"} or notice.accion not in {"ninguna", "suspender_envios"}:
        raise ValidationError("Tipo o acción de aviso inválidos.")
    if notice.accion != "ninguna" and notice.tipo != "informativo":
        raise ValidationError("La suspensión de envíos debe ser un aviso informativo.")
    if notice.fin is not None and notice.fin <= notice.inicio:
        raise ValidationError("El fin debe ser posterior al inicio.")


def assert_delivery_available(session: Session, day: date, hour: time | None) -> None:
    message = delivery_block(notice_rows(session), day, hour)
    if message:
        raise ValidationError(message)
