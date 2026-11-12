"""Building the Drive query, calling the API, pagination and retries.

Receives a Drive service object and never creates one (dependency injection),
so tests can pass in a fake.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from typing import Any, Callable

import httplib2
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

FILE_FIELDS = "id, name, mimeType, createdTime, modifiedTime, parents, driveId, webViewLink"
PAGE_SIZE = 100
MAX_RETRIES = 5
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
RATE_LIMIT_REASONS = {"rateLimitExceeded", "userRateLimitExceeded"}


class DriveSearchError(Exception):
    """Google Drive could not be searched."""


@dataclass(frozen=True)
class SearchCriteria:
    """What to search for. Dates are local calendar dates, inclusive."""

    name: str
    exact: bool = False
    created_on: date | None = None
    created_after: date | None = None
    created_before: date | None = None
    include_shared_drives: bool = False


def escape_query_value(value: str) -> str:
    """Escape a value for use inside single quotes in a Drive query."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _local_midnight(day: date) -> datetime:
    """Start of ``day`` in the local time zone (DST-aware)."""
    return datetime.combine(day, dt_time.min).astimezone()


def created_range(criteria: SearchCriteria) -> tuple[datetime | None, datetime | None]:
    """Return the (start inclusive, end exclusive) creation window in UTC."""
    start: datetime | None = None
    end: datetime | None = None
    if criteria.created_on:
        start = _local_midnight(criteria.created_on)
        end = _local_midnight(criteria.created_on + timedelta(days=1))
    else:
        if criteria.created_after:
            start = _local_midnight(criteria.created_after)
        if criteria.created_before:
            end = _local_midnight(criteria.created_before + timedelta(days=1))
    return (
        start.astimezone(timezone.utc) if start else None,
        end.astimezone(timezone.utc) if end else None,
    )


def to_rfc3339(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_query(criteria: SearchCriteria) -> str:
    """Build the Drive API ``q`` string for ``criteria``."""
    operator = "=" if criteria.exact else "contains"
    parts = [f"name {operator} '{escape_query_value(criteria.name)}'", "trashed = false"]
    start, end = created_range(criteria)
    if start:
        parts.append(f"createdTime >= '{to_rfc3339(start)}'")
    if end:
        parts.append(f"createdTime < '{to_rfc3339(end)}'")
    return " and ".join(parts)


def _error_reasons(exc: HttpError) -> set[str]:
    details = getattr(exc, "error_details", None)
    if isinstance(details, list):
        return {d.get("reason", "") for d in details if isinstance(d, dict)}
    return set()


def http_status(exc: HttpError) -> int:
    return int(getattr(exc.resp, "status", 0) or 0)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, HttpError):
        status = http_status(exc)
        if status in RETRYABLE_STATUS:
            return True
        return status == 403 and bool(_error_reasons(exc) & RATE_LIMIT_REASONS)
    # Network problems: DNS, connection reset, timeouts.
    return isinstance(exc, (httplib2.HttpLib2Error, OSError))


def _short_error(exc: BaseException) -> str:
    if isinstance(exc, HttpError):
        return f"HTTP {http_status(exc)}"
    return exc.__class__.__name__


def execute_with_retry(
    request: Any,
    *,
    description: str,
    max_retries: int = MAX_RETRIES,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Execute an API request, retrying rate limits and network errors with backoff.

    Non-retryable ``HttpError``s are re-raised unchanged so callers can inspect
    the status. Exhausted retries raise ``DriveSearchError``.
    """
    attempt = 0
    while True:
        try:
            return request.execute()
        except Exception as exc:
            if not _is_retryable(exc):
                raise
            attempt += 1
            if attempt > max_retries:
                raise DriveSearchError(
                    f"{description} still failing after {max_retries} retries ({_short_error(exc)})."
                ) from exc
            wait = min(2 ** (attempt - 1), 32) + random.uniform(0, 1)
            logger.warning(
                "%s failed (%s); retry %d of %d in %.1f s", description, _short_error(exc), attempt, max_retries, wait
            )
            sleep(wait)


def search_files(
    service: Any,
    criteria: SearchCriteria,
    *,
    page_size: int = PAGE_SIZE,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    """Return every matching file, newest first, following all result pages."""
    query = build_query(criteria)
    params: dict[str, Any] = {
        "q": query,
        "pageSize": page_size,
        "fields": f"nextPageToken, files({FILE_FIELDS})",
        "spaces": "drive",
    }
    if criteria.include_shared_drives:
        params.update(corpora="allDrives", includeItemsFromAllDrives=True, supportsAllDrives=True)

    logger.info("Searching Drive with query: %s", query)
    logger.debug("Request parameters: %s", params)

    files: list[dict[str, Any]] = []
    page = 0
    while True:
        page += 1
        started = time.monotonic()
        try:
            response = execute_with_retry(
                service.files().list(**params), description=f"Drive search page {page}", sleep=sleep
            )
        except HttpError as exc:
            raise DriveSearchError(f"Google Drive rejected the search request (HTTP {http_status(exc)}).") from exc
        batch = response.get("files", [])
        logger.info("Page %d returned %d files in %.2f s", page, len(batch), time.monotonic() - started)
        for item in batch:
            logger.debug("Found file id=%s name=%r", item.get("id"), item.get("name"))
        files.extend(batch)
        token = response.get("nextPageToken")
        if not token:
            break
        params["pageToken"] = token

    if criteria.exact:
        # Enforce a case-sensitive whole-name match regardless of API behavior.
        before = len(files)
        files = [f for f in files if f.get("name") == criteria.name]
        if len(files) != before:
            logger.info("Kept %d of %d files after the exact-name check", len(files), before)

    # RFC 3339 UTC strings from Drive sort correctly as text.
    files.sort(key=lambda f: f.get("createdTime", ""), reverse=True)
    logger.info("Total matches: %d", len(files))
    return files
