from enum import Enum


class RolUsuario(str, Enum):
    ADMIN = "admin"
    DUENO = "dueno"


class EstadoPedido(str, Enum):
    PEDIDO = "pedido"
    PENDIENTE_CONFIRMACION = "pendiente_confirmacion"
    EN_PROCESO = "en_proceso"
    ENTREGADO = "entregado"
    CANCELADO = "cancelado"


class FormaPago(str, Enum):
    TRANSFERENCIA = "transferencia"
    EFECTIVO = "efectivo"


class UnidadVenta(str, Enum):
    PIEZA = "pieza"
    UNIDAD = "unidad"
    DOCENA = "docena"


class ReglaPrecioCombo(str, Enum):
    MAYOR_VALOR = "mayor_valor"
    PROMEDIO = "promedio"
    PRECIO_FIJO = "precio_fijo"


class TipoPromocion(str, Enum):
    PRECIO_UNITARIO_POR_CANTIDAD = "precio_unitario_por_cantidad"
