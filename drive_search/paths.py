"""Rebuilding full paths from Drive parent folders, with caching.

Drive has no real paths: a file has parent folder IDs. We walk the first
parent up to the root (My Drive or a shared drive). If a parent can't be seen
(typical for files shared with you), the path starts with "(shared with me)".
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from googleapiclient.errors import HttpError

from drive_search.search import DriveSearchError, execute_with_retry, http_status

logger = logging.getLogger(__name__)

MY_DRIVE = "My Drive"
SHARED_WITH_ME = "(shared with me)"
FOLDER_FIELDS = "id, name, parents, driveId"
_UNFETCHED = object()


class PathResolver:
    """Turns Drive file metadata into a readable full path."""

    def __init__(self, service: Any, *, sleep: Callable[[float], None] = time.sleep) -> None:
        self._service = service
        self._sleep = sleep
        self._folders: dict[str, dict[str, Any] | None] = {}
        self._root_id: Any = _UNFETCHED

    @property
    def root_id(self) -> str | None:
        """ID of the user's My Drive root folder (looked up once)."""
        if self._root_id is _UNFETCHED:
            try:
                root = execute_with_retry(
                    self._service.files().get(fileId="root", fields="id"),
                    description="My Drive root lookup",
                    sleep=self._sleep,
                )
                self._root_id = root.get("id")
            except HttpError as exc:
                logger.warning("Could not look up the My Drive root folder (HTTP %d).", http_status(exc))
                self._root_id = None
        return self._root_id

    def _folder(self, folder_id: str) -> dict[str, Any] | None:
        if folder_id in self._folders:
            logger.debug("Folder cache hit: %s", folder_id)
            return self._folders[folder_id]
        logger.debug("Folder cache miss: %s", folder_id)
        try:
            folder: dict[str, Any] | None = execute_with_retry(
                self._service.files().get(fileId=folder_id, fields=FOLDER_FIELDS, supportsAllDrives=True),
                description="Folder lookup",
                sleep=self._sleep,
            )
        except HttpError as exc:
            if http_status(exc) in (403, 404):
                folder = None  # exists but we can't see it
            else:
                raise DriveSearchError(f"Folder lookup failed (HTTP {http_status(exc)}).") from exc
        self._folders[folder_id] = folder
        return folder

    def resolve(self, file: dict[str, Any]) -> str:
        """Return a path such as ``My Drive/Projects/2026/report.pdf``."""
        segments = [file.get("name") or "(unnamed)"]
        parents = file.get("parents") or []
        current = parents[0] if parents else None
        seen: set[str] = set()

        while current and current not in seen:
            seen.add(current)
            if current == self.root_id:
                segments.append(MY_DRIVE)
                return "/".join(reversed(segments))
            folder = self._folder(current)
            if folder is None:
                break
            if folder.get("driveId") and folder.get("driveId") == current:
                segments.append(folder.get("name") or "Shared drive")  # shared drive root
                return "/".join(reversed(segments))
            segments.append(folder.get("name") or "(unnamed folder)")
            folder_parents = folder.get("parents") or []
            current = folder_parents[0] if folder_parents else None

        logger.warning("Could not resolve the full path for file id=%s; marking it as shared.", file.get("id"))
        segments.append(SHARED_WITH_ME)
        return "/".join(reversed(segments))
