import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from app.core.config import ConfigError, get_settings
from app.main import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_health_ok():
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_missing_config_gives_clear_error(monkeypatch):
    monkeypatch.delenv("KEITARO_URL")
    monkeypatch.delenv("KEITARO_API_KEY")
    get_settings.cache_clear()
    with pytest.raises(ConfigError, match="KEITARO_URL.*KEITARO_API_KEY|KEITARO_API_KEY.*KEITARO_URL"):
        create_app()


def test_api_key_not_leaked_in_repr():
    assert "test-key" not in repr(get_settings())


def _alembic(*args: str, db_url: str) -> None:
    env = {**os.environ, "DATABASE_URL": db_url}
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=PROJECT_ROOT, env=env, check=True, capture_output=True,
    )


def test_migrations_upgrade_and_downgrade(tmp_path):
    db_url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    _alembic("upgrade", "head", db_url=db_url)
    tables = set(inspect(create_engine(db_url)).get_table_names())
    assert {"campaign_records", "operation_logs"} <= tables

    _alembic("downgrade", "base", db_url=db_url)
    tables = set(inspect(create_engine(db_url)).get_table_names())
    assert not ({"campaign_records", "operation_logs"} & tables)
