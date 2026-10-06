from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Column, Enum as SAEnum, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from gastroflow.domain.enums import ReglaPrecioCombo, TipoPromocion, UnidadVenta
from gastroflow.models.base import IdMixin, money_column


class CategoriaBase(SQLModel):
    codigo: str = Field(index=True, unique=True, max_length=50)
    nombre: str = Field(max_length=120)
    descripcion_publica: Optional[str] = Field(default=None)
    foto_url: Optional[str] = Field(default=None, max_length=500)
    orden: int = Field(default=0)
    visible_cliente: bool = Field(default=True, sa_column=Column(Boolean, nullable=False))
    es_automatica: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    cantidad_minima_total: Optional[int] = Field(default=None)
    prioridad: int = Field(default=0)
    acumulable: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    activa: bool = Field(default=True, sa_column=Column(Boolean, nullable=False))


class Categoria(CategoriaBase, IdMixin, table=True):
    __tablename__ = "categoria"


class CategoriaCreate(CategoriaBase):
    pass


class CategoriaRead(CategoriaBase):
    id: int


class ProductoBase(SQLModel):
    codigo: str = Field(index=True, unique=True, max_length=50)
    nombre: str = Field(index=True, max_length=140)
    descripcion: Optional[str] = Field(default=None)
    fotos: Optional[list[str]] = Field(default=None, sa_column=Column(JSONB, nullable=True))
    unidad_venta: UnidadVenta = Field(
        sa_column=Column(SAEnum(UnidadVenta, name="unidad_venta"), nullable=False)
    )
    activo: bool = Field(default=True, sa_column=Column(Boolean, nullable=False))


class Producto(ProductoBase, IdMixin, table=True):
    __tablename__ = "producto"


class ProductoCreate(ProductoBase):
    pass


class ProductoRead(ProductoBase):
    id: int


class ProductoCategoriaBase(SQLModel):
    producto_id: int = Field(foreign_key="producto.id", index=True)
    categoria_id: int = Field(foreign_key="categoria.id", index=True)
    precio: Decimal = Field(sa_column=money_column())
    descripcion_publica: Optional[str] = Field(default=None)
    foto_url: Optional[str] = Field(default=None, max_length=500)
    visible: bool = Field(default=True, sa_column=Column(Boolean, nullable=False))
    orden: int = Field(default=0)
    destacado: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    activo: bool = Field(default=True, sa_column=Column(Boolean, nullable=False))


class ProductoCategoria(ProductoCategoriaBase, IdMixin, table=True):
    __tablename__ = "producto_categoria"
    __table_args__ = (
        UniqueConstraint("producto_id", "categoria_id", name="uq_producto_categoria"),
    )


class ProductoCategoriaCreate(ProductoCategoriaBase):
    pass


class ProductoCategoriaRead(ProductoCategoriaBase):
    id: int


class PromocionBase(SQLModel):
    codigo: str = Field(index=True, unique=True, max_length=80)
    nombre: str = Field(max_length=140)
    tipo: TipoPromocion = Field(
        sa_column=Column(SAEnum(TipoPromocion, name="tipo_promocion"), nullable=False)
    )
    cantidad_minima: int = Field(gt=0)
    precio_unitario_promocional: Decimal = Field(sa_column=money_column())
    precio_total_promocional: Optional[Decimal] = Field(default=None, sa_column=money_column(nullable=True))
    activa: bool = Field(default=True, sa_column=Column(Boolean, nullable=False))
    vigencia_desde: Optional[datetime] = None
    vigencia_hasta: Optional[datetime] = None


class Promocion(PromocionBase, IdMixin, table=True):
    __tablename__ = "promocion"


class PromocionCreate(PromocionBase):
    pass


class PromocionRead(PromocionBase):
    id: int


class PromocionProductoBase(SQLModel):
    promocion_id: int = Field(foreign_key="promocion.id")
    producto_id: int = Field(foreign_key="producto.id")


class PromocionProducto(PromocionProductoBase, IdMixin, table=True):
    __tablename__ = "promocion_producto"
    __table_args__ = (UniqueConstraint("promocion_id", "producto_id"),)


class PromocionProductoCreate(PromocionProductoBase):
    pass


class PromocionProductoRead(PromocionProductoBase):
    id: int


class ComboReglaBase(SQLModel):
    producto_a_id: int = Field(foreign_key="producto.id")
    producto_b_id: int = Field(foreign_key="producto.id")
    requiere_confirmacion: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    regla_precio: ReglaPrecioCombo = Field(
        sa_column=Column(SAEnum(ReglaPrecioCombo, name="regla_precio_combo"), nullable=False)
    )
    precio_fijo_combo: Optional[Decimal] = Field(default=None, sa_column=money_column(nullable=True))


class ComboRegla(ComboReglaBase, IdMixin, table=True):
    __tablename__ = "combo_regla"


class ComboReglaCreate(ComboReglaBase):
    pass


class ComboReglaRead(ComboReglaBase):
    id: int


class ZonaEnvioBase(SQLModel):
    nombre: str = Field(max_length=140)
    costo: Decimal = Field(sa_column=money_column())


class ZonaEnvio(ZonaEnvioBase, IdMixin, table=True):
    __tablename__ = "zona_envio"


class ZonaEnvioCreate(ZonaEnvioBase):
    pass


class ZonaEnvioRead(ZonaEnvioBase):
    id: int


class MotivoGastoBase(SQLModel):
    nombre: str = Field(index=True, unique=True, max_length=140)


class MotivoGasto(MotivoGastoBase, IdMixin, table=True):
    __tablename__ = "motivo_gasto"


class MotivoGastoCreate(MotivoGastoBase):
    pass


class MotivoGastoRead(MotivoGastoBase):
    id: int


class MarcaBase(SQLModel):
    nombre: str = Field(index=True, unique=True, max_length=140)


class Marca(MarcaBase, IdMixin, table=True):
    __tablename__ = "marca"


class MarcaCreate(MarcaBase):
    pass


class MarcaRead(MarcaBase):
    id: int


class AppConfigBase(SQLModel):
    key: str = Field(index=True, unique=True, max_length=120)
    value: Optional[str] = Field(default=None)


class AppConfig(AppConfigBase, IdMixin, table=True):
    __tablename__ = "app_config"


class AppConfigCreate(AppConfigBase):
    pass


class AppConfigRead(AppConfigBase):
    id: int
