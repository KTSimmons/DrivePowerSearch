import json
from types import SimpleNamespace

import pytest
from google.auth.exceptions import RefreshError

from drive_search import auth
from drive_search.logging_setup import setup_logging

TOKEN_SECRET = "ya29.TOKEN-SECRET-VALUE"
REFRESH_SECRET = "1//REFRESH-SECRET-VALUE"


class FakeCreds:
    def __init__(self, valid=True, expired=False, scopes=None, refresh_error=None):
        self.valid = valid
        self.expired = expired
        self.refresh_token = REFRESH_SECRET
        self.token = TOKEN_SECRET
        self.scopes = list(auth.DEFAULT_SCOPES if scopes is None else scopes)
        self.refresh_error = refresh_error
        self.refreshed = False

    def has_scopes(self, scopes):
        return set(scopes).issubset(self.scopes)

    def refresh(self, request):
        if self.refresh_error:
            raise self.refresh_error
        self.valid, self.expired, self.refreshed = True, False, True

    def to_json(self):
        return json.dumps({"token": self.token, "refresh_token": self.refresh_token, "scopes": self.scopes})


class FakeFlow:
    def __init__(self, creds=None, error=None):
        self.creds = creds or FakeCreds()
        self.error = error
        self.ran = False

    def run_local_server(self, port=0):
        self.ran = True
        if self.error:
            raise self.error
        return self.creds


@pytest.fixture
def paths(tmp_path):
    return tmp_path / "credentials.json", tmp_path / "token.json"


def install(monkeypatch, cached=None, flow=None):
    monkeypatch.setattr(auth, "Credentials", SimpleNamespace(from_authorized_user_file=lambda path: cached))
    flow = flow or FakeFlow()
    monkeypatch.setattr(auth, "InstalledAppFlow", SimpleNamespace(from_client_secrets_file=lambda path, scopes: flow))
    monkeypatch.setattr(auth, "Request", lambda: object())
    return flow


def test_valid_cached_token_is_used(monkeypatch, paths):
    secrets, token = paths
    token.write_text("{}")
    cached = FakeCreds()
    flow = install(monkeypatch, cached=cached)
    assert auth.get_credentials(secrets, token) is cached
    assert not flow.ran


def test_expired_token_is_refreshed_and_saved(monkeypatch, paths):
    secrets, token = paths
    token.write_text("{}")
    cached = FakeCreds(valid=False, expired=True)
    flow = install(monkeypatch, cached=cached)
    assert auth.get_credentials(secrets, token) is cached
    assert cached.refreshed and not flow.ran
    assert json.loads(token.read_text())["token"] == TOKEN_SECRET


def test_no_token_runs_browser_sign_in(monkeypatch, paths):
    secrets, token = paths
    secrets.write_text("{}")
    flow = install(monkeypatch)
    creds = auth.get_credentials(secrets, token)
    assert flow.ran and creds is flow.creds
    assert token.exists()


def test_missing_credentials_file(monkeypatch, paths):
    secrets, token = paths
    install(monkeypatch)
    with pytest.raises(auth.CredentialsNotFoundError, match="credentials.json"):
        auth.get_credentials(secrets, token)


def test_different_scopes_force_sign_in(monkeypatch, paths):
    secrets, token = paths
    secrets.write_text("{}")
    token.write_text("{}")
    flow = install(monkeypatch, cached=FakeCreds(scopes=["https://www.googleapis.com/auth/other"]))
    auth.get_credentials(secrets, token)
    assert flow.ran


def test_revoked_refresh_token_falls_back_to_sign_in(monkeypatch, paths):
    secrets, token = paths
    secrets.write_text("{}")
    token.write_text("{}")
    flow = install(monkeypatch, cached=FakeCreds(valid=False, expired=True, refresh_error=RefreshError("revoked")))
    auth.get_credentials(secrets, token)
    assert flow.ran


def test_cancelled_sign_in_raises_authentication_error(monkeypatch, paths):
    secrets, token = paths
    secrets.write_text("{}")
    install(monkeypatch, flow=FakeFlow(error=RuntimeError("user closed the browser")))
    with pytest.raises(auth.AuthenticationError, match="failed or was cancelled"):
        auth.get_credentials(secrets, token)


def test_environment_variables_override_paths(monkeypatch, tmp_path):
    custom = tmp_path / "elsewhere" / "my_client.json"
    monkeypatch.setenv(auth.ENV_CREDENTIALS, str(custom))
    monkeypatch.setenv(auth.ENV_TOKEN, str(tmp_path / "elsewhere" / "tok.json"))
    install(monkeypatch)
    with pytest.raises(auth.CredentialsNotFoundError) as excinfo:
        auth.get_credentials()
    assert str(custom) in str(excinfo.value)


def test_secrets_never_reach_the_log(monkeypatch, tmp_path, paths):
    secrets, token = paths
    secrets.write_text("{}")
    info = setup_logging(level="DEBUG", log_dir=tmp_path / "logs")
    # Success path: sign in, save token, then refresh on a second call.
    install(monkeypatch)
    auth.get_credentials(secrets, token)
    install(monkeypatch, cached=FakeCreds(valid=False, expired=True))
    auth.get_credentials(secrets, token)
    # Failure path.
    token.unlink()
    install(monkeypatch, flow=FakeFlow(error=RuntimeError("boom")))
    with pytest.raises(auth.AuthenticationError):
        auth.get_credentials(secrets, token)

    log = info.log_file.read_text(encoding="utf-8")
    assert "Browser sign-in completed" in log  # proves logging happened
    assert TOKEN_SECRET not in log
    assert REFRESH_SECRET not in log
