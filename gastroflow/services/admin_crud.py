from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from sqlmodel import Session, SQLModel, select

from gastroflow.domain.errors import ValidationError
from gastroflow.models import (
    Agregado,
    AgregadoCategoria,
    Categoria,
    Cliente,
    ComboRegla,
    Gasto,
    GastoDetalle,
    Marca,
    MotivoGasto,
    Pedido,
    PedidoItem,
    PedidoItemAgregado,
    PedidoPago,
    Producto,
    ProductoCategoria,
    Promocion,
    PromocionCategoria,
    PromocionItem,
    PromocionProducto,
    Usuario,
    UsuarioRead,
    ZonaEnvio,
)
from gastroflow.security import hash_password
from gastroflow.services.auth import AuthService
from gastroflow.services.orders import normalize_phone


@dataclass(frozen=True)
class TableConfig:
    model: type[SQLModel]
    sensitive_fields: frozenset[str] = frozenset()
    password_enabled: bool = False


CRUD_TABLES: dict[str, TableConfig] = {
    "agregado": TableConfig(Agregado),
    "agregado_categoria": TableConfig(AgregadoCategoria),
    "categoria": TableConfig(Categoria),
    "producto": TableConfig(Producto),
    "producto_categoria": TableConfig(ProductoCategoria),
    "promocion": TableConfig(Promocion),
    "promocion_producto": TableConfig(PromocionProducto),
    "promocion_categoria": TableConfig(PromocionCategoria),
    "promocion_item": TableConfig(PromocionItem),
    "combo_regla": TableConfig(ComboRegla),
    "zona_envio": TableConfig(ZonaEnvio),
    "motivo_gasto": TableConfig(MotivoGasto),
    "marca": TableConfig(Marca),
    "usuario": TableConfig(Usuario, frozenset({"password_hash"}), password_enabled=True),
    "cliente": TableConfig(Cliente),
    "pedido": TableConfig(Pedido),
    "pedido_item": TableConfig(PedidoItem),
    "pedido_item_agregado": TableConfig(PedidoItemAgregado),
    "pedido_pago": TableConfig(PedidoPago),
    "gasto": TableConfig(Gasto),
    "gasto_detalle": TableConfig(GastoDetalle),
}


class AdminCrudService:
    def __init__(self, session: Session):
        self.session = session

    def list_records(self, table_name: str, current_user: UsuarioRead) -> list[dict[str, Any]]:
        AuthService(self.session).require_admin(current_user)
        config = self._config(table_name)
        records = self.session.exec(select(config.model)).all()
        return [self._serialize(record, config) for record in records]

    def get_record(self, table_name: str, record_id: int, current_user: UsuarioRead) -> dict[str, Any]:
        AuthService(self.session).require_admin(current_user)
        config = self._config(table_name)
        record = self._get_existing(config, record_id)
        return self._serialize(record, config)

    def create_record(
        self,
        table_name: str,
        data: dict[str, Any],
        current_user: UsuarioRead,
    ) -> dict[str, Any]:
        AuthService(self.session).require_admin(current_user)
        config = self._config(table_name)
        payload = self._prepare_payload(config, data, is_create=True)
        record = config.model(**payload)
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._serialize(record, config)

    def update_record(
        self,
        table_name: str,
        record_id: int,
        data: dict[str, Any],
        current_user: UsuarioRead,
    ) -> dict[str, Any]:
        AuthService(self.session).require_admin(current_user)
        config = self._config(table_name)
        record = self._get_existing(config, record_id)
        payload = self._prepare_payload(config, data, is_create=False)
        for key, value in payload.items():
            if key == "id":
                continue
            setattr(record, key, value)
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._serialize(record, config)

    def delete_record(self, table_name: str, record_id: int, current_user: UsuarioRead) -> None:
        AuthService(self.session).require_admin(current_user)
        config = self._config(table_name)
        record = self._get_existing(config, record_id)
        if table_name == "pedido":
            # A hard delete is deliberately exceptional. Remove dependent
            # snapshots first, while the business-code sequence remains
            # untouched so the deleted number can never be reused.
            items = self.session.exec(
                select(PedidoItem).where(PedidoItem.pedido_id == record_id)
            ).all()
            item_ids = [item.id for item in items if item.id is not None]
            if item_ids:
                for addon in self.session.exec(
                    select(PedidoItemAgregado).where(
                        PedidoItemAgregado.pedido_item_id.in_(item_ids)
                    )
                ).all():
                    self.session.delete(addon)
            for payment in self.session.exec(
                select(PedidoPago).where(PedidoPago.pedido_id == record_id)
            ).all():
                self.session.delete(payment)
            for item in items:
                self.session.delete(item)
        self.session.delete(record)
        self.session.commit()

    def _config(self, table_name: str) -> TableConfig:
        try:
            return CRUD_TABLES[table_name]
        except KeyError as exc:
            raise ValidationError(f"Tabla no habilitada para CRUD: {table_name}.") from exc

    def _get_existing(self, config: TableConfig, record_id: int) -> SQLModel:
        record = self.session.get(config.model, record_id)
        if record is None:
            raise ValidationError("Registro inexistente.")
        return record

    def _prepare_payload(
        self,
        config: TableConfig,
        data: dict[str, Any],
        *,
        is_create: bool,
    ) -> dict[str, Any]:
        payload = dict(data)
        for field in config.sensitive_fields:
            payload.pop(field, None)

        if config.password_enabled:
            password = payload.pop("password", None)
            if password:
                payload["password_hash"] = hash_password(str(password))
            elif is_create:
                raise ValidationError("La password es obligatoria para crear un usuario.")

        table_name = getattr(config.model, "__tablename__", "")
        for field in ("codigo", "username"):
            if field in payload and isinstance(payload[field], str):
                payload[field] = " ".join(payload[field].strip().split()).upper()
        if table_name == "cliente" and "telefono" in payload:
            payload["telefono"] = normalize_phone(str(payload["telefono"]))
        for key, value in payload.items():
            if isinstance(value, str) and key not in {"password_hash"}:
                payload[key] = " ".join(value.strip().split())

        return payload

    def _serialize(self, record: SQLModel, config: TableConfig) -> dict[str, Any]:
        raw = record.model_dump()
        for field in config.sensitive_fields:
            raw.pop(field, None)
        return {key: self._serialize_value(value) for key, value in raw.items()}

    def _serialize_value(self, value: Any) -> Any:
        if isinstance(value, Enum):
            return value.value
        return value
