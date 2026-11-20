from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    return create_engine(url, connect_args={"check_same_thread": False})  # SQLite, used from FastAPI threads


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = _session_factory()()
    try:
        yield db
    finally:
        db.close()
