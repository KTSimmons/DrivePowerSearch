"""A tiny fake of the Drive v3 service, enough for search and path tests."""

from __future__ import annotations

import json
from typing import Any

import httplib2
from googleapiclient.errors import HttpError


def make_http_error(status: int, reason: str = "testReason") -> HttpError:
    resp = httplib2.Response({"status": str(status)})
    content = json.dumps(
        {"error": {"code": status, "message": "test error", "errors": [{"reason": reason, "message": "test"}]}}
    ).encode("utf-8")
    return HttpError(resp, content)


class FakeRequest:
    """``outcome`` is a dict/exception, or a list of them consumed one per
    ``execute()`` call (the last one repeats)."""

    def __init__(self, outcome: Any) -> None:
        self._outcomes = list(outcome) if isinstance(outcome, list) else [outcome]

    def execute(self) -> Any:
        result = self._outcomes.pop(0) if len(self._outcomes) > 1 else self._outcomes[0]
        if isinstance(result, BaseException):
            raise result
        return result


class FakeFiles:
    def __init__(self, pages: list[Any], folders: dict[str, Any], root_id: str) -> None:
        self.pages = list(pages)
        self.folders = folders
        self.root_id = root_id
        self.list_calls: list[dict[str, Any]] = []
        self.get_calls: list[str] = []

    def list(self, **params: Any) -> FakeRequest:
        self.list_calls.append(dict(params))
        return FakeRequest(self.pages.pop(0))

    def get(self, fileId: str, **params: Any) -> FakeRequest:  # noqa: N803 (Drive API name)
        self.get_calls.append(fileId)
        if fileId == "root":
            return FakeRequest({"id": self.root_id})
        if fileId in self.folders:
            return FakeRequest(self.folders[fileId])
        return FakeRequest(make_http_error(404, "notFound"))


class FakeService:
    def __init__(self, pages: list[Any] | None = None, folders: dict[str, Any] | None = None, root_id: str = "root-id"):
        self.files_api = FakeFiles(pages or [{"files": []}], folders or {}, root_id)

    def files(self) -> FakeFiles:
        return self.files_api


def drive_file(file_id: str, name: str, created: str = "2026-03-01T10:00:00.000Z", parents: list[str] | None = None,
               modified: str = "2026-03-02T11:30:00.000Z") -> dict[str, Any]:
    return {
        "id": file_id,
        "name": name,
        "createdTime": created,
        "modifiedTime": modified,
        "parents": parents if parents is not None else ["root-id"],
        "webViewLink": f"https://drive.google.com/file/d/{file_id}/view",
    }
