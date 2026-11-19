import os

import pytest

TEST_ENV = {
    "KEITARO_URL": "https://keitaro.test",
    "KEITARO_API_KEY": "test-key",
    "DATABASE_URL": "sqlite:///:memory:",
}
# Set before any `app.*` import: app.main builds the app at import time.
os.environ.update(TEST_ENV)


@pytest.fixture(autouse=True)
def _test_env(monkeypatch, tmp_path):
    """Isolate tests from the developer's real .env."""
    monkeypatch.chdir(tmp_path)  # no .env in cwd
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    from app.core.config import get_settings
    from app.services.defaults import clear_defaults_cache

    get_settings.cache_clear()
    clear_defaults_cache()
    yield
    get_settings.cache_clear()
    clear_defaults_cache()


BASE = TEST_ENV["KEITARO_URL"]
API = BASE + "/admin_api/v1"


@pytest.fixture
def db_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db import models  # noqa: F401
    from app.db.base import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()


@pytest.fixture
def api(db_session):
    """TestClient with in-memory DB and a Keitaro client pointing to the mocked BASE (no retries)."""
    from fastapi.testclient import TestClient

    from app.api.deps import get_keitaro
    from app.db.session import get_db
    from app.keitaro.client import KeitaroClient
    from app.main import create_app

    app = create_app()

    def _keitaro():
        c = KeitaroClient(BASE, "k", max_retries=0, retry_backoff=0)
        yield c
        c.close()

    app.dependency_overrides[get_keitaro] = _keitaro
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)
