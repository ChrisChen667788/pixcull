"""V14.7 error reporting unit tests.

Pin the redaction patterns + opt-in semantics so accidental future
edits can't quietly start shipping real user data.
"""

from __future__ import annotations

from pathlib import Path

from pixcull.error_reporting import (
    build_payload,
    endpoint,
    gather_recent_log,
    is_enabled,
    redact,
    submit_report,
)


# ---------------------------------------------------------------------------
# Opt-in semantics — defaults MUST be safe
# ---------------------------------------------------------------------------

def test_disabled_by_default():
    assert is_enabled({}) is False
    assert is_enabled({"error_reports_enabled": False}) is False


def test_endpoint_blank_by_default():
    assert endpoint({}) == ""
    assert endpoint({"error_reports_endpoint": "  "}) == ""


def test_submit_no_op_when_disabled(tmp_path):
    """Even if endpoint is set, disabled means nothing leaves the box."""
    cfg = {"error_reports_enabled": False,
           "error_reports_endpoint": "https://example.invalid/report"}
    out = submit_report(cfg, "13.0.0", tmp_path)
    assert out["sent"] is False
    assert out["payload"] is None
    assert out["message"] == "未开启错误上报"


def test_submit_dry_run_when_enabled_no_endpoint(tmp_path):
    """Enabled but no endpoint = dry run; user sees what WOULD ship."""
    cfg = {"error_reports_enabled": True}
    out = submit_report(cfg, "13.0.0", tmp_path)
    assert out["sent"] is False
    assert out["payload"] is not None
    assert out["payload"]["schema"] == "pixcull.error_report.v1"
    assert "dry run" in out["message"]


# ---------------------------------------------------------------------------
# Redaction — every pattern must catch its target
# ---------------------------------------------------------------------------

def test_redacts_macos_home_path():
    out = redact("Traceback at /Users/alice/Downloads/foo.py line 12")
    assert "/Users/alice" not in out
    assert "/Users/<redacted>" in out


def test_redacts_linux_home_path():
    out = redact("Crashed at /home/bob/code/pixcull/main.py")
    assert "/home/bob" not in out
    assert "/home/<redacted>" in out


def test_redacts_windows_home_path():
    out = redact(r"Failed at C:\Users\Charlie\AppData\foo.exe")
    assert r"C:\Users\Charlie" not in out
    assert r"C:\Users\<redacted>" in out


def test_redacts_deepseek_key():
    # Synthetic, runtime-assembled non-secret: no literal API key ever lands
    # in the repo (that would trip GitHub secret scanning).  Still exercises
    # the ``sk-...`` redaction rule end-to-end.
    fake = "sk-" + "0" * 32
    out = redact(f"DEEPSEEK_API_KEY={fake} failed")
    assert fake not in out
    assert "sk-***" in out


def test_redacts_bearer_token():
    out = redact("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc.def")
    assert "eyJhbGc" not in out
    assert "Bearer ***" in out


def test_redacts_huggingface_token():
    out = redact("export HF_TOKEN=hf_qWeRtYuIoPaSdFgHjKlZxCvBnM")
    assert "hf_qWeRtYuIo" not in out
    assert "hf_***" in out


def test_redacts_email():
    out = redact("Contact alice@example.com for help")
    assert "alice@example.com" not in out
    assert "<email>" in out


def test_redact_idempotent():
    """Re-redacting already-redacted text leaves it unchanged."""
    once = redact("/Users/alice/foo")
    twice = redact(once)
    assert once == twice


def test_redact_preserves_meaningful_content():
    """We should still see the traceback structure after redaction."""
    log = (
        "Traceback (most recent call last):\n"
        '  File "/Users/alice/code/foo.py", line 42, in bar\n'
        "    raise ValueError('bad input')\n"
        "ValueError: bad input"
    )
    out = redact(log)
    assert "Traceback" in out
    assert "ValueError" in out
    assert "bad input" in out
    assert "/Users/alice" not in out


# ---------------------------------------------------------------------------
# Log gathering — gracefully handles missing dir / no logs
# ---------------------------------------------------------------------------

def test_gather_log_returns_empty_when_dir_missing(tmp_path):
    out = gather_recent_log(tmp_path / "no-such-dir")
    assert out == ""


def test_gather_log_returns_empty_when_no_logs(tmp_path):
    out = gather_recent_log(tmp_path)
    assert out == ""


def test_gather_log_reads_most_recent_and_redacts(tmp_path):
    (tmp_path / "pixcull_2026-01-01.log").write_text(
        "old log /Users/oldperson/x\n", encoding="utf-8"
    )
    fresh = tmp_path / "pixcull_2026-05-08.log"
    fresh.write_text(
        "fresh log /Users/alice/foo\nLine 2\n", encoding="utf-8"
    )
    # Force the fresh one to be newer
    import os, time as t
    t.sleep(0.01)
    os.utime(fresh, None)
    out = gather_recent_log(tmp_path)
    assert "/Users/alice" not in out
    assert "/Users/<redacted>" in out
    assert "Line 2" in out
    assert "old log" not in out  # only most recent log is read


def test_gather_log_caps_lines(tmp_path):
    fresh = tmp_path / "pixcull_2026-05-08.log"
    fresh.write_text("\n".join(f"line {i}" for i in range(500)),
                     encoding="utf-8")
    out = gather_recent_log(tmp_path, max_lines=50)
    assert out.count("\n") <= 50  # at most 50 newlines = ≤50 lines


# ---------------------------------------------------------------------------
# Payload shape
# ---------------------------------------------------------------------------

def test_build_payload_shape(tmp_path):
    p = build_payload("13.0.0", tmp_path, reason="manual")
    assert p["schema"] == "pixcull.error_report.v1"
    assert p["app_version"] == "13.0.0"
    assert p["reason"] == "manual"
    assert "platform" in p
    assert "log_tail" in p
    assert isinstance(p["extra"], dict)


def test_build_payload_extra_passthrough(tmp_path):
    p = build_payload("13.0.0", tmp_path, extra={"feature": "rescorer"})
    assert p["extra"] == {"feature": "rescorer"}
