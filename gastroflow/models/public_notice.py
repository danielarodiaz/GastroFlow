"""Public notices use Argentina local time, with an exclusive end instant."""

from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime
from sqlmodel import Field, SQLModel

from gastroflow.models.base import IdMixin


class AvisoPublico(IdMixin, SQLModel, table=True):
    __tablename__ = "aviso_publico"
    __table_args__ = (
        CheckConstraint("tipo IN ('informativo', 'oferta')", name="ck_aviso_tipo"),
        CheckConstraint("accion IN ('ninguna', 'suspender_envios')", name="ck_aviso_accion"),
        CheckConstraint("fin IS NULL OR fin > inicio", name="ck_aviso_vigencia"),
        CheckConstraint("accion = 'ninguna' OR tipo = 'informativo'", name="ck_aviso_accion_tipo"),
    )

    titulo: str = Field(max_length=160)
    mensaje: str = Field(max_length=4000)
    mensaje_html: str | None = Field(default=None, max_length=20000)
    tipo: str = Field(default="informativo", max_length=20)
    accion: str = Field(default="ninguna", max_length=30)
    habilitado: bool = True
    prioridad: int = 0
    inicio: datetime = Field(sa_column=Column(DateTime(timezone=False), nullable=False))
    fin: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=False), nullable=True))
