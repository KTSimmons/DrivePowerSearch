import io
from datetime import datetime, timedelta, timezone

import pytest
from rich.console import Console

from drive_search.reports import (
    NO_RESULTS,
    Report,
    ReportWriteError,
    ResultRow,
    parse_drive_time,
    render_html,
    render_markdown,
    render_terminal,
    save_reports,
)

RUN_AT = datetime(2026, 11, 10, 14, 32, 5, tzinfo=timezone(timedelta(hours=-5)))
TERMS = [("Name", "budget"), ("Match", "contains (case-insensitive)")]


def row(name="budget.xlsx", path="My Drive/Finance/budget.xlsx", link="https://drive.google.com/file/d/abc/view"):
    return ResultRow(
        name=name,
        created=parse_drive_time("2026-03-01T10:00:00.000Z"),
        modified=parse_drive_time("2026-03-02T11:30:00Z"),
        path=path,
        link=link,
    )


def report(rows=None):
    return Report(search_terms=TERMS, run_at=RUN_AT, rows=[row()] if rows is None else rows)


def terminal_text(rep):
    buffer = io.StringIO()
    render_terminal(rep, Console(file=buffer, width=200, color_system=None))
    return buffer.getvalue()


class TestMarkdown:
    def test_header_and_counts(self):
        md = render_markdown(report())
        assert md.startswith("# Google Drive Search Report")
        assert "**Report run:** 2026-11-10T14:32:05-05:00" in md
        assert "**Files found:** 1" in md
        assert "| Name | budget |" in md
        assert "| File name | Created | Modified | Full path |" in md

    def test_pipe_in_name_is_escaped(self):
        md = render_markdown(report([row(name="a|b.txt")]))
        assert "a\\|b.txt" in md

    def test_no_results(self):
        md = render_markdown(report([]))
        assert NO_RESULTS in md
        assert "| File name |" not in md


class TestHtml:
    def test_path_is_clickable_in_new_tab(self):
        page = render_html(report())
        assert (
            '<a href="https://drive.google.com/file/d/abc/view" target="_blank" '
            'rel="noopener noreferrer">My Drive/Finance/budget.xlsx</a>'
        ) in page

    def test_values_are_escaped(self):
        page = render_html(report([row(name="<script>alert(1)</script>.txt")]))
        assert "&lt;script&gt;alert(1)&lt;/script&gt;.txt" in page
        assert "<script>alert" not in page

    def test_non_https_link_is_not_clickable(self):
        page = render_html(report([row(link="javascript:alert(1)")]))
        assert "javascript:" not in page

    def test_local_file_link_is_clickable(self):
        page = render_html(report([row(path="G:\\My Drive\\a b.txt", link="file:///G:/My%20Drive/a%20b.txt")]))
        assert '<a href="file:///G:/My%20Drive/a%20b.txt" target="_blank"' in page
        assert "G:\\My Drive\\a b.txt</a>" in page

    def test_self_contained(self):
        page = render_html(report())
        assert "<link" not in page
        assert "<script" not in page
        assert "<style>" in page

    def test_no_results(self):
        page = render_html(report([]))
        assert NO_RESULTS in page
        assert "<th>File name</th>" not in page


def test_all_outputs_show_the_same_information():
    rep = report([row(), row(name="plan [draft].docx", path="My Drive/plan [draft].docx")])
    outputs = [render_markdown(rep), render_html(rep), terminal_text(rep)]
    for text in outputs:
        assert "Google Drive Search Report" in text
        assert "2026-11-10T14:32:05-05:00" in text
        assert "budget.xlsx" in text
        assert "plan [draft].docx" in text  # brackets survive rich markup
        assert "budget" in text and "contains (case-insensitive)" in text
    assert "Files found: 2" in outputs[2]


def test_terminal_no_results():
    assert NO_RESULTS in terminal_text(report([]))


class TestSave:
    def test_two_runs_never_overwrite(self, tmp_path):
        first = save_reports(report(), tmp_path / "out")
        second = save_reports(report(), tmp_path / "out")
        assert first[0].name == "drive_search_20261110_143205.md"
        assert second[0].name == "drive_search_20261110_143205_2.md"
        assert len(list((tmp_path / "out").iterdir())) == 4
        assert first[1].read_text(encoding="utf-8").startswith("<!doctype html>")

    def test_unwritable_folder_raises_friendly_error(self, tmp_path):
        blocker = tmp_path / "not_a_folder"
        blocker.write_text("x")
        with pytest.raises(ReportWriteError, match="Could not write reports"):
            save_reports(report(), blocker)
