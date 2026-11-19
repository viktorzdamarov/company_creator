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
