from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlmodel import Session, select

from gastroflow.domain.errors import ValidationError
from gastroflow.models import Gasto, GastoDetalle, GastoRead, Marca, MotivoGasto, UsuarioRead
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
    descripcion: str | None = None
    lugar_lat: Decimal | None = None
    lugar_lng: Decimal | None = None


@dataclass(frozen=True)
class ExpenseDetailInput:
    motivo_nombre: str
    marca_nombre: str
    cantidad: Decimal
    unidad_medida: str
    precio_unitario: Decimal
    descripcion: str | None = None


@dataclass(frozen=True)
class ExpenseTicketInput:
    fecha: date
    lugar_texto: str
    items: list[ExpenseDetailInput]
    lugar_lat: Decimal | None = None
    lugar_lng: Decimal | None = None
    observaciones: str | None = None


class ExpenseService:
    def __init__(self, session: Session):
        self.session = session

    def create_expense(self, data: ExpenseInput, current_user: UsuarioRead) -> GastoRead:
        ticket = ExpenseTicketInput(
            fecha=data.fecha,
            lugar_texto=data.lugar_texto,
            lugar_lat=data.lugar_lat,
            lugar_lng=data.lugar_lng,
            items=[
                ExpenseDetailInput(
                    motivo_nombre=data.motivo_nombre,
                    marca_nombre=data.marca_nombre,
                    cantidad=data.cantidad,
                    unidad_medida=data.unidad_medida,
                    precio_unitario=data.precio,
                    descripcion=data.descripcion,
                )
            ],
        )
        return self.create_expense_ticket(ticket, current_user)

    def create_expense_ticket(self, data: ExpenseTicketInput, current_user: UsuarioRead) -> GastoRead:
        AuthService(self.session).require_owner_or_admin(current_user)
        self._validate(data)

        detail_rows: list[tuple[ExpenseDetailInput, MotivoGasto, Marca, Decimal]] = []
        total = Decimal("0.00")
        for item in data.items:
            motivo = self._get_or_create_motivo(item.motivo_nombre)
            marca = self._get_or_create_marca(item.marca_nombre)
            subtotal = self._line_subtotal(item)
            total += subtotal
            detail_rows.append((item, motivo, marca, subtotal))

        gasto = Gasto(
            codigo=next_business_code(self.session, "gasto_codigo_seq", "GAS"),
            fecha=data.fecha,
            lugar_texto=normalize_catalog_name(data.lugar_texto),
            lugar_lat=data.lugar_lat,
            lugar_lng=data.lugar_lng,
            observaciones=data.observaciones.strip() if data.observaciones else None,
            monto_total=self._money(total),
        )
        self.session.add(gasto)
        self.session.flush()
        for item, motivo, marca, subtotal in detail_rows:
            self.session.add(
                GastoDetalle(
                    gasto_id=gasto.id or 0,
                    motivo_gasto_id=motivo.id or 0,
                    marca_id=marca.id or 0,
                    descripcion=normalize_optional_text(item.descripcion),
                    cantidad=self._quantity(item.cantidad),
                    unidad_medida=normalize_catalog_name(item.unidad_medida),
                    precio_unitario=self._money(item.precio_unitario),
                    subtotal=subtotal,
                )
            )
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

    def _validate(self, data: ExpenseTicketInput) -> None:
        if not data.lugar_texto.strip():
            raise ValidationError("El lugar del gasto es obligatorio.")
        if not data.items:
            raise ValidationError("El gasto debe tener al menos un item.")
        for item in data.items:
            self._validate_detail(item)

    def _validate_detail(self, item: ExpenseDetailInput) -> None:
        if not item.motivo_nombre.strip():
            raise ValidationError("El motivo del gasto es obligatorio.")
        if not item.marca_nombre.strip():
            raise ValidationError("La marca del gasto es obligatoria.")
        if item.cantidad <= 0:
            raise ValidationError("La cantidad del gasto debe ser mayor a cero.")
        if not item.unidad_medida.strip():
            raise ValidationError("La unidad de medida es obligatoria.")
        if item.precio_unitario < 0:
            raise ValidationError("El precio del gasto no puede ser negativo.")

    def _line_subtotal(self, item: ExpenseDetailInput) -> Decimal:
        return self._money(self._quantity(item.cantidad) * self._money(item.precio_unitario))

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
            lugar_texto=gasto.lugar_texto,
            lugar_lat=gasto.lugar_lat,
            lugar_lng=gasto.lugar_lng,
            observaciones=gasto.observaciones,
            monto_total=gasto.monto_total,
            created_at=gasto.created_at,
            updated_at=gasto.updated_at,
        )


def normalize_catalog_name(value: str) -> str:
    return " ".join(value.strip().split()).upper()


def normalize_optional_text(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    return normalize_catalog_name(value)
