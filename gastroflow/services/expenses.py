from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlmodel import Session, select

from gastroflow.domain.errors import ValidationError
from gastroflow.models import Gasto, GastoRead, Marca, MotivoGasto, UsuarioRead
from gastroflow.services.auth import AuthService
from gastroflow.services.codes import next_business_code

MONEY_QUANT = Decimal("0.01")
QUANTITY_QUANT = Decimal("0.001")


@dataclass(frozen=True)
class ExpenseInput:
    fecha: date
    motivo_nombre: str
    marca_nombre: str
    cantidad: Decimal
    unidad_medida: str
    precio: Decimal
    lugar_texto: str
    lugar_lat: Decimal | None = None
    lugar_lng: Decimal | None = None


class ExpenseService:
    def __init__(self, session: Session):
        self.session = session

    def create_expense(self, data: ExpenseInput, current_user: UsuarioRead) -> GastoRead:
        AuthService(self.session).require_owner_or_admin(current_user)
        self._validate(data)

        motivo = self._get_or_create_motivo(data.motivo_nombre)
        marca = self._get_or_create_marca(data.marca_nombre)
        gasto = Gasto(
            codigo=next_business_code(self.session, "gasto_codigo_seq", "GAS"),
            fecha=data.fecha,
            motivo_gasto_id=motivo.id or 0,
            marca_id=marca.id or 0,
            cantidad=self._quantity(data.cantidad),
            unidad_medida=normalize_catalog_name(data.unidad_medida),
            precio=self._money(data.precio),
            lugar_texto=normalize_catalog_name(data.lugar_texto),
            lugar_lat=data.lugar_lat,
            lugar_lng=data.lugar_lng,
        )
        self.session.add(gasto)
        self.session.commit()
        self.session.refresh(gasto)
        return self._to_read(gasto)

    def _get_or_create_motivo(self, nombre: str) -> MotivoGasto:
        normalized = normalize_catalog_name(nombre)
        motivo = self.session.exec(
            select(MotivoGasto).where(func.lower(MotivoGasto.nombre) == normalized.lower())
        ).first()
        if motivo is not None:
            return motivo

        motivo = MotivoGasto(nombre=normalized)
        self.session.add(motivo)
        self.session.flush()
        return motivo

    def _get_or_create_marca(self, nombre: str) -> Marca:
        normalized = normalize_catalog_name(nombre)
        marca = self.session.exec(
            select(Marca).where(func.lower(Marca.nombre) == normalized.lower())
        ).first()
        if marca is not None:
            return marca

        marca = Marca(nombre=normalized)
        self.session.add(marca)
        self.session.flush()
        return marca

    def _validate(self, data: ExpenseInput) -> None:
        if not data.motivo_nombre.strip():
            raise ValidationError("El motivo del gasto es obligatorio.")
        if not data.marca_nombre.strip():
            raise ValidationError("La marca del gasto es obligatoria.")
        if data.cantidad <= 0:
            raise ValidationError("La cantidad del gasto debe ser mayor a cero.")
        if not data.unidad_medida.strip():
            raise ValidationError("La unidad de medida es obligatoria.")
        if data.precio < 0:
            raise ValidationError("El precio del gasto no puede ser negativo.")
        if not data.lugar_texto.strip():
            raise ValidationError("El lugar del gasto es obligatorio.")

    @staticmethod
    def _money(value: Decimal) -> Decimal:
        return Decimal(value).quantize(MONEY_QUANT)

    @staticmethod
    def _quantity(value: Decimal) -> Decimal:
        return Decimal(value).quantize(QUANTITY_QUANT)

    @staticmethod
    def _to_read(gasto: Gasto) -> GastoRead:
        return GastoRead(
            id=gasto.id or 0,
            codigo=gasto.codigo,
            fecha=gasto.fecha,
            motivo_gasto_id=gasto.motivo_gasto_id,
            marca_id=gasto.marca_id,
            cantidad=gasto.cantidad,
            unidad_medida=gasto.unidad_medida,
            precio=gasto.precio,
            lugar_texto=gasto.lugar_texto,
            lugar_lat=gasto.lugar_lat,
            lugar_lng=gasto.lugar_lng,
            created_at=gasto.created_at,
            updated_at=gasto.updated_at,
        )


def normalize_catalog_name(value: str) -> str:
    return " ".join(value.strip().split()).upper()
