from __future__ import annotations

import os

from alembic import command
from alembic.config import Config

from scripts import create_admin, seed_catalog


def main() -> None:
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    seed_catalog.main()

    if os.getenv("FIRST_ADMIN_USERNAME") and os.getenv("FIRST_ADMIN_PASSWORD"):
        create_admin.main()
    else:
        print("Admin no creado: define FIRST_ADMIN_USERNAME y FIRST_ADMIN_PASSWORD para crearlo automaticamente.")


if __name__ == "__main__":
    main()
