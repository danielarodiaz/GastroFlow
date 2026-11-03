from collections.abc import Iterable
from sqlalchemy import func

from sqlmodel import Session, select

from gastroflow.domain.enums import PermisoUsuario, RolUsuario
from gastroflow.domain.errors import AuthenticationError, AuthorizationError, ConflictError
from gastroflow.models import Usuario, UsuarioRead
from gastroflow.security import hash_password, verify_password


class AuthService:
    def __init__(self, session: Session):
        self.session = session

    def create_user(
        self,
        username: str,
        password: str,
        rol: RolUsuario,
        permisos: Iterable[PermisoUsuario | str] | None = None,
        *,
        commit: bool = True,
    ) -> UsuarioRead:
        normalized_username = self._normalize_username(username)
        existing_user = self._get_user_by_username(normalized_username)
        if existing_user is not None:
            raise ConflictError("Ya existe un usuario con ese username.")

        user = Usuario(
            username=normalized_username,
            password_hash=hash_password(password),
            rol=rol,
            activo=True,
            permisos=self.normalize_permissions(permisos or self.default_permissions(rol)),
        )
        self.session.add(user)
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        self.session.refresh(user)
        return self._to_read(user)

    def create_first_admin(self, username: str, password: str) -> UsuarioRead:
        existing_admin = self.session.exec(
            select(Usuario).where(Usuario.rol == RolUsuario.ADMIN)
        ).first()
        if existing_admin is not None:
            raise ConflictError("Ya existe un usuario Admin inicial.")

        return self.create_user(username=username, password=password, rol=RolUsuario.ADMIN)

    def authenticate(self, username: str, password: str) -> UsuarioRead:
        normalized_username = self._normalize_username(username)
        user = self._get_user_by_username(normalized_username)
        if user is None or not verify_password(password, user.password_hash):
            raise AuthenticationError("El usuario o la contraseña no son correctos.")
        if not user.activo:
            raise AuthenticationError("Este usuario está desactivado. Consulta con un administrador.")
        return self._to_read(user)

    def get_user(self, user_id: int) -> UsuarioRead | None:
        user = self.session.get(Usuario, user_id)
        if user is None or not user.activo:
            return None
        return self._to_read(user)

    def require_role(self, user: UsuarioRead, allowed_roles: Iterable[RolUsuario]) -> None:
        allowed = set(allowed_roles)
        if user.rol not in allowed:
            raise AuthorizationError("El usuario no tiene permisos para esta operacion.")

    def require_admin(self, user: UsuarioRead) -> None:
        self.require_role(user, [RolUsuario.ADMIN])

    def require_owner_or_admin(self, user: UsuarioRead) -> None:
        self.require_role(user, [RolUsuario.ADMIN, RolUsuario.DUENO])

    def require_permission(self, user: UsuarioRead, permission: PermisoUsuario) -> None:
        if permission.value not in self.effective_permissions(user):
            raise AuthorizationError("El usuario no tiene permisos para esta operación.")

    @staticmethod
    def default_permissions(role: RolUsuario) -> list[str]:
        if role == RolUsuario.ADMIN:
            return [permission.value for permission in PermisoUsuario]
        return [PermisoUsuario.PEDIDOS.value, PermisoUsuario.GASTOS.value]

    @classmethod
    def effective_permissions(cls, user: UsuarioRead | Usuario) -> set[str]:
        permissions = cls.normalize_permissions(user.permisos)
        if permissions:
            return set(permissions)
        return set(cls.default_permissions(user.rol))

    @staticmethod
    def normalize_permissions(permissions: Iterable[PermisoUsuario | str]) -> list[str]:
        allowed = {permission.value for permission in PermisoUsuario}
        normalized = {
            permission.value if isinstance(permission, PermisoUsuario) else str(permission)
            for permission in permissions
        }
        return [permission.value for permission in PermisoUsuario if permission.value in normalized and permission.value in allowed]

    def _get_user_by_username(self, username: str) -> Usuario | None:
        return self.session.exec(select(Usuario).where(func.upper(Usuario.username) == username.upper())).first()

    @staticmethod
    def _normalize_username(username: str) -> str:
        return username.strip().upper()

    @staticmethod
    def _to_read(user: Usuario) -> UsuarioRead:
        return UsuarioRead(
            id=user.id or 0,
            username=user.username,
            rol=user.rol,
            activo=user.activo,
            permisos=list(user.permisos or []),
            created_at=user.created_at,
            updated_at=user.updated_at,
        )
