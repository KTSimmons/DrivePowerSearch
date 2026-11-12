"""Local Google Drive for desktop source, tested against a temporary fake mount."""

import os
from datetime import date, timedelta
from pathlib import Path

import pytest

from drive_search import local_search
from drive_search.local_search import (
    LocalDriveError,
    find_drive_mount as real_find_drive_mount,  # imported before conftest patches the module attribute
    resolve_mount,
    search_local,
)
from drive_search.search import SearchCriteria

TODAY = date.today()


@pytest.fixture
def mount(tmp_path):
    """A fake G:\\ with My Drive, Shared drives and the internal folders to skip."""
    root = tmp_path / "G"
    files = [
        "My Drive/Budget 2026.xlsx",
        "My Drive/Projects/2026/annual_report.pdf",
        "My Drive/Projects/notes.gdoc",
        "My Drive/old-budget-draft.txt",
        "My Drive/.shortcut-targets-by-id/abc/budget_shortcut.pdf",
        "My Drive/$RECYCLE.BIN/deleted_budget.txt",
        "Shared drives/Team/Budget plan.docx",
        ".Encrypted/budget_secret.bin",
    ]
    for rel in files:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    (root / "My Drive" / "Budgets folder").mkdir()
    return root


def names(results):
    return sorted(r["name"] for r in results)


def test_contains_is_case_insensitive_substring_and_recursive(mount):
    found = search_local(mount, SearchCriteria(name="BUDGET"))
    assert names(found) == ["Budget 2026.xlsx", "Budgets folder", "old-budget-draft.txt"]


def test_true_substring_not_just_word_prefix(mount):
    assert names(search_local(mount, SearchCriteria(name="dget"))) == [
        "Budget 2026.xlsx", "Budgets folder", "old-budget-draft.txt"
    ]


def test_finds_files_in_nested_folders(mount):
    assert names(search_local(mount, SearchCriteria(name="report"))) == ["annual_report.pdf"]


def test_skips_hidden_internal_and_bin_folders(mount):
    found = names(search_local(mount, SearchCriteria(name="budget", include_shared_drives=True)))
    assert "budget_shortcut.pdf" not in found
    assert "deleted_budget.txt" not in found
    assert "budget_secret.bin" not in found


def test_shared_drives_only_when_asked(mount):
    assert "Budget plan.docx" not in names(search_local(mount, SearchCriteria(name="plan")))
    assert names(search_local(mount, SearchCriteria(name="plan", include_shared_drives=True))) == ["Budget plan.docx"]


def test_exact_is_case_sensitive_and_needs_extension(mount):
    assert names(search_local(mount, SearchCriteria(name="notes.gdoc", exact=True))) == ["notes.gdoc"]
    assert search_local(mount, SearchCriteria(name="notes", exact=True)) == []
    assert search_local(mount, SearchCriteria(name="NOTES.GDOC", exact=True)) == []


def test_date_filters_use_creation_time(mount):
    # The fake files were all created just now.
    assert len(search_local(mount, SearchCriteria(name="budget", created_on=TODAY))) == 3
    assert search_local(mount, SearchCriteria(name="budget", created_on=TODAY - timedelta(days=1))) == []
    assert search_local(mount, SearchCriteria(name="budget", created_before=TODAY - timedelta(days=1))) == []
    assert len(search_local(mount, SearchCriteria(name="budget", created_after=TODAY))) == 3


def test_result_shape_path_and_link(mount):
    (result,) = search_local(mount, SearchCriteria(name="annual"))
    expected = mount / "My Drive" / "Projects" / "2026" / "annual_report.pdf"
    assert result["localPath"] == str(expected)
    assert result["webViewLink"] == expected.as_uri()
    assert result["webViewLink"].startswith("file:///")
    assert result["createdTime"].endswith("Z") and result["modifiedTime"].endswith("Z")


def test_unreadable_folder_is_skipped_not_fatal(mount, monkeypatch, caplog):
    real_scandir = os.scandir
    blocked = str(mount / "My Drive" / "Projects")

    def fake_scandir(path):
        if str(path) == blocked:
            raise PermissionError(13, "Access is denied")
        return real_scandir(path)

    monkeypatch.setattr(local_search.os, "scandir", fake_scandir)
    found = names(search_local(mount, SearchCriteria(name="budget")))
    assert "Budget 2026.xlsx" in found
    assert "couldn't be read" in caplog.text


def test_info_log_has_counts_not_file_names(mount, caplog):
    caplog.set_level("INFO", logger="drive_search.local_search")
    search_local(mount, SearchCriteria(name="annual"))
    info_text = " ".join(r.getMessage() for r in caplog.records if r.levelname == "INFO")
    assert "1 matches" in info_text
    assert "annual_report.pdf" not in info_text


class TestFindingTheMount:
    def test_env_override_accepts_mount_root_or_my_drive(self, mount):
        assert real_find_drive_mount(env={"GDRIVE_LOCAL_ROOT": str(mount)}, letters=[]) == mount
        assert real_find_drive_mount(env={"GDRIVE_LOCAL_ROOT": str(mount / "My Drive")}, letters=[]) == mount

    def test_env_override_without_my_drive_is_ignored(self, tmp_path):
        assert real_find_drive_mount(env={"GDRIVE_LOCAL_ROOT": str(tmp_path)}, letters=[]) is None

    def test_nothing_found(self):
        assert real_find_drive_mount(env={}, letters=[]) is None

    def test_explicit_drive_root(self, mount):
        assert resolve_mount(str(mount)) == mount

    def test_bad_explicit_drive_root_raises(self, tmp_path):
        with pytest.raises(LocalDriveError, match="My Drive"):
            resolve_mount(str(tmp_path))

    def test_no_explicit_root_falls_back_to_detection(self):
        assert resolve_mount(None) is None  # conftest hides any real mount


# --- Parallel scanning (spec 1.5.0) -------------------------------------------

@pytest.fixture
def wide_mount(tmp_path):
    """Many folders, so several threads really run at once."""
    root = tmp_path / "W"
    for a in range(6):
        for b in range(5):
            folder = root / "My Drive" / f"dir{a}" / f"sub{b}"
            folder.mkdir(parents=True)
            (folder / f"match_{a}_{b}.txt").write_text("x", encoding="utf-8")
            (folder / f"other_{a}_{b}.txt").write_text("x", encoding="utf-8")
    return root


@pytest.mark.parametrize("name", ["match", "budget", "dget", "report"])
def test_results_identical_for_any_thread_count(mount, wide_mount, name):
    for root in (mount, wide_mount):
        criteria = SearchCriteria(name=name, include_shared_drives=True)
        baseline = search_local(root, criteria, threads=1)
        for threads in (2, 5, 10):
            assert search_local(root, criteria, threads=threads) == baseline


def test_parallel_scan_finds_everything(wide_mount):
    found = search_local(wide_mount, SearchCriteria(name="match"), threads=10)
    assert len(found) == 30


def test_threads_really_run_in_parallel(wide_mount, monkeypatch):
    import threading
    import time as _time

    real = local_search._scan_folder
    active = 0
    peak = 0
    lock = threading.Lock()

    def slow_scan(*args):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        _time.sleep(0.02)  # stand-in for a slow Drive for desktop listing
        try:
            return real(*args)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(local_search, "_scan_folder", slow_scan)
    search_local(wide_mount, SearchCriteria(name="match"), threads=10)
    assert 2 <= peak <= 10


@pytest.mark.parametrize("bad", [0, 11, -1])
def test_thread_count_out_of_range(mount, bad):
    with pytest.raises(ValueError, match="between 1 and 10"):
        search_local(mount, SearchCriteria(name="x"), threads=bad)


def test_unreadable_folder_with_threads(mount, monkeypatch, caplog):
    real_scandir = os.scandir
    blocked = str(mount / "My Drive" / "Projects")
    monkeypatch.setattr(
        local_search.os, "scandir",
        lambda p: (_ for _ in ()).throw(PermissionError(13, "denied")) if str(p) == blocked else real_scandir(p),
    )
    found = names(search_local(mount, SearchCriteria(name="budget"), threads=10))
    assert "Budget 2026.xlsx" in found and "couldn't be read" in caplog.text
