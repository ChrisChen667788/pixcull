"""v3.15 — the tether verdict reaches the application the photographer is
looking at.

This is the block's clearest instance of the defect this repository keeps
finding.  `decision_to_xmp` has mapped keep/maybe/cull to 5/3/1 stars and
Green/Yellow/Red since V29, and its own docstring says Capture One
renders those as coloured borders in the browser.  `tether.py` analysed
every frame as it landed, appended a row, and never once called it.

So a live tether session produced verdicts that existed only inside
PixCull's own window — while the photographer spent the shoot looking at
Lightroom or Capture One.  Both Capture One's Assisted Review and Meitu's
iPad import put the first verdict in front of the photographer at capture
time; PixCull had every piece needed and had not connected them.
"""
import inspect
import tempfile
from pathlib import Path

from pixcull import tether


class _Session(tether.TetherSession):
    """A session with the polling loop and analysis stubbed out."""
    def __init__(self, tmp):
        self.n_analyzed = 0
        self.n_failed = 0
        self.n_sidecars = 0
        self.n_sidecar_failed = 0
        self._tmp = Path(tmp)


def test_the_verdict_becomes_a_sidecar_the_host_can_render(monkeypatch):
    monkeypatch.setenv(tether.TetherSession.SIDECAR_ENV, "1")
    with tempfile.TemporaryDirectory() as d:
        img = Path(d) / "DSC_0001.NEF"
        img.write_bytes(b"\xff\xd8\xff")
        s = _Session(d)
        s._write_sidecar(img, {"filename": "DSC_0001.NEF", "decision": "keep"})
        side = img.with_suffix(".xmp")
        assert side.exists(), "no sidecar next to the frame"
        text = side.read_text(encoding="utf-8")
        assert "<xmp:Rating>5</xmp:Rating>" in text
        assert "Green" in text
        assert s.n_sidecars == 1


def test_a_cull_lands_as_red_and_one_star(monkeypatch):
    monkeypatch.setenv(tether.TetherSession.SIDECAR_ENV, "1")
    with tempfile.TemporaryDirectory() as d:
        img = Path(d) / "DSC_0002.NEF"
        img.write_bytes(b"\xff\xd8\xff")
        s = _Session(d)
        s._write_sidecar(img, {"filename": "DSC_0002.NEF", "decision": "cull"})
        text = img.with_suffix(".xmp").read_text(encoding="utf-8")
        assert "<xmp:Rating>1</xmp:Rating>" in text and "Red" in text


def test_nothing_is_written_unless_the_photographer_opted_in(monkeypatch):
    """The tether destination is a folder the host is actively importing
    from. Dropping files into it mid-import is a real collision risk."""
    monkeypatch.delenv(tether.TetherSession.SIDECAR_ENV, raising=False)
    with tempfile.TemporaryDirectory() as d:
        img = Path(d) / "DSC_0003.NEF"
        img.write_bytes(b"\xff\xd8\xff")
        s = _Session(d)
        s._write_sidecar(img, {"filename": "DSC_0003.NEF", "decision": "keep"})
        assert not img.with_suffix(".xmp").exists()
        assert s.n_sidecars == 0


def test_only_an_explicit_one_enables_it(monkeypatch):
    monkeypatch.setenv(tether.TetherSession.SIDECAR_ENV, "yes")
    with tempfile.TemporaryDirectory() as d:
        assert _Session(d)._sidecar_enabled() is False


def test_a_failed_write_does_not_cost_the_analysis(monkeypatch):
    """A locked file or a read-only card must not raise out of the poll
    loop and end the session."""
    monkeypatch.setenv(tether.TetherSession.SIDECAR_ENV, "1")
    with tempfile.TemporaryDirectory() as d:
        s = _Session(d)
        s._write_sidecar(Path(d) / "no" / "such" / "dir" / "x.NEF",
                         {"filename": "x.NEF", "decision": "keep"})
        assert s.n_sidecar_failed == 1
        assert s.n_sidecars == 0


def test_failures_are_counted_so_a_locked_folder_is_visible(monkeypatch):
    """A session that wrote nothing because the host held the folder must
    not look identical to one that was never asked to write any."""
    monkeypatch.setenv(tether.TetherSession.SIDECAR_ENV, "1")
    with tempfile.TemporaryDirectory() as d:
        s = _Session(d)
        for _ in range(3):
            s._write_sidecar(Path(d) / "nope" / "x.NEF",
                             {"filename": "x.NEF", "decision": "cull"})
        assert s.n_sidecar_failed == 3


def test_the_status_payload_reports_both_counts_and_the_setting():
    src = inspect.getsource(tether.TetherSession.status)
    assert '"n_sidecars"' in src
    assert '"n_sidecar_failed"' in src
    assert '"sidecars_enabled"' in src


def test_the_poll_loop_actually_calls_it():
    """The capability existing and never being reached is the defect this
    version exists to close. Assert the call site, not just the method."""
    src = inspect.getsource(tether)
    assert "self._write_sidecar(p, result)" in src
