"""v2.1-P2-1 — tests for pixcull.io.raw_proxy."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from pixcull.io import raw_proxy as RP
from pixcull.io.video import FFmpegError

_HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def test_needs_proxy():
    assert RP.needs_proxy("A001.braw")
    assert RP.needs_proxy(Path("/x/clip.CRM"))
    assert RP.needs_proxy(".r3d")
    assert not RP.needs_proxy("clip.mp4")
    assert not RP.needs_proxy("clip.mov")


def test_recipe_raw():
    r = RP.raw_proxy_recipe(Path("/x/A001.braw"))
    assert r.needs_transcode is True
    assert "Blackmagic" in r.advice
    assert "proxy.mov" in r.suggested_cmd
    assert r.to_dict()["ext"] == ".braw"


def test_recipe_decodable():
    r = RP.raw_proxy_recipe(Path("/x/clip.mp4"))
    assert r.needs_transcode is False
    assert "prores_ks" in r.suggested_cmd


def test_make_proxy_raw_without_tool_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("PIXCULL_RAW_TRANSCODER", raising=False)
    braw = tmp_path / "A001.braw"
    braw.write_bytes(b"\x00" * 64)
    with pytest.raises(FFmpegError, match="RAW"):
        RP.make_proxy(braw, tmp_path / "out")


def test_make_proxy_raw_invokes_configured_tool(tmp_path):
    # A fake transcoder script that just writes the output file.
    braw = tmp_path / "A001.braw"
    braw.write_bytes(b"\x00" * 64)
    tool = tmp_path / "faketranscode.sh"
    tool.write_text('#!/bin/sh\ncp /dev/null "$2"\n')
    tool.chmod(0o755)
    out = RP.make_proxy(braw, tmp_path / "out", transcoder=str(tool))
    assert out.exists() and out.name == "A001.proxy.mov"


@pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg not installed")
def test_make_proxy_decodable_transcodes(tmp_path):
    src = tmp_path / "c.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=30",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)],
        check=True, capture_output=True, timeout=60)
    out = RP.make_proxy(src, tmp_path / "out")
    assert out.exists() and out.suffix == ".mov"
    # The proxy is ProRes.
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1",
        str(out)], capture_output=True, text=True, timeout=30)
    assert "prores" in probe.stdout
