from datetime import date, datetime, timezone

import pytest

from drive_search.search import (
    DriveSearchError,
    SearchCriteria,
    build_query,
    created_range,
    escape_query_value,
    search_files,
)
from fakes import FakeService, drive_file, make_http_error


def local_midnight_utc(y, m, d):
    return datetime(y, m, d).astimezone().astimezone(timezone.utc)


class TestBuildQuery:
    def test_contains_by_default(self):
        assert build_query(SearchCriteria(name="budget")) == "name contains 'budget' and trashed = false"

    def test_exact(self):
        assert build_query(SearchCriteria(name="Budget.xlsx", exact=True)).startswith("name = 'Budget.xlsx'")

    def test_escapes_quotes_and_backslashes(self):
        assert escape_query_value("Bob's \\ file") == "Bob\\'s \\\\ file"
        assert "name contains 'Bob\\'s'" in build_query(SearchCriteria(name="Bob's"))

    def test_created_on_is_one_local_day(self):
        criteria = SearchCriteria(name="x", created_on=date(2026, 3, 8))
        start, end = created_range(criteria)
        assert start == local_midnight_utc(2026, 3, 8)
        assert end == local_midnight_utc(2026, 3, 9)
        query = build_query(criteria)
        assert f"createdTime >= '{start:%Y-%m-%dT%H:%M:%SZ}'" in query
        assert f"createdTime < '{end:%Y-%m-%dT%H:%M:%SZ}'" in query

    def test_range_is_inclusive(self):
        start, end = created_range(SearchCriteria(name="x", created_after=date(2026, 1, 1), created_before=date(2026, 1, 31)))
        assert start == local_midnight_utc(2026, 1, 1)
        assert end == local_midnight_utc(2026, 2, 1)  # end of Jan 31

    def test_open_ended_ranges(self):
        assert created_range(SearchCriteria(name="x", created_after=date(2026, 1, 1)))[1] is None
        assert created_range(SearchCriteria(name="x", created_before=date(2026, 1, 1)))[0] is None
        assert "createdTime" not in build_query(SearchCriteria(name="x"))


class TestSearchFiles:
    def test_follows_every_page(self):
        service = FakeService(pages=[
            {"files": [drive_file("a", "a.txt"), drive_file("b", "b.txt")], "nextPageToken": "t1"},
            {"files": [drive_file("c", "c.txt")]},
        ])
        result = search_files(service, SearchCriteria(name="txt"))
        assert {f["id"] for f in result} == {"a", "b", "c"}
        calls = service.files_api.list_calls
        assert len(calls) == 2
        assert "pageToken" not in calls[0]
        assert calls[1]["pageToken"] == "t1"
        assert "trashed = false" in calls[0]["q"]

    def test_sorted_newest_first(self):
        service = FakeService(pages=[{"files": [
            drive_file("old", "old", created="2025-01-01T00:00:00.000Z"),
            drive_file("new", "new", created="2026-06-01T00:00:00.000Z"),
            drive_file("mid", "mid", created="2025-09-01T00:00:00.000Z"),
        ]}])
        assert [f["id"] for f in search_files(service, SearchCriteria(name="x"))] == ["new", "mid", "old"]

    def test_exact_match_is_case_sensitive(self):
        service = FakeService(pages=[{"files": [drive_file("1", "budget.xlsx"), drive_file("2", "Budget.xlsx")]}])
        result = search_files(service, SearchCriteria(name="Budget.xlsx", exact=True))
        assert [f["id"] for f in result] == ["2"]

    def test_shared_drive_params_only_when_asked(self):
        service = FakeService(pages=[{"files": []}, {"files": []}])
        search_files(service, SearchCriteria(name="x"))
        search_files(service, SearchCriteria(name="x", include_shared_drives=True))
        default_call, shared_call = service.files_api.list_calls
        assert "corpora" not in default_call
        assert shared_call["corpora"] == "allDrives"
        assert shared_call["includeItemsFromAllDrives"] is True
        assert shared_call["supportsAllDrives"] is True

    def test_retries_rate_limit_then_succeeds(self):
        sleeps = []
        service = FakeService(pages=[[make_http_error(429), {"files": [drive_file("a", "a")]}]])
        result = search_files(service, SearchCriteria(name="a"), sleep=sleeps.append)
        assert len(result) == 1
        assert len(sleeps) == 1

    def test_retries_403_rate_limit_reason(self):
        sleeps = []
        service = FakeService(pages=[[make_http_error(403, "userRateLimitExceeded"), {"files": []}]])
        search_files(service, SearchCriteria(name="a"), sleep=sleeps.append)
        assert len(sleeps) == 1

    def test_403_permission_error_is_not_retried(self):
        sleeps = []
        service = FakeService(pages=[[make_http_error(403, "insufficientPermissions")]])
        with pytest.raises(DriveSearchError, match="HTTP 403"):
            search_files(service, SearchCriteria(name="a"), sleep=sleeps.append)
        assert sleeps == []

    def test_gives_up_after_max_retries(self):
        sleeps = []
        service = FakeService(pages=[[make_http_error(503)] * 10])
        with pytest.raises(DriveSearchError, match="after 5 retries"):
            search_files(service, SearchCriteria(name="a"), sleep=sleeps.append)
        assert len(sleeps) == 5

    def test_network_error_is_retried(self):
        sleeps = []
        service = FakeService(pages=[[ConnectionResetError("reset"), {"files": []}]])
        search_files(service, SearchCriteria(name="a"), sleep=sleeps.append)
        assert len(sleeps) == 1
