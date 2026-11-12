"""Rendering the terminal, Markdown and HTML reports.

All three outputs show the same title, search terms, run timestamp, count and
rows. Every value from Drive is escaped for its output format.
"""

from __future__ import annotations

import html
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

logger = logging.getLogger(__name__)

TITLE = "Google Drive Search Report"
NO_RESULTS = "No files found"
COLUMNS = ("File name", "Created", "Modified", "Full path")


class ReportWriteError(Exception):
    """A report file could not be written."""


@dataclass(frozen=True)
class ResultRow:
    name: str
    created: datetime | None
    modified: datetime | None
    path: str
    link: str | None = None


@dataclass(frozen=True)
class Report:
    search_terms: list[tuple[str, str]]
    run_at: datetime  # timezone-aware, local
    rows: list[ResultRow] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.rows)


def parse_drive_time(value: str | None) -> datetime | None:
    """Parse a Drive RFC 3339 timestamp such as ``2026-11-10T19:32:05.123Z``."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_local(moment: datetime | None) -> str:
    return moment.astimezone().strftime("%Y-%m-%d %H:%M") if moment else ""


def format_run_time(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _cells(row: ResultRow) -> tuple[str, str, str, str]:
    return row.name, format_local(row.created), format_local(row.modified), row.path


# --- Terminal -----------------------------------------------------------------

def render_terminal(report: Report, console: Console | None = None) -> None:
    """Print the report as aligned tables. Values are Text objects, so names
    containing [brackets] are never treated as rich markup."""
    console = console or Console()
    console.print(Text(TITLE, style="bold"))
    console.print(Text(f"Report run:  {format_run_time(report.run_at)}"))
    console.print(Text(f"Files found: {report.count}"))

    terms = Table(title="Search terms", title_justify="left", show_header=True)
    terms.add_column("Term")
    terms.add_column("Value")
    for term, value in report.search_terms:
        terms.add_row(Text(term), Text(value))
    console.print(terms)

    if not report.rows:
        console.print(Text(NO_RESULTS, style="yellow"))
        return
    results = Table(title="Results", title_justify="left", show_header=True)
    results.add_column(COLUMNS[0], overflow="fold")
    results.add_column(COLUMNS[1], no_wrap=True)
    results.add_column(COLUMNS[2], no_wrap=True)
    results.add_column(COLUMNS[3], overflow="fold")  # long paths wrap to fit
    for row in report.rows:
        results.add_row(*(Text(cell) for cell in _cells(row)))
    console.print(results)


# --- Markdown -----------------------------------------------------------------

def _md(text: str) -> str:
    """Escape a value for a GitHub-flavored Markdown table cell."""
    return (
        text.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("<", "&lt;")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def render_markdown(report: Report) -> str:
    lines = [
        f"# {TITLE}",
        "",
        f"**Report run:** {format_run_time(report.run_at)}",
        "",
        f"**Files found:** {report.count}",
        "",
        "## Search terms",
        "",
        "| Term | Value |",
        "|---|---|",
    ]
    lines += [f"| {_md(term)} | {_md(value)} |" for term, value in report.search_terms]
    lines += ["", "## Results", ""]
    if report.rows:
        lines += ["| " + " | ".join(COLUMNS) + " |", "|---|---|---|---|"]
        lines += ["| " + " | ".join(_md(c) for c in _cells(row)) + " |" for row in report.rows]
    else:
        lines.append(NO_RESULTS)
    return "\n".join(lines) + "\n"


# --- HTML ---------------------------------------------------------------------

_CSS = """
:root { --bg:#ffffff; --fg:#1f2328; --muted:#59636e; --line:#d1d9e0; --head:#f6f8fa; --link:#0969da; --stripe:#fafbfc; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#0d1117; --fg:#e6edf3; --muted:#9198a1; --line:#3d444d; --head:#151b23; --link:#4493f8; --stripe:#11161d; }
}
body { background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; margin:0; padding:24px 16px; }
main { max-width:1100px; margin:0 auto; }
h1 { font-size:1.6rem; margin:0 0 .5rem; }
h2 { font-size:1.15rem; margin:1.75rem 0 .5rem; }
.meta { color:var(--muted); margin:.15rem 0; }
.table-wrap { overflow-x:auto; }
table { border-collapse:collapse; width:100%; }
th, td { border:1px solid var(--line); padding:6px 10px; text-align:left; vertical-align:top; }
th { background:var(--head); }
tr:nth-child(even) td { background:var(--stripe); }
td.nowrap { white-space:nowrap; }
td.path { word-break:break-all; }
a { color:var(--link); }
.empty { color:var(--muted); font-style:italic; }
""".strip()


def _h(text: str) -> str:
    return html.escape(text, quote=True)


def _path_cell(row: ResultRow) -> str:
    # Only real https Drive links become clickable (never javascript: etc.).
    if row.link and row.link.lower().startswith("https://"):
        return f'<a href="{_h(row.link)}" target="_blank" rel="noopener noreferrer">{_h(row.path)}</a>'
    return _h(row.path)


def render_html(report: Report) -> str:
    term_rows = "\n".join(f"<tr><td>{_h(t)}</td><td>{_h(v)}</td></tr>" for t, v in report.search_terms)
    if report.rows:
        body_rows = "\n".join(
            "<tr>"
            f"<td>{_h(row.name)}</td>"
            f'<td class="nowrap">{_h(format_local(row.created))}</td>'
            f'<td class="nowrap">{_h(format_local(row.modified))}</td>'
            f'<td class="path">{_path_cell(row)}</td>'
            "</tr>"
            for row in report.rows
        )
        header = "".join(f"<th>{_h(c)}</th>" for c in COLUMNS)
        results = f'<div class="table-wrap"><table>\n<thead><tr>{header}</tr></thead>\n<tbody>\n{body_rows}\n</tbody>\n</table></div>'
    else:
        results = f'<p class="empty">{_h(NO_RESULTS)}</p>'

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_h(TITLE)}</title>
<style>
{_CSS}
</style>
</head>
<body>
<main>
<h1>{_h(TITLE)}</h1>
<p class="meta"><strong>Report run:</strong> {_h(format_run_time(report.run_at))}</p>
<p class="meta"><strong>Files found:</strong> {report.count}</p>
<h2>Search terms</h2>
<div class="table-wrap"><table>
<thead><tr><th>Term</th><th>Value</th></tr></thead>
<tbody>
{term_rows}
</tbody>
</table></div>
<h2>Results</h2>
{results}
</main>
</body>
</html>
"""


# --- Saving -------------------------------------------------------------------

def save_reports(report: Report, output_dir: str | os.PathLike[str]) -> tuple[Path, Path]:
    """Write ``drive_search_<YYYYMMDD_HHMMSS>.md`` and ``.html``.

    Never overwrites an earlier report: adds ``_2``, ``_3``... if needed.
    Returns the absolute paths of the Markdown and HTML files.
    """
    folder = Path(output_dir).expanduser().resolve()
    stamp = report.run_at.strftime("%Y%m%d_%H%M%S")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        base = f"drive_search_{stamp}"
        suffix = 1
        while (folder / f"{base}.md").exists() or (folder / f"{base}.html").exists():
            suffix += 1
            base = f"drive_search_{stamp}_{suffix}"
        md_path = folder / f"{base}.md"
        html_path = folder / f"{base}.html"
        md_path.write_text(render_markdown(report), encoding="utf-8")
        html_path.write_text(render_html(report), encoding="utf-8")
    except OSError as exc:
        raise ReportWriteError(f"Could not write reports to {folder} ({exc.__class__.__name__}: {exc}).") from exc
    logger.info("Wrote Markdown report: %s", md_path)
    logger.info("Wrote HTML report: %s", html_path)
    return md_path, html_path
