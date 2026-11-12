"""Google authentication and authorization.

This is the ONLY module that reads credential or token files, handles tokens,
or names OAuth scopes. It does not depend on the search or report code, so it
can be reused by other Google Drive tools.

Flow:
1. Use the cached token if it is valid.
2. If it has expired and has a refresh token, refresh it silently and save it.
3. Otherwise run the OAuth "Desktop app" browser sign-in and save the token.

Token contents are never printed or logged.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Sequence

from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCOPES = ["https://www.googleapis.com/auth/drive.metadata.readonly"]
DEFAULT_CREDENTIALS_FILE = PROJECT_ROOT / "credentials.json"
DEFAULT_TOKEN_FILE = PROJECT_ROOT / "token.json"
ENV_CREDENTIALS = "GDRIVE_CREDENTIALS"
ENV_TOKEN = "GDRIVE_TOKEN"


class AuthError(Exception):
    """Base class for authentication problems."""


class CredentialsNotFoundError(AuthError):
    """The OAuth client secrets file (credentials.json) is missing."""


class AuthenticationError(AuthError):
    """Sign-in failed, was cancelled, or a token could not be used."""


def _resolve_path(explicit: str | os.PathLike[str] | None, env_var: str, default: Path) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    from_env = os.environ.get(env_var)
    if from_env:
        return Path(from_env).expanduser().resolve()
    return default


def _save_token(creds: Credentials, token_path: Path) -> None:
    try:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
    except OSError as exc:
        # Not fatal: the search can still run, you'll just sign in again next time.
        logger.warning("Could not save the sign-in token to %s (%s).", token_path, exc.__class__.__name__)
        return
    logger.info("Saved sign-in token to %s", token_path)


def _load_cached(token_path: Path, scopes: Sequence[str]) -> Credentials | None:
    if not token_path.exists():
        logger.info("No saved sign-in token at %s", token_path)
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(token_path))
    except (ValueError, OSError) as exc:
        logger.warning("Saved sign-in token could not be read (%s); signing in again.", exc.__class__.__name__)
        return None
    if not creds.has_scopes(list(scopes)):
        logger.warning("Saved sign-in token was granted different permissions; signing in again.")
        return None
    return creds


def get_credentials(
    credentials_path: str | os.PathLike[str] | None = None,
    token_path: str | os.PathLike[str] | None = None,
    scopes: Sequence[str] | None = None,
) -> Credentials:
    """Return valid Google credentials, signing in only when needed.

    Paths default to the ``GDRIVE_CREDENTIALS`` / ``GDRIVE_TOKEN`` environment
    variables, then to ``credentials.json`` / ``token.json`` in the project folder.

    Raises:
        CredentialsNotFoundError: a browser sign-in is needed but credentials.json is missing.
        AuthenticationError: sign-in failed or was cancelled.
    """
    scopes = list(scopes or DEFAULT_SCOPES)
    secrets_file = _resolve_path(credentials_path, ENV_CREDENTIALS, DEFAULT_CREDENTIALS_FILE)
    token_file = _resolve_path(token_path, ENV_TOKEN, DEFAULT_TOKEN_FILE)

    creds = _load_cached(token_file, scopes)
    if creds is not None and creds.valid:
        logger.info("Using saved sign-in token")
        return creds

    if creds is not None and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            logger.warning("Saved sign-in token could not be refreshed (it may have been revoked); signing in again.")
        except TransportError as exc:
            raise AuthenticationError("Could not reach Google to refresh your sign-in. Check your internet connection.") from exc
        else:
            logger.info("Refreshed sign-in token")
            _save_token(creds, token_file)
            return creds

    if not secrets_file.exists():
        raise CredentialsNotFoundError(
            f"OAuth client file not found: {secrets_file}. "
            "Create a 'Desktop app' OAuth client in Google Cloud Console, download it as "
            "credentials.json, and put it there (see README, 'Google Cloud setup')."
        )

    logger.info("Starting browser sign-in")
    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(secrets_file), scopes)
        creds = flow.run_local_server(port=0)
    except Exception as exc:  # oauthlib raises many types; all mean "sign-in failed"
        raise AuthenticationError(f"Google sign-in failed or was cancelled ({exc.__class__.__name__}).") from exc
    logger.info("Browser sign-in completed")
    _save_token(creds, token_file)
    return creds


def build_drive_service(credentials: Credentials) -> Any:
    """Return a ready-to-use Google Drive v3 client."""
    return build("drive", "v3", credentials=credentials, cache_discovery=False)
