"""Searching the local Google Drive for desktop mount (no API, no credentials).

Google Drive for desktop shows Drive as a drive letter (for example ``G:\\``)
with ``My Drive`` and ``Shared drives`` folders. This module walks those folders
using directory listings and file details only. It never opens files, so
nothing is downloaded.

Results use the same dict shape as the API search, so ``reports.py`` and
``cli.py`` treat both sources the same way.
"""

from __future__ import annotations

import logging
import os
import string
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from drive_search.search import SearchCriteria, created_range

logger = logging.getLogger(__name__)

ENV_LOCAL_ROOT = "GDRIVE_LOCAL_ROOT"
MY_DRIVE_DIR = "My Drive"
SHARED_DRIVES_DIR = "Shared drives"
SKIP_PREFIXES = (".", "$")  # .shortcut-targets-by-id, .Encrypted, $RECYCLE.BIN, hidden files
CANDIDATE_LETTERS = string.ascii_uppercase[3:]  # D..Z (A/B are floppies, C is the system drive)
MAX_THREADS = 10
DEFAULT_THREADS = 10


class LocalDriveError(Exception):
    """The local Google Drive mount can't be found or used."""


def _as_mount(path: Path) -> Path | None:
    """Accept the mount root (``G:\\``) or ``My Drive`` itself; return the mount root."""
    try:
        if (path / MY_DRIVE_DIR).is_dir():
            return path
        if path.name == MY_DRIVE_DIR and path.is_dir():
            return path.parent
    except OSError:
        pass
    return None


def find_drive_mount(
    env: Mapping[str, str] | None = None,
    letters: Iterable[str] = CANDIDATE_LETTERS,
) -> Path | None:
    """Return the Google Drive for desktop mount, or None if there isn't one.

    Checks the ``GDRIVE_LOCAL_ROOT`` environment variable first, then drive
    letters D-Z for a folder named ``My Drive``.
    """
    env = os.environ if env is None else env
    override = env.get(ENV_LOCAL_ROOT)
    if override:
        mount = _as_mount(Path(override).expanduser())
        if mount is None:
            logger.warning("%s is set but contains no '%s' folder; ignoring it.", ENV_LOCAL_ROOT, MY_DRIVE_DIR)
        return mount
    for letter in letters:
        mount = _as_mount(Path(f"{letter}:\\"))
        if mount is not None:
            return mount
    return None


def resolve_mount(explicit: str | os.PathLike[str] | None) -> Path | None:
    """Mount from ``--drive-root`` if given (error if invalid), else auto-detect."""
    if explicit:
        mount = _as_mount(Path(explicit).expanduser())
        if mount is None:
            raise LocalDriveError(
                f"--drive-root {explicit} doesn't contain a '{MY_DRIVE_DIR}' folder. "
                "Point it at the Google Drive for desktop drive, for example G:\\"
            )
        return mount
    return find_drive_mount()


def search_roots(mount: Path, include_shared_drives: bool) -> list[Path]:
    roots = [mount / MY_DRIVE_DIR]
    shared = mount / SHARED_DRIVES_DIR
    if include_shared_drives and shared.is_dir():
        roots.append(shared)
    return roots


def _created(st: os.stat_result) -> float:
    return getattr(st, "st_birthtime", st.st_ctime)


def _rfc3339(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _name_matches(name: str, criteria: SearchCriteria) -> bool:
    if criteria.exact:
        return name == criteria.name
    return criteria.name.casefold() in name.casefold()


@dataclass
class _FolderResult:
    """What one worker found in one folder."""

    subfolders: list[Path] = field(default_factory=list)
    matches: list[dict[str, Any]] = field(default_factory=list)
    files_seen: int = 0
    unreadable: int = 0
    listed: bool = False


def _scan_folder(
    folder: Path, criteria: SearchCriteria, start_ts: float | None, end_ts: float | None
) -> _FolderResult:
    """List one folder and check its entries. Runs in a worker thread.

    Listing and ``stat`` are the slow, I/O-bound steps, so they run here,
    off the main thread. Only directory listings and file details are read.
    """
    result = _FolderResult()
    try:
        with os.scandir(folder) as it:
            entries = list(it)
    except OSError as exc:
        result.unreadable += 1
        logger.debug("Unreadable folder %s (%s)", folder, exc.__class__.__name__)
        return result
    result.listed = True
    for entry in entries:
        if entry.name.startswith(SKIP_PREFIXES):
            continue
        try:
            is_dir = entry.is_dir(follow_symlinks=False)
            if is_dir:
                result.subfolders.append(Path(entry.path))
            else:
                result.files_seen += 1
            if not _name_matches(entry.name, criteria):
                continue
            st = entry.stat(follow_symlinks=False)
        except OSError as exc:
            result.unreadable += 1
            logger.debug("Unreadable item %s (%s)", entry.path, exc.__class__.__name__)
            continue
        created = _created(st)
        if start_ts is not None and created < start_ts:
            continue
        if end_ts is not None and created >= end_ts:
            continue
        path = Path(entry.path)
        logger.debug("Match: %s", path)
        result.matches.append(
            {
                "id": None,
                "name": entry.name,
                "mimeType": "folder" if is_dir else "file",
                "createdTime": _rfc3339(created),
                "modifiedTime": _rfc3339(st.st_mtime),
                "localPath": str(path),
                "webViewLink": path.as_uri(),
            }
        )
    return result


def search_local(
    mount: Path,
    criteria: SearchCriteria,
    *,
    threads: int = DEFAULT_THREADS,
    clock: Callable[[], float] = time.monotonic,
) -> list[dict[str, Any]]:
    """Return matching files and folders under the mount, newest first.

    Folders are listed in parallel by up to ``threads`` worker threads (1-10).
    When a folder finishes, its subfolders are submitted as new tasks. Results
    are the same whatever the thread count.
    """
    if not 1 <= threads <= MAX_THREADS:
        raise ValueError(f"threads must be between 1 and {MAX_THREADS}, got {threads}")
    start, end = created_range(criteria)
    start_ts = start.timestamp() if start else None
    end_ts = end.timestamp() if end else None
    roots = search_roots(mount, criteria.include_shared_drives)
    logger.info(
        "Searching local Google Drive at %s (%s) with %d thread%s",
        mount, ", ".join(r.name for r in roots), threads, "" if threads == 1 else "s",
    )

    results: list[dict[str, Any]] = []
    folders_scanned = files_seen = unreadable = 0
    started = clock()
    executor = ThreadPoolExecutor(max_workers=threads, thread_name_prefix="drive-scan")
    try:
        pending: set[Future[_FolderResult]] = {
            executor.submit(_scan_folder, root, criteria, start_ts, end_ts) for root in roots
        }
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                found = future.result()
                folders_scanned += found.listed
                files_seen += found.files_seen
                unreadable += found.unreadable
                results.extend(found.matches)
                for sub in found.subfolders:
                    pending.add(executor.submit(_scan_folder, sub, criteria, start_ts, end_ts))
    finally:
        # On Ctrl+C or an error, don't start queued folders; let running ones finish.
        executor.shutdown(wait=True, cancel_futures=True)

    # Stable, thread-independent order: newest first, then by path.
    results.sort(key=lambda f: f["localPath"])
    results.sort(key=lambda f: f["createdTime"], reverse=True)
    logger.info(
        "Scanned %d folders and %d files in %.1f s; %d matches",
        folders_scanned, files_seen, clock() - started, len(results),
    )
    if unreadable:
        logger.warning("%d folders or items couldn't be read and were skipped.", unreadable)
    return results
