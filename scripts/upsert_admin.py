from __future__ import annotations

import argparse
import getpass
import os

from sqlmodel import Session, select
from sqlalchemy import func

from gastroflow.data.database import engine
from gastroflow.domain.enums import RolUsuario
from gastroflow.models import Usuario
from gastroflow.security import hash_password
from gastroflow.services import AuthService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crea o actualiza un usuario Admin de desarrollo.")
    parser.add_argument("--username", default=os.getenv("ADMIN_USERNAME", "admin"))
    parser.add_argument("--password", default=os.getenv("ADMIN_PASSWORD"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    username = args.username.strip().upper()
    password = args.password or getpass.getpass("Password Admin: ")

    with Session(engine) as session:
        user = session.exec(select(Usuario).where(func.upper(Usuario.username) == username)).first()
        if user is None:
            admin = AuthService(session).create_user(username=username, password=password, rol=RolUsuario.ADMIN)
            print(f"Admin creado: {admin.username}")
            return

        user.password_hash = hash_password(password)
        user.rol = RolUsuario.ADMIN
        session.add(user)
        session.commit()
        print(f"Admin actualizado: {username}")


if __name__ == "__main__":
    main()
