"""Logging configuration for Drive Search.

This is the ONLY module that adds handlers or sets formats. Every other module
just does ``logger = logging.getLogger(__name__)``.

- File log: ``drive_search.log`` in the log folder (rotating, 1 MB x 5 backups).
- Console: stderr, WARNING+ by default, INFO+ with ``verbose=True``.
  Tracebacks go to the file only.
- Log folder: created on first run and checked for write access on every run,
  with a fallback folder and finally console-only logging. A logging problem
  never stops a search.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE_NAME = "drive_search.log"
FALLBACK_APP_DIR = "DriveSearch"

FILE_FORMAT = "%(asctime)s | %(levelname)s | run=%(run_id)s | %(name)s | %(message)s"
CONSOLE_FORMAT = "%(levelname)s: %(message)s"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 5
VALID_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

# Third-party loggers kept at WARNING: they are noisy and, at DEBUG, can echo
# request details we don't want in the log.
QUIET_LOGGERS = (
    "googleapiclient",
    "google",
    "google_auth_oauthlib",
    "oauthlib",
    "requests_oauthlib",
    "urllib3",
)

_HANDLER_TAG = "_drive_search_handler"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoggingInfo:
    """What ``setup_logging`` actually set up."""

    run_id: str
    log_dir: Path | None  # None means console-only logging
    created_log_dir: bool = False

    @property
    def log_file(self) -> Path | None:
        return self.log_dir / LOG_FILE_NAME if self.log_dir else None

    def describe_location(self) -> str:
        """Where to look for details, for use in error messages."""
        return str(self.log_file) if self.log_file else "the console output above"


class _RunIdFilter(logging.Filter):
    """Stamps every record passing through a handler with the run ID."""

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = self.run_id
        return True


class _LocalIsoFormatter(logging.Formatter):
    """Local ISO 8601 timestamps with milliseconds and UTC offset."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return datetime.fromtimestamp(record.created).astimezone().isoformat(timespec="milliseconds")


class _NoTracebackFormatter(logging.Formatter):
    """Console formatter that leaves out tracebacks (they go to the file)."""

    def format(self, record: logging.LogRecord) -> str:
        clean = logging.makeLogRecord(record.__dict__)
        clean.exc_info = None
        clean.exc_text = None
        clean.stack_info = None
        return super().format(clean)


def fallback_log_dir() -> Path:
    """User-writable log folder used when the main one can't be used."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / FALLBACK_APP_DIR / "logs"
    return Path.home() / ".drive_search" / "logs"


def prepare_log_dir(path: Path) -> bool:
    """Create ``path`` if needed and prove it is writable.

    Returns True if the folder was created by this call. Raises OSError if the
    folder can't be created or written to.
    """
    existed = path.is_dir()
    path.mkdir(parents=True, exist_ok=True)
    probe = path / f".write_test_{uuid.uuid4().hex}.tmp"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()
    return not existed


def shutdown_logging() -> None:
    """Remove and close the handlers added by ``setup_logging``."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_TAG, False):
            root.removeHandler(handler)
            handler.close()


def _tag(handler: logging.Handler, run_filter: logging.Filter) -> logging.Handler:
    setattr(handler, _HANDLER_TAG, True)
    handler.addFilter(run_filter)
    return handler


def setup_logging(
    level: str = "INFO",
    log_dir: str | os.PathLike[str] | None = None,
    verbose: bool = False,
) -> LoggingInfo:
    """Configure logging for one run. Call once, at program start.

    Args:
        level: File log level: DEBUG, INFO, WARNING or ERROR.
        log_dir: Log folder. ``None`` means ``<project>/logs``.
        verbose: Also show INFO messages on the console.

    Returns:
        LoggingInfo with the run ID and the log folder actually in use.
    """
    level_name = level.upper()
    if level_name not in VALID_LEVELS:
        raise ValueError(f"Invalid log level {level!r}; use one of {', '.join(VALID_LEVELS)}")

    shutdown_logging()
    file_level = getattr(logging, level_name)
    console_level = logging.INFO if verbose else logging.WARNING
    run_id = uuid.uuid4().hex[:8]
    run_filter = _RunIdFilter(run_id)

    root = logging.getLogger()
    root.setLevel(min(file_level, console_level))
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    console = _tag(logging.StreamHandler(sys.stderr), run_filter)
    console.setLevel(console_level)
    console.setFormatter(_NoTracebackFormatter(CONSOLE_FORMAT))
    root.addHandler(console)

    # Messages are held until handlers exist, then logged (spec step 6).
    warnings: list[str] = []
    requested = Path(log_dir).expanduser().resolve() if log_dir else DEFAULT_LOG_DIR
    chosen: Path | None = None
    created = False
    for candidate in (requested, fallback_log_dir()):
        try:
            created = prepare_log_dir(candidate)
            chosen = candidate
            break
        except OSError as exc:
            warnings.append(f"Log folder {candidate} is not usable ({exc.__class__.__name__}: {exc}).")

    if chosen is not None:
        try:
            file_handler = logging.handlers.RotatingFileHandler(
                chosen / LOG_FILE_NAME, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
            )
        except OSError as exc:
            warnings.append(f"Could not open log file in {chosen} ({exc.__class__.__name__}: {exc}).")
            chosen = None
        else:
            _tag(file_handler, run_filter)
            file_handler.setLevel(file_level)
            file_handler.setFormatter(_LocalIsoFormatter(FILE_FORMAT))
            root.addHandler(file_handler)

    for message in warnings:
        logger.warning(message)
    if chosen is None:
        logger.warning("File logging is off for this run; log messages go to the console only.")
    else:
        if chosen != requested:
            logger.warning("Using fallback log folder %s.", chosen)
        if created:
            logger.info("Created log folder at %s", chosen)
        logger.info("Logging to %s", chosen / LOG_FILE_NAME)

    return LoggingInfo(run_id=run_id, log_dir=chosen, created_log_dir=created and chosen is not None)
