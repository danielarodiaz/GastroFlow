from __future__ import annotations

import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import reflex as rx
from reflex.constants import Endpoint

from gastroflow.config.settings import get_settings


def normalize_media_url(value: str | None) -> str:
    if not value:
        return ""
    clean = value.strip()
    if clean.startswith(("http://", "https://")):
        return clean
    path = clean.replace("/uploaded_files/", "").lstrip("/")
    return f"{Endpoint.UPLOAD.get_url().rstrip('/')}/{path}"


async def save_media_upload(file: rx.UploadFile, folder: str) -> str:
    safe_name = "".join(char for char in file.filename if char.isalnum() or char in {".", "-", "_"})
    filename = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}_{safe_name}"
    content = await file.read()

    settings = get_settings()
    if settings.media_storage_backend.lower() == "supabase":
        return _upload_to_supabase(
            content=content,
            folder=folder,
            filename=filename,
            content_type=file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream",
        )

    upload_dir = Path(rx.get_upload_dir()) / folder
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / filename).write_bytes(content)
    return f"{folder}/{filename}"


def _upload_to_supabase(*, content: bytes, folder: str, filename: str, content_type: str) -> str:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("Supabase Storage requiere SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY.")

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
            "apikey": settings.supabase_service_role_key,
            "Authorization": f"Bearer {settings.supabase_service_role_key}",
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
