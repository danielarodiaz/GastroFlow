from __future__ import annotations

from datetime import datetime, timezone

from gastroflow.services.media_storage import save_media_bytes


def main() -> None:
    filename = f"smoke_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.txt"
    url = save_media_bytes(
        content=b"GastroFlow media storage smoke test\n",
        folder="smoke-tests",
        filename=filename,
        content_type="text/plain; charset=utf-8",
    )
    print(f"Media storage OK: {url}")


if __name__ == "__main__":
    main()
