"""v2.37 — the ModelScope sync must not report success it didn't have.

Observed on the v2.36 publish: the run printed

    [modelscope-sync] ✓ hosted 20/28 referenced assets
    [modelscope-sync] ✓ synced haozi667788/pixcull#master

and exited 0.  Eight assets had failed with HTTP 429 "commit lock busy"
(a manual sync and the push-triggered CI workflow were fighting over the
same repo lock), so the published model card referenced eight images
that were not on the server — while the last line said it was synced.

Two fixes, both tested here: retry the transient failures, and make a
short count an actual non-zero failure.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "sync_modelscope_readme.py"


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch, sync):
    """Backoff is real seconds in production and pure waste in tests."""
    monkeypatch.setattr(sync.time, "sleep", lambda _s: None)


@pytest.fixture(scope="module")
def sync():
    spec = importlib.util.spec_from_file_location("ms_sync_test", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    sys.modules["ms_sync_test"] = m
    spec.loader.exec_module(m)
    return m


class _Api:
    """Stub HubApi. ``fail_times`` maps a path to how many times its
    upload should raise before succeeding."""

    def __init__(self, fail_times=None, always_fail=()):
        self.fail_times = dict(fail_times or {})
        self.always_fail = set(always_fail)
        self.calls = []

    def upload_file(self, *, path_or_fileobj, path_in_repo, **kw):
        self.calls.append(path_in_repo)
        if path_in_repo in self.always_fail:
            raise RuntimeError("HTTP 403 forbidden")
        left = self.fail_times.get(path_in_repo, 0)
        if left:
            self.fail_times[path_in_repo] = left - 1
            raise RuntimeError(
                "HTTP 429 error: {'Message': 'commit lock busy, please "
                "try again'}")


@pytest.fixture
def readme(tmp_path, sync, monkeypatch):
    """A README referencing three real files under a temp repo root."""
    docs = tmp_path / "docs" / "screenshots"
    docs.mkdir(parents=True)
    for i in (1, 2, 3):
        (docs / f"{i:02d}-shot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(sync, "REPO_ROOT", tmp_path)
    return "\n".join(
        f"![s](docs/screenshots/{i:02d}-shot.png)" for i in (1, 2, 3))


def test_all_uploads_ok_reports_full_count(sync, readme):
    api = _Api()
    n, expected, failed = sync._upload_referenced_assets(
        api, "x/y", "master", readme)
    assert (n, expected, failed) == (3, 3, [])


def test_transient_lock_busy_is_retried_not_reported(sync, readme):
    """429 'commit lock busy' is transient by definition — waiting fixes
    it, so it must not become a permanently missing asset."""
    api = _Api(fail_times={"docs/screenshots/02-shot.png": 2})
    n, expected, failed = sync._upload_referenced_assets(
        api, "x/y", "master", readme, attempts=4)
    assert failed == [], "a retryable failure was reported as permanent"
    assert n == expected == 3
    assert api.calls.count("docs/screenshots/02-shot.png") == 3


def test_permanent_failure_is_reported(sync, readme):
    api = _Api(always_fail={"docs/screenshots/03-shot.png"})
    n, expected, failed = sync._upload_referenced_assets(
        api, "x/y", "master", readme, attempts=2)
    assert failed == ["docs/screenshots/03-shot.png"]
    assert (n, expected) == (2, 3)


def test_non_transient_error_is_not_retried(sync, readme):
    """A 403 will never fix itself; burning retries on it just makes the
    failure slower to surface."""
    api = _Api(always_fail={"docs/screenshots/01-shot.png"})
    sync._upload_referenced_assets(api, "x/y", "master", readme, attempts=4)
    assert api.calls.count("docs/screenshots/01-shot.png") == 1


def test_exhausted_retries_give_up_and_report(sync, readme):
    api = _Api(fail_times={"docs/screenshots/01-shot.png": 99})
    n, expected, failed = sync._upload_referenced_assets(
        api, "x/y", "master", readme, attempts=3)
    assert failed == ["docs/screenshots/01-shot.png"]
    assert api.calls.count("docs/screenshots/01-shot.png") == 3


def test_missing_local_file_is_not_counted_as_expected(sync, tmp_path,
                                                       monkeypatch):
    """A README pointing at a file that isn't in the repo is a README
    bug, reported separately from an upload failure."""
    docs = tmp_path / "docs" / "screenshots"
    docs.mkdir(parents=True)
    (docs / "01-shot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(sync, "REPO_ROOT", tmp_path)
    text = ("![a](docs/screenshots/01-shot.png)\n"
            "![b](docs/screenshots/99-gone.png)")
    n, expected, failed = sync._upload_referenced_assets(
        _Api(), "x/y", "master", text)
    assert (n, expected, failed) == (1, 1, [])


def test_transient_classifier_covers_the_observed_message(sync):
    """The exact 429 body ModelScope returned during the v2.36 publish."""
    real = RuntimeError(
        "HTTP 429 error from https://www.modelscope.cn/api/v1/repos/models/"
        "x/y/commit/master: {'Code': 10030000001, 'Message': 'commit lock "
        "busy, please try again', 'Success': False}")
    assert sync._is_transient(real)
    assert not sync._is_transient(RuntimeError("HTTP 401 unauthorized"))


def test_main_returns_nonzero_when_assets_are_missing(sync, monkeypatch):
    """The regression that mattered: a half-published card exiting 0."""
    monkeypatch.setattr(sync, "_upload_referenced_assets",
                        lambda *a, **k: (20, 28, ["docs/screenshots/02.png"]))
    monkeypatch.setattr(sync, "_git_push_readme", lambda *a, **k: True)
    monkeypatch.setattr(sync, "_resolve_token", lambda *a, **k: "t")
    monkeypatch.setattr(sync, "README_SOURCE", SCRIPT)   # any readable file

    class _FakeApi:
        def login(self, *a, **k):
            pass

    monkeypatch.setitem(
        sys.modules, "modelscope.hub.api",
        type(sys)("modelscope.hub.api"))
    sys.modules["modelscope.hub.api"].HubApi = lambda *a, **k: _FakeApi()

    rc = sync.main([])
    assert rc != 0, (
        "sync reported success while 8 referenced assets were unhosted")
