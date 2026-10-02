from collections.abc import Generator

from sqlalchemy import Engine
from sqlmodel import Session, create_engine

from gastroflow.config.settings import get_settings


def create_db_engine() -> Engine:
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True)


engine = create_db_engine()


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
