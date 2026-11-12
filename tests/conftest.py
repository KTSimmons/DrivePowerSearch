import pytest

from drive_search.logging_setup import shutdown_logging


@pytest.fixture(autouse=True)
def _reset_logging():
    """Close our log handlers after every test (avoids Windows file locks)."""
    yield
    shutdown_logging()


@pytest.fixture(autouse=True)
def _isolate_auth_env(monkeypatch):
    """Tests must never pick up real credential paths from the environment."""
    monkeypatch.delenv("GDRIVE_CREDENTIALS", raising=False)
    monkeypatch.delenv("GDRIVE_TOKEN", raising=False)
