"""Normalize business text at the persistence boundary, never in form setters."""

from sqlalchemy import event
from sqlalchemy.orm import Session


UPPERCASE_FIELDS = {
    "categoria": ("codigo", "nombre", "descripcion_publica"),
    "producto": ("codigo", "nombre", "descripcion"),
    "producto_categoria": ("descripcion_publica",),
    "promocion": ("codigo", "nombre"),
    "zona_envio": ("nombre",),
    "motivo_gasto": ("nombre",),
    "marca": ("nombre",),
    "usuario": ("username",),
    "cliente": ("nombre_apellido", "telefono"),
    "pedido": ("codigo", "direccion_delivery", "observaciones"),
    "gasto": ("codigo", "lugar_texto", "observaciones"),
    "gasto_detalle": ("descripcion", "unidad_medida"),
}


@event.listens_for(Session, "before_flush")
def uppercase_business_text(session, flush_context, instances):
    for record in session.new.union(session.dirty):
        for field in UPPERCASE_FIELDS.get(getattr(record, "__tablename__", ""), ()):
            value = getattr(record, field, None)
            if isinstance(value, str):
                setattr(record, field, value.upper())
