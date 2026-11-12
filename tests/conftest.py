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


@pytest.fixture(autouse=True)
def _hide_real_drive_mount(monkeypatch):
    """Tests must never scan the real Google Drive for desktop mount (e.g. G:\\).
    Auto-detection reports "no mount"; local tests pass a temporary fake mount."""
    from drive_search import local_search

    monkeypatch.delenv("GDRIVE_LOCAL_ROOT", raising=False)
    monkeypatch.setattr(local_search, "find_drive_mount", lambda *a, **k: None)
