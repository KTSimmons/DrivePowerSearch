from drive_search.paths import PathResolver
from fakes import FakeService, drive_file

FOLDERS = {
    "f1": {"id": "f1", "name": "Projects", "parents": ["root-id"]},
    "f2": {"id": "f2", "name": "2026", "parents": ["f1"]},
    "visible": {"id": "visible", "name": "Shared Folder", "parents": ["hidden"]},
    "d1": {"id": "d1", "name": "Team Drive", "driveId": "d1"},
    "f5": {"id": "f5", "name": "Docs", "parents": ["d1"], "driveId": "d1"},
    "loop1": {"id": "loop1", "name": "A", "parents": ["loop2"]},
    "loop2": {"id": "loop2", "name": "B", "parents": ["loop1"]},
}


def resolver():
    service = FakeService(folders=FOLDERS)
    return PathResolver(service, sleep=lambda s: None), service


def test_full_path_to_my_drive():
    r, _ = resolver()
    assert r.resolve(drive_file("x", "report.pdf", parents=["f2"])) == "My Drive/Projects/2026/report.pdf"


def test_file_in_root():
    r, _ = resolver()
    assert r.resolve(drive_file("x", "a.txt", parents=["root-id"])) == "My Drive/a.txt"


def test_folder_lookups_are_cached():
    r, service = resolver()
    r.resolve(drive_file("x", "one.pdf", parents=["f2"]))
    r.resolve(drive_file("y", "two.pdf", parents=["f2"]))
    calls = service.files_api.get_calls
    assert calls.count("f2") == 1
    assert calls.count("f1") == 1
    assert calls.count("root") == 1


def test_no_parents_means_shared_with_me():
    r, _ = resolver()
    assert r.resolve(drive_file("x", "a.txt", parents=[])) == "(shared with me)/a.txt"


def test_invisible_parent_means_shared_with_me():
    r, _ = resolver()
    assert r.resolve(drive_file("x", "a.txt", parents=["missing"])) == "(shared with me)/a.txt"


def test_partial_path_keeps_visible_folders():
    r, _ = resolver()
    assert r.resolve(drive_file("x", "a.txt", parents=["visible"])) == "(shared with me)/Shared Folder/a.txt"


def test_shared_drive_root():
    r, _ = resolver()
    assert r.resolve(drive_file("x", "a.txt", parents=["f5"])) == "Team Drive/Docs/a.txt"


def test_parent_cycle_terminates():
    r, _ = resolver()
    assert r.resolve(drive_file("x", "a.txt", parents=["loop1"])).startswith("(shared with me)/")
