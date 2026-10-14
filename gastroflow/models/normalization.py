"""Normalize identifiers at persistence while preserving display text."""

from sqlalchemy import event
from sqlalchemy.orm import Session


UPPERCASE_FIELDS = {
    "categoria": ("codigo",),
    "producto": ("codigo",),
    "promocion": ("codigo",),
    "usuario": ("username",),
    "pedido": ("codigo",),
    "gasto": ("codigo",),
}


@event.listens_for(Session, "before_flush")
def uppercase_identifiers(session, flush_context, instances):
    for record in session.new.union(session.dirty):
        for field in UPPERCASE_FIELDS.get(getattr(record, "__tablename__", ""), ()):
            value = getattr(record, field, None)
            if isinstance(value, str):
                setattr(record, field, value.upper())
