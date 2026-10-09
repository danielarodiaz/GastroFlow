from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Column, Enum as SAEnum, String
from sqlmodel import Field, SQLModel

from gastroflow.domain.enums import EstadoPedido, FormaPago, RolUsuario
from gastroflow.models.base import IdMixin, coordinate_column, money_column, quantity_column, timestamp_field


class UsuarioBase(SQLModel):
    username: str = Field(index=True, unique=True, max_length=80)
    rol: RolUsuario = Field(sa_column=Column(SAEnum(RolUsuario, name="rol_usuario"), nullable=False))


class Usuario(UsuarioBase, IdMixin, table=True):
    __tablename__ = "usuario"

    created_at: datetime = timestamp_field()
    updated_at: datetime = timestamp_field()
    password_hash: str = Field(max_length=255)


class UsuarioCreate(UsuarioBase):
    password: str = Field(min_length=8, max_length=128)


class UsuarioRead(UsuarioBase):
    id: int
    created_at: datetime
    updated_at: datetime


class ClienteBase(SQLModel):
    nombre_apellido: str = Field(max_length=160)
    telefono: str = Field(index=True, unique=True, max_length=40)


class Cliente(ClienteBase, IdMixin, table=True):
    __tablename__ = "cliente"

    created_at: datetime = timestamp_field()
    updated_at: datetime = timestamp_field()


class ClienteCreate(ClienteBase):
    pass


class ClienteRead(ClienteBase):
    id: int
    created_at: datetime
    updated_at: datetime


class PedidoBase(SQLModel):
    codigo: str = Field(index=True, unique=True, max_length=30)
    fecha_entrega: date
    cliente_id: int = Field(foreign_key="cliente.id")
    direccion_delivery: str
    direccion_lat: Optional[Decimal] = Field(default=None, sa_column=coordinate_column())
    direccion_lng: Optional[Decimal] = Field(default=None, sa_column=coordinate_column())
    zona_envio_id: Optional[int] = Field(default=None, foreign_key="zona_envio.id")
    costo_envio: Decimal = Field(sa_column=money_column())
    forma_pago: FormaPago = Field(
        sa_column=Column(SAEnum(FormaPago, name="forma_pago"), nullable=False)
    )
    estado: EstadoPedido = Field(
        sa_column=Column(SAEnum(EstadoPedido, name="estado_pedido"), nullable=False)
    )
    observaciones: Optional[str] = None
    monto_total: Decimal = Field(sa_column=money_column())


class Pedido(PedidoBase, IdMixin, table=True):
    __tablename__ = "pedido"

    created_at: datetime = timestamp_field()
    updated_at: datetime = timestamp_field()


class PedidoCreate(PedidoBase):
    pass


class PedidoRead(PedidoBase):
    id: int
    created_at: datetime
    updated_at: datetime


class PedidoItemBase(SQLModel):
    pedido_id: int = Field(foreign_key="pedido.id", index=True)
    producto_id: int = Field(foreign_key="producto.id")
    producto_combo_id: Optional[int] = Field(default=None, foreign_key="producto.id")
    categoria_venta_id: int = Field(foreign_key="categoria.id")
    cantidad: int = Field(gt=0)
    precio_unitario: Decimal = Field(sa_column=money_column())
    subtotal: Decimal = Field(sa_column=money_column())


class PedidoItem(PedidoItemBase, IdMixin, table=True):
    __tablename__ = "pedido_item"


class PedidoItemCreate(PedidoItemBase):
    pass


class PedidoItemRead(PedidoItemBase):
    id: int


class GastoBase(SQLModel):
    codigo: str = Field(index=True, unique=True, max_length=30)
    fecha: date
    lugar_texto: str
    lugar_lat: Optional[Decimal] = Field(default=None, sa_column=coordinate_column())
    lugar_lng: Optional[Decimal] = Field(default=None, sa_column=coordinate_column())
    observaciones: Optional[str] = None
    monto_total: Decimal = Field(sa_column=money_column())


class Gasto(GastoBase, IdMixin, table=True):
    __tablename__ = "gasto"

    created_at: datetime = timestamp_field()
    updated_at: datetime = timestamp_field()


class GastoCreate(GastoBase):
    pass


class GastoRead(GastoBase):
    id: int
    created_at: datetime
    updated_at: datetime


class GastoDetalleBase(SQLModel):
    gasto_id: int = Field(foreign_key="gasto.id", index=True)
    motivo_gasto_id: int = Field(foreign_key="motivo_gasto.id")
    marca_id: int = Field(foreign_key="marca.id")
    descripcion: Optional[str] = None
    cantidad: Decimal = Field(sa_column=quantity_column())
    unidad_medida: str = Field(max_length=40)
    precio_unitario: Decimal = Field(sa_column=money_column())
    subtotal: Decimal = Field(sa_column=money_column())


class GastoDetalle(GastoDetalleBase, IdMixin, table=True):
    __tablename__ = "gasto_detalle"


class GastoDetalleCreate(GastoDetalleBase):
    pass


class GastoDetalleRead(GastoDetalleBase):
    id: int
