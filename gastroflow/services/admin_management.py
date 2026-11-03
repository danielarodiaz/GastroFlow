from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import func
from sqlmodel import Session, select

from gastroflow.domain.enums import PermisoUsuario, RolUsuario
from gastroflow.domain.errors import ConflictError, ValidationError
from gastroflow.models import (
    Agregado,
    AgregadoCategoria,
    CambioAdministrativo,
    Categoria,
    Usuario,
    UsuarioRead,
    ZonaEnvio,
)
from gastroflow.security import hash_password
from gastroflow.services.auth import AuthService


class AdminManagementService:
    def __init__(self, session: Session):
        self.session = session

    def list_zones(self, current_user: UsuarioRead) -> list[ZonaEnvio]:
        self._require_config(current_user)
        return list(self.session.exec(select(ZonaEnvio).order_by(ZonaEnvio.nombre)).all())

    def create_zone(self, name: str, cost: Decimal, current_user: UsuarioRead) -> ZonaEnvio:
        self._require_config(current_user)
        clean_name = self._required_text(name, "El nombre de la zona es obligatorio.")
        self._ensure_unique_name(ZonaEnvio, clean_name)
        zone = ZonaEnvio(nombre=clean_name, costo=self._money(cost), activa=True)
        self.session.add(zone)
        self.session.flush()
        self._audit(current_user, "zonas", "alta", zone.id, f"Zona {clean_name} creada", None, zone)
        self.session.commit()
        self.session.refresh(zone)
        return zone

    def update_zone(self, zone_id: int, name: str, cost: Decimal, current_user: UsuarioRead) -> ZonaEnvio:
        self._require_config(current_user)
        zone = self._get(ZonaEnvio, zone_id, "La zona seleccionada ya no existe.")
        before = self._snapshot(zone)
        clean_name = self._required_text(name, "El nombre de la zona es obligatorio.")
        self._ensure_unique_name(ZonaEnvio, clean_name, excluding_id=zone_id)
        zone.nombre = clean_name
        zone.costo = self._money(cost)
        self.session.add(zone)
        self._audit(current_user, "zonas", "modificacion", zone.id, f"Zona {clean_name} modificada", before, zone)
        self.session.commit()
        self.session.refresh(zone)
        return zone

    def set_zone_active(self, zone_id: int, active: bool, current_user: UsuarioRead) -> ZonaEnvio:
        self._require_config(current_user)
        zone = self._get(ZonaEnvio, zone_id, "La zona seleccionada ya no existe.")
        before = self._snapshot(zone)
        zone.activa = active
        self.session.add(zone)
        action = "reactivacion" if active else "baja"
        self._audit(current_user, "zonas", action, zone.id, f"Zona {zone.nombre} {'reactivada' if active else 'desactivada'}", before, zone)
        self.session.commit()
        self.session.refresh(zone)
        return zone

    def list_categories(self, current_user: UsuarioRead) -> list[Categoria]:
        self._require_config(current_user)
        return list(self.session.exec(select(Categoria).order_by(Categoria.orden, Categoria.nombre)).all())

    def create_category(self, name: str, description: str, current_user: UsuarioRead) -> Categoria:
        self._require_config(current_user)
        clean_name = self._required_text(name, "El nombre de la categoría es obligatorio.")
        self._ensure_unique_name(Categoria, clean_name)
        code = self._unique_code(Categoria, clean_name)
        max_order = self.session.exec(select(func.max(Categoria.orden))).one() or 0
        category = Categoria(
            codigo=code,
            nombre=clean_name,
            descripcion_publica=self._optional_text(description),
            orden=int(max_order) + 1,
            visible_cliente=True,
            activa=True,
        )
        self.session.add(category)
        self.session.flush()
        self._audit(current_user, "categorias", "alta", category.id, f"Categoría {clean_name} creada", None, category)
        self.session.commit()
        self.session.refresh(category)
        return category

    def update_category(self, category_id: int, name: str, description: str, current_user: UsuarioRead) -> Categoria:
        self._require_config(current_user)
        category = self._get(Categoria, category_id, "La categoría seleccionada ya no existe.")
        before = self._snapshot(category)
        clean_name = self._required_text(name, "El nombre de la categoría es obligatorio.")
        self._ensure_unique_name(Categoria, clean_name, excluding_id=category_id)
        category.nombre = clean_name
        category.descripcion_publica = self._optional_text(description)
        self.session.add(category)
        self._audit(current_user, "categorias", "modificacion", category.id, f"Categoría {clean_name} modificada", before, category)
        self.session.commit()
        self.session.refresh(category)
        return category

    def set_category_active(self, category_id: int, active: bool, current_user: UsuarioRead) -> Categoria:
        self._require_config(current_user)
        category = self._get(Categoria, category_id, "La categoría seleccionada ya no existe.")
        before = self._snapshot(category)
        category.activa = active
        self.session.add(category)
        action = "reactivacion" if active else "baja"
        self._audit(current_user, "categorias", action, category.id, f"Categoría {category.nombre} {'reactivada' if active else 'desactivada'}", before, category)
        self.session.commit()
        self.session.refresh(category)
        return category

    def list_addons(self, current_user: UsuarioRead) -> list[tuple[Agregado, list[Categoria]]]:
        self._require_config(current_user)
        addons = self.session.exec(select(Agregado).order_by(Agregado.nombre)).all()
        relations = self.session.exec(select(AgregadoCategoria)).all()
        categories = {category.id: category for category in self.session.exec(select(Categoria)).all()}
        category_ids_by_addon: dict[int, list[int]] = {}
        for relation in relations:
            category_ids_by_addon.setdefault(relation.agregado_id, []).append(relation.categoria_id)
        return [
            (
                addon,
                [categories[category_id] for category_id in category_ids_by_addon.get(addon.id or 0, []) if category_id in categories],
            )
            for addon in addons
        ]

    def create_addon(
        self,
        name: str,
        price: Decimal,
        category_ids: Iterable[int],
        current_user: UsuarioRead,
    ) -> Agregado:
        self._require_config(current_user)
        clean_name = self._required_text(name, "El nombre del agregado es obligatorio.")
        self._ensure_unique_name(Agregado, clean_name)
        category_ids = self._validate_categories(category_ids)
        addon = Agregado(codigo=self._unique_code(Agregado, clean_name), nombre=clean_name, precio=self._money(price), activo=True)
        self.session.add(addon)
        self.session.flush()
        self._replace_addon_categories(addon.id or 0, category_ids)
        self._audit(current_user, "agregados", "alta", addon.id, f"Agregado {clean_name} creado", None, addon)
        self.session.commit()
        self.session.refresh(addon)
        return addon

    def update_addon(
        self,
        addon_id: int,
        name: str,
        price: Decimal,
        category_ids: Iterable[int],
        current_user: UsuarioRead,
    ) -> Agregado:
        self._require_config(current_user)
        addon = self._get(Agregado, addon_id, "El agregado seleccionado ya no existe.")
        before = self._snapshot(addon)
        clean_name = self._required_text(name, "El nombre del agregado es obligatorio.")
        self._ensure_unique_name(Agregado, clean_name, excluding_id=addon_id)
        category_ids = self._validate_categories(category_ids)
        addon.nombre = clean_name
        addon.precio = self._money(price)
        self.session.add(addon)
        self._replace_addon_categories(addon_id, category_ids)
        self._audit(current_user, "agregados", "modificacion", addon.id, f"Agregado {clean_name} modificado", before, addon)
        self.session.commit()
        self.session.refresh(addon)
        return addon

    def set_addon_active(self, addon_id: int, active: bool, current_user: UsuarioRead) -> Agregado:
        self._require_config(current_user)
        addon = self._get(Agregado, addon_id, "El agregado seleccionado ya no existe.")
        before = self._snapshot(addon)
        addon.activo = active
        self.session.add(addon)
        action = "reactivacion" if active else "baja"
        self._audit(current_user, "agregados", action, addon.id, f"Agregado {addon.nombre} {'reactivado' if active else 'desactivado'}", before, addon)
        self.session.commit()
        self.session.refresh(addon)
        return addon

    def list_users(self, current_user: UsuarioRead) -> list[Usuario]:
        self._require_users(current_user)
        return list(self.session.exec(select(Usuario).order_by(Usuario.username)).all())

    def create_user(
        self,
        username: str,
        password: str,
        permissions: Iterable[str],
        current_user: UsuarioRead,
    ) -> Usuario:
        self._require_users(current_user)
        normalized_permissions = AuthService.normalize_permissions(permissions)
        if not normalized_permissions:
            raise ValidationError("Selecciona al menos un permiso para el usuario.")
        role = self._role_for_permissions(normalized_permissions)
        created = AuthService(self.session).create_user(
            username,
            password,
            role,
            normalized_permissions,
            commit=False,
        )
        user = self._get(Usuario, created.id, "No se pudo recuperar el usuario creado.")
        self._audit(current_user, "usuarios", "alta", user.id, f"Usuario {user.username} creado", None, user)
        self.session.commit()
        self.session.refresh(user)
        return user

    def update_user(
        self,
        user_id: int,
        username: str,
        password: str,
        permissions: Iterable[str],
        current_user: UsuarioRead,
    ) -> Usuario:
        self._require_users(current_user)
        user = self._get(Usuario, user_id, "El usuario seleccionado ya no existe.")
        before = self._snapshot(user, sensitive=True)
        clean_username = self._required_text(username, "El nombre de usuario es obligatorio.").upper()
        existing = self.session.exec(
            select(Usuario).where(func.upper(Usuario.username) == clean_username, Usuario.id != user_id)
        ).first()
        if existing is not None:
            raise ConflictError("Ya existe otro usuario con ese nombre.")
        normalized_permissions = AuthService.normalize_permissions(permissions)
        if not normalized_permissions:
            raise ValidationError("Selecciona al menos un permiso para el usuario.")
        if user.activo and PermisoUsuario.USUARIOS.value in AuthService.effective_permissions(user):
            if PermisoUsuario.USUARIOS.value not in normalized_permissions:
                self._ensure_another_user_manager(user_id)
        user.username = clean_username
        user.permisos = normalized_permissions
        user.rol = self._role_for_permissions(normalized_permissions)
        user.updated_at = datetime.now(timezone.utc)
        if password.strip():
            user.password_hash = hash_password(password)
        self.session.add(user)
        self._audit(current_user, "usuarios", "modificacion", user.id, f"Usuario {clean_username} modificado", before, user)
        self.session.commit()
        self.session.refresh(user)
        return user

    def set_user_active(self, user_id: int, active: bool, current_user: UsuarioRead) -> Usuario:
        self._require_users(current_user)
        user = self._get(Usuario, user_id, "El usuario seleccionado ya no existe.")
        if not active and user.id == current_user.id:
            raise ValidationError("No puedes desactivar tu propio usuario.")
        if not active and PermisoUsuario.USUARIOS.value in AuthService.effective_permissions(user):
            self._ensure_another_user_manager(user_id)
        before = self._snapshot(user, sensitive=True)
        user.activo = active
        user.updated_at = datetime.now(timezone.utc)
        self.session.add(user)
        action = "reactivacion" if active else "baja"
        self._audit(current_user, "usuarios", action, user.id, f"Usuario {user.username} {'reactivado' if active else 'desactivado'}", before, user)
        self.session.commit()
        self.session.refresh(user)
        return user

    def _replace_addon_categories(self, addon_id: int, category_ids: list[int]) -> None:
        existing = self.session.exec(
            select(AgregadoCategoria).where(AgregadoCategoria.agregado_id == addon_id)
        ).all()
        existing_ids = {relation.categoria_id for relation in existing}
        desired_ids = set(category_ids)
        for relation in existing:
            if relation.categoria_id not in desired_ids:
                self.session.delete(relation)
        for category_id in desired_ids - existing_ids:
            self.session.add(AgregadoCategoria(agregado_id=addon_id, categoria_id=category_id))

    def _validate_categories(self, category_ids: Iterable[int]) -> list[int]:
        ids = sorted({int(category_id) for category_id in category_ids})
        if not ids:
            raise ValidationError("Selecciona al menos una categoría para el agregado.")
        found = self.session.exec(select(Categoria).where(Categoria.id.in_(ids))).all()
        if len(found) != len(ids):
            raise ValidationError("Una de las categorías seleccionadas ya no existe.")
        return ids

    def _ensure_another_user_manager(self, excluding_id: int) -> None:
        users = self.session.exec(select(Usuario).where(Usuario.activo == True, Usuario.id != excluding_id)).all()
        if not any(PermisoUsuario.USUARIOS.value in AuthService.effective_permissions(user) for user in users):
            raise ValidationError("Debe quedar al menos un usuario activo con permiso para administrar usuarios.")

    def _require_config(self, current_user: UsuarioRead) -> None:
        AuthService(self.session).require_permission(current_user, PermisoUsuario.CONFIGURACION)

    def _require_users(self, current_user: UsuarioRead) -> None:
        AuthService(self.session).require_permission(current_user, PermisoUsuario.USUARIOS)

    def _audit(
        self,
        current_user: UsuarioRead,
        section: str,
        action: str,
        record_id: int | None,
        summary: str,
        before: dict[str, Any] | None,
        after: Any,
    ) -> None:
        self.session.add(
            CambioAdministrativo(
                usuario_id=current_user.id,
                usuario_nombre=current_user.username,
                seccion=section,
                accion=action,
                registro_id=record_id,
                resumen=summary,
                datos_anteriores=json.dumps(before, ensure_ascii=False, default=str) if before else None,
                datos_nuevos=json.dumps(self._snapshot(after, sensitive=True), ensure_ascii=False, default=str),
            )
        )

    @staticmethod
    def _snapshot(record: Any, sensitive: bool = False) -> dict[str, Any]:
        data = record.model_dump()
        if isinstance(record, Usuario) or sensitive:
            data.pop("password_hash", None)
        return data

    def _ensure_unique_name(self, model: Any, name: str, excluding_id: int | None = None) -> None:
        statement = select(model).where(func.upper(model.nombre) == name.upper())
        if excluding_id is not None:
            statement = statement.where(model.id != excluding_id)
        if self.session.exec(statement).first() is not None:
            raise ConflictError("Ya existe un registro con ese nombre.")

    def _unique_code(self, model: Any, name: str) -> str:
        base = self._code_from_name(name)
        candidate = base
        suffix = 2
        while self.session.exec(select(model).where(func.upper(model.codigo) == candidate)).first() is not None:
            candidate = f"{base}_{suffix}"
            suffix += 1
        return candidate

    @staticmethod
    def _code_from_name(name: str) -> str:
        normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
        code = re.sub(r"[^A-Za-z0-9]+", "_", normalized).strip("_").upper()
        return (code or "REGISTRO")[:45]

    @staticmethod
    def _required_text(value: str, message: str) -> str:
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            raise ValidationError(message)
        return cleaned

    @staticmethod
    def _optional_text(value: str) -> str | None:
        return " ".join(value.strip().split()) or None

    @staticmethod
    def _money(value: Decimal) -> Decimal:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
        if amount < 0:
            raise ValidationError("El importe no puede ser negativo.")
        return amount

    def _get(self, model: Any, record_id: int, message: str) -> Any:
        record = self.session.get(model, record_id)
        if record is None:
            raise ValidationError(message)
        return record

    @staticmethod
    def _role_for_permissions(permissions: Iterable[str]) -> RolUsuario:
        values = set(permissions)
        if PermisoUsuario.CONFIGURACION.value in values or PermisoUsuario.USUARIOS.value in values:
            return RolUsuario.ADMIN
        return RolUsuario.DUENO
