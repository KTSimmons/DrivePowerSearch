"""Command-line interface: argument parsing, input checks, and turning
exceptions into friendly messages and exit codes.

Logging is set up first, before anything else (spec 1.3.0, "Log folder setup").
"""

from __future__ import annotations

import argparse
import logging
import platform
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

from rich.console import Console
from rich.text import Text

from drive_search import __version__, auth
from drive_search.auth import AuthError
from drive_search.logging_setup import VALID_LEVELS, LoggingInfo, setup_logging, shutdown_logging
from drive_search.paths import PathResolver
from drive_search.reports import Report, ReportWriteError, ResultRow, parse_drive_time, render_terminal, save_reports
from drive_search.search import DriveSearchError, SearchCriteria, search_files

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_USAGE = 2
EXIT_AUTH = 3
EXIT_DRIVE = 4
EXIT_OUTPUT = 5
EXIT_INTERRUPTED = 130

DEFAULT_OUTPUT_DIR = "./search_results"
NOT_SET = "(not set)"


def parse_date(text: str) -> date:
    """argparse type for YYYY-MM-DD dates."""
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' is not a valid date; use YYYY-MM-DD, for example 2026-11-10")


def _add_logging_args(parser: argparse.ArgumentParser, strict: bool) -> None:
    parser.add_argument(
        "--log-level",
        type=str.upper,
        default="INFO",
        choices=VALID_LEVELS if strict else None,
        help="Detail level for the log file (default: INFO)",
    )
    parser.add_argument("--log-dir", default=None, help="Log folder (default: logs/ next to the utility)")
    parser.add_argument("--verbose", action="store_true", help="Also show INFO log messages in the terminal")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m drive_search",
        description="Search Google Drive by file name and creation date, and save Markdown and HTML reports.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--name", required=True, help="Text to match against file names")
    parser.add_argument(
        "--exact", action="store_true", help="Match the whole name exactly (default: name contains TEXT, case-insensitive)"
    )
    parser.add_argument("--created-on", type=parse_date, metavar="YYYY-MM-DD", help="Only files created on this date")
    parser.add_argument("--created-after", type=parse_date, metavar="YYYY-MM-DD", help="Created on or after this date")
    parser.add_argument("--created-before", type=parse_date, metavar="YYYY-MM-DD", help="Created on or before this date")
    parser.add_argument("--include-shared-drives", action="store_true", help="Also search shared drives")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help=f"Report folder (default: {DEFAULT_OUTPUT_DIR})")
    _add_logging_args(parser, strict=True)
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Check combinations argparse can't. Calls ``parser.error`` (exit 2) on problems."""
    if not args.name.strip():
        parser.error("--name must not be empty")
    if args.created_on and (args.created_after or args.created_before):
        parser.error("--created-on can't be combined with --created-after or --created-before")
    if args.created_after and args.created_before and args.created_after > args.created_before:
        parser.error(
            f"--created-after ({args.created_after}) is later than --created-before ({args.created_before})"
        )


def _fmt(value: object) -> str:
    if value is None:
        return NOT_SET
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def search_terms(args: argparse.Namespace, info: LoggingInfo) -> list[tuple[str, str]]:
    """Every argument and its value, including defaults, for the report."""
    return [
        ("Name", args.name),
        ("Match", "exact (case-sensitive)" if args.exact else "contains (case-insensitive)"),
        ("Created on", _fmt(args.created_on)),
        ("Created after", _fmt(args.created_after)),
        ("Created before", _fmt(args.created_before)),
        ("Include shared drives", _fmt(args.include_shared_drives)),
        ("Output folder", str(Path(args.output_dir).expanduser().resolve())),
        ("Log level", args.log_level),
        ("Log folder", str(info.log_dir) if info.log_dir else "(console only)"),
        ("Verbose", _fmt(args.verbose)),
    ]


def _fail(info: LoggingInfo, message: str, exc: BaseException, code: int) -> int:
    # Console shows the message only; the traceback goes to the log file.
    logger.error("%s See %s for details.", message, info.describe_location(), exc_info=exc)
    return code


def _run(argv: Sequence[str], info: LoggingInfo) -> int:
    run_at = datetime.now().astimezone()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        validate_args(parser, args)
    except SystemExit as exc:  # argparse already printed its message (or --help/--version)
        code = exc.code if isinstance(exc.code, int) else EXIT_USAGE
        if code:
            logger.info("Invalid arguments; nothing searched.")
        return code

    terms = search_terms(args, info)
    logger.info("Search arguments: %s", "; ".join(f"{k}={v}" for k, v in terms))
    criteria = SearchCriteria(
        name=args.name,
        exact=args.exact,
        created_on=args.created_on,
        created_after=args.created_after,
        created_before=args.created_before,
        include_shared_drives=args.include_shared_drives,
    )
    console = Console()

    try:
        credentials = auth.get_credentials()
        service = auth.build_drive_service(credentials)
        files = search_files(service, criteria)
        resolver = PathResolver(service)
        rows = [
            ResultRow(
                name=f.get("name") or "(unnamed)",
                created=parse_drive_time(f.get("createdTime")),
                modified=parse_drive_time(f.get("modifiedTime")),
                path=resolver.resolve(f),
                link=f.get("webViewLink"),
            )
            for f in files
        ]
        report = Report(search_terms=terms, run_at=run_at, rows=rows)
        render_terminal(report, console)
        md_path, html_path = save_reports(report, args.output_dir)
    except AuthError as exc:
        return _fail(info, str(exc), exc, EXIT_AUTH)
    except DriveSearchError as exc:
        return _fail(info, str(exc), exc, EXIT_DRIVE)
    except ReportWriteError as exc:
        return _fail(info, str(exc), exc, EXIT_OUTPUT)
    except Exception as exc:
        return _fail(info, f"Unexpected error ({exc.__class__.__name__}).", exc, EXIT_UNEXPECTED)

    console.print(Text(f"Markdown report: {md_path}"))
    console.print(Text(f"HTML report:     {html_path}"))
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Run the utility. Returns the process exit code."""
    argv = list(sys.argv[1:] if argv is None else argv)

    # Read only the logging options first, so logging exists before anything else.
    pre = argparse.ArgumentParser(add_help=False)
    _add_logging_args(pre, strict=False)
    log_opts, _ = pre.parse_known_args(argv)
    level = log_opts.log_level if log_opts.log_level in VALID_LEVELS else "INFO"  # full parser reports bad values
    info = setup_logging(level=level, log_dir=log_opts.log_dir, verbose=log_opts.verbose)

    started = time.monotonic()
    logger.info("Drive Search %s starting (Python %s)", __version__, platform.python_version())
    code = EXIT_UNEXPECTED
    try:
        code = _run(argv, info)
    except KeyboardInterrupt:
        logger.warning("Cancelled by user.")
        code = EXIT_INTERRUPTED
    finally:
        logger.info("Finished with exit code %d in %.2f s", code, time.monotonic() - started)
        shutdown_logging()
    return code
