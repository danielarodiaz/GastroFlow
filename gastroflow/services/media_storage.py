from __future__ import annotations

import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from gastroflow.config.settings import get_settings

if TYPE_CHECKING:
    import reflex as rx


def normalize_media_url(value: str | None) -> str:
    if not value:
        return ""
    clean = value.strip()
    if clean.startswith(("http://", "https://")):
        return clean
    from reflex.constants import Endpoint

    path = clean.replace("/uploaded_files/", "").lstrip("/")
    return f"{Endpoint.UPLOAD.get_url().rstrip('/')}/{path}"


async def save_media_upload(file: "rx.UploadFile", folder: str) -> str:
    safe_name = "".join(char for char in file.filename if char.isalnum() or char in {".", "-", "_"})
    filename = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}_{safe_name}"
    content = await file.read()

    return save_media_bytes(
        content=content,
        folder=folder,
        filename=filename,
        content_type=file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream",
    )


def save_media_bytes(*, content: bytes, folder: str, filename: str, content_type: str) -> str:
    settings = get_settings()
    if settings.media_storage_backend.lower() == "supabase":
        return _upload_to_supabase(
            content=content,
            folder=folder,
            filename=filename,
            content_type=content_type,
        )

    upload_dir = Path("uploaded_files") / folder
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / filename).write_bytes(content)
    return f"{folder}/{filename}"


def _upload_to_supabase(*, content: bytes, folder: str, filename: str, content_type: str) -> str:
    settings = get_settings()
    supabase_key = settings.supabase_service_role_key or settings.supabase_key
    if not settings.supabase_url or not supabase_key:
        raise RuntimeError("Supabase Storage requiere SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY o SUPABASE_KEY.")
    if supabase_key.startswith(("sb_publishable", "sb_anon")):
        raise RuntimeError(
            "Supabase Storage requiere una service_role key para subir archivos desde el servidor. "
            "La publishable/anon key solo sirve para operaciones permitidas por politicas publicas."
        )

    base_url = settings.supabase_url.rstrip("/")
    bucket = settings.supabase_storage_bucket.strip("/")
    object_path = f"{folder.strip('/')}/{filename}"
    encoded_path = "/".join(quote(part) for part in object_path.split("/"))
    upload_url = f"{base_url}/storage/v1/object/{quote(bucket)}/{encoded_path}"

    request = Request(
        upload_url,
        data=content,
        method="POST",
        headers={
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Content-Type": content_type,
            "x-upsert": "true",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            if response.status >= 400:
                raise RuntimeError(f"Supabase Storage rechazo la subida con estado {response.status}.")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase Storage rechazo la subida: {exc.code} {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"No se pudo conectar con Supabase Storage: {exc.reason}") from exc

    return f"{base_url}/storage/v1/object/public/{quote(bucket)}/{encoded_path}"
