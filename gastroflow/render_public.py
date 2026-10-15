from __future__ import annotations

import os

from reflex.constants import LogLevel
from reflex.utils.exec import run_backend_prod


def main() -> None:
    """Serve the prebuilt public frontend and Reflex backend on Render's port."""
    port = int(os.getenv("PORT", "10000"))
    run_backend_prod(
        host="0.0.0.0",
        port=port,
        loglevel=LogLevel.INFO,
        frontend_present=True,
        mount_frontend_compiled_app=True,
    )


if __name__ == "__main__":
    main()
