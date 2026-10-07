from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    app_secret_key: str
    google_maps_api_key: str | None = None
    database_url: str
    media_storage_backend: str = "local"
    supabase_url: str | None = None
    supabase_key: str | None = None
    supabase_service_role_key: str | None = None
    supabase_storage_bucket: str = "gastroflow-media"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
