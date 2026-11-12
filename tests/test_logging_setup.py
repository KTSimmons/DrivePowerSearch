import logging
import re

import pytest

from drive_search import logging_setup
from drive_search.logging_setup import LOG_FILE_NAME, setup_logging, shutdown_logging

LINE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2} \| INFO \| run=[0-9a-f]{8} \| \S+ \| .+$"
)


def read_log(folder):
    return (folder / LOG_FILE_NAME).read_text(encoding="utf-8")


def test_first_run_creates_missing_nested_folder(tmp_path):
    target = tmp_path / "a" / "b" / "logs"
    info = setup_logging(log_dir=target)
    assert target.is_dir()
    assert info.created_log_dir and info.log_dir == target
    assert f"Created log folder at {target}" in read_log(target)


def test_line_format_and_run_id(tmp_path):
    info = setup_logging(log_dir=tmp_path)
    logging.getLogger("drive_search.test").info("hello")
    lines = read_log(tmp_path).splitlines()
    assert lines and all(LINE.match(line) for line in lines)
    assert all(f"run={info.run_id}" in line for line in lines)


def test_second_run_reuses_folder_and_appends(tmp_path):
    first = setup_logging(log_dir=tmp_path)
    shutdown_logging()
    second = setup_logging(log_dir=tmp_path)
    assert not second.created_log_dir
    assert first.run_id != second.run_id
    log = read_log(tmp_path)
    assert f"run={first.run_id}" in log and f"run={second.run_id}" in log


def _failing_for(bad_paths):
    real = logging_setup.prepare_log_dir

    def fake(path):
        if any(path == p for p in bad_paths):
            raise PermissionError(13, "Access is denied")
        return real(path)

    return fake


def test_unusable_folder_switches_to_fallback(tmp_path, monkeypatch, capsys):
    primary, fallback = tmp_path / "readonly_logs", tmp_path / "fallback"
    primary.mkdir()
    monkeypatch.setattr(logging_setup, "fallback_log_dir", lambda: fallback)
    monkeypatch.setattr(logging_setup, "prepare_log_dir", _failing_for([primary]))
    info = setup_logging(log_dir=primary)
    assert info.log_dir == fallback
    err = capsys.readouterr().err
    assert str(primary) in err and str(fallback) in err


def test_both_folders_failing_falls_back_to_console(tmp_path, monkeypatch, capsys):
    primary, fallback = tmp_path / "p", tmp_path / "f"
    monkeypatch.setattr(logging_setup, "fallback_log_dir", lambda: fallback)
    monkeypatch.setattr(logging_setup, "prepare_log_dir", _failing_for([primary, fallback]))
    info = setup_logging(log_dir=primary)
    assert info.log_dir is None and info.log_file is None
    logging.getLogger("drive_search.test").warning("still working")
    err = capsys.readouterr().err
    assert "console only" in err and "still working" in err


@pytest.mark.parametrize("verbose, shown", [(False, False), (True, True)])
def test_console_respects_verbose(tmp_path, capsys, verbose, shown):
    setup_logging(log_dir=tmp_path, verbose=verbose)
    logging.getLogger("drive_search.test").info("info-message")
    assert ("info-message" in capsys.readouterr().err) is shown
    assert "info-message" in read_log(tmp_path)  # file always gets INFO


def test_traceback_goes_to_file_not_console(tmp_path, capsys):
    setup_logging(log_dir=tmp_path)
    try:
        raise ValueError("kaboom")
    except ValueError:
        logging.getLogger("drive_search.test").exception("Something failed")
    err = capsys.readouterr().err
    assert "Something failed" in err and "Traceback" not in err
    assert "Traceback" in read_log(tmp_path)


def test_invalid_level_rejected():
    with pytest.raises(ValueError):
        setup_logging(level="CHATTY")
