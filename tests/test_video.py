"""v2.0-P0-1 — tests for pixcull.io.video (probe + extract + manifest).

These exercise the *real* ffmpeg / ffprobe binaries against tiny
synthetic clips generated on the fly via the lavfi ``testsrc`` source.
The whole module skips when ffmpeg/ffprobe aren't on PATH (so CI without
ffmpeg stays green), and individual codec cases skip when their encoder
isn't compiled into the local ffmpeg.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from pixcull.io import video as V

_HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))

pytestmark = pytest.mark.skipif(
    not _HAS_FFMPEG, reason="ffmpeg/ffprobe not installed"
)


# --------------------------------------------------------------------------
# Synthetic clip helpers
# --------------------------------------------------------------------------

def _encoder_available(encoder: str) -> bool:
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    return any(line.split()[1:2] == [encoder]
               for line in out.splitlines() if line.strip())


def _make_clip(
    dest: Path,
    *,
    vcodec: str = "libx264",
    duration: int = 4,
    rate: int = 30,
    with_audio: bool = True,
    extra: list[str] | None = None,
) -> Path:
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i",
        f"testsrc=duration={duration}:size=320x240:rate={rate}",
    ]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=1000:duration={duration}"]
    cmd += ["-c:v", vcodec]
    if vcodec in ("libx264", "libx265"):
        cmd += ["-pix_fmt", "yuv420p"]
    if vcodec == "prores_ks":
        cmd += ["-profile:v", "0"]
    if extra:
        cmd += extra
    if with_audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd += [str(dest)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    return dest


@pytest.fixture(scope="module")
def h264_clip(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("video_h264")
    return _make_clip(d / "clip.mp4", vcodec="libx264")


# --------------------------------------------------------------------------
# is_video / make_video_id
# --------------------------------------------------------------------------

def test_is_video_true_for_containers():
    assert V.is_video("clip.mp4")
    assert V.is_video("CLIP.MOV")
    assert V.is_video(".mkv")
    assert V.is_video(Path("/a/b/wedding.m4v"))


def test_is_video_false_for_images():
    assert not V.is_video("photo.jpg")
    assert not V.is_video(".cr3")
    assert not V.is_video("notes.txt")


def test_make_video_id_stable_and_safe(tmp_path):
    f = tmp_path / "My Wedding Clip! (final).mov"
    f.write_bytes(b"x" * 100)
    a = V.make_video_id(f)
    b = V.make_video_id(f)
    assert a == b                              # deterministic
    assert a.replace("_", "").replace("-", "").isalnum()  # fs-safe
    assert a.startswith("My_Wedding_Clip")


def test_make_video_id_differs_for_different_files(tmp_path):
    f1 = tmp_path / "clip.mov"
    f2 = tmp_path / "clip.mov"  # same name, different dir
    f1.write_bytes(b"a" * 10)
    sub = tmp_path / "sub"
    sub.mkdir()
    f2 = sub / "clip.mov"
    f2.write_bytes(b"b" * 999)
    assert V.make_video_id(f1) != V.make_video_id(f2)


# --------------------------------------------------------------------------
# probe_video
# --------------------------------------------------------------------------

def test_probe_h264(h264_clip):
    m = V.probe_video(h264_clip)
    assert m.codec == "h264"
    assert m.width == 320 and m.height == 240
    assert m.fps == pytest.approx(30.0, abs=0.5)
    assert m.duration_s == pytest.approx(4.0, abs=0.3)
    assert m.audio_track_count == 1
    assert m.video_id
    assert m.source_name == "clip.mp4"


def test_probe_no_audio(tmp_path):
    clip = _make_clip(tmp_path / "silent.mp4", with_audio=False)
    m = V.probe_video(clip)
    assert m.audio_track_count == 0


def test_probe_missing_file_raises(tmp_path):
    with pytest.raises(V.FFmpegError, match="not found"):
        V.probe_video(tmp_path / "nope.mp4")


def test_probe_vendor_raw_raises(tmp_path):
    # The .braw need not exist — the extension alone is unsupported.
    with pytest.raises(V.FFmpegError, match="RAW"):
        V.probe_video(tmp_path / "A001.braw")


# --------------------------------------------------------------------------
# extract_keyframes — interval mode
# --------------------------------------------------------------------------

def test_extract_interval_frame_count(h264_clip, tmp_path):
    r = V.extract_keyframes(
        h264_clip, tmp_path, mode="interval", interval_s=1.0,
    )
    # 4s @ 1 frame/s → 4 frames (±1 for boundary rounding).
    assert 3 <= r.frame_count <= 5
    assert r.mode == "interval"
    assert r.interval_s == pytest.approx(1.0)
    # Files actually exist and are non-empty JPEGs.
    for fr in r.frames:
        p = r.frames_dir / fr.filename
        assert p.exists() and p.stat().st_size > 0
        assert p.suffix == ".jpg"


def test_extract_interval_timestamps_monotonic(h264_clip, tmp_path):
    r = V.extract_keyframes(h264_clip, tmp_path, interval_s=1.0)
    ts = [f.timestamp_s for f in r.frames]
    assert ts == sorted(ts)
    assert ts[0] == 0.0
    # Consecutive frames are interval_s apart.
    if len(ts) >= 2:
        assert ts[1] - ts[0] == pytest.approx(1.0, abs=0.01)


def test_extract_frame_ids_zero_padded(h264_clip, tmp_path):
    r = V.extract_keyframes(h264_clip, tmp_path, interval_s=2.0)
    assert r.frames[0].frame_id == "frame_000001"
    assert all(f.frame_id.startswith("frame_") for f in r.frames)


def test_extract_dense_interval(h264_clip, tmp_path):
    # 0.5s interval over 4s → ~8 frames.
    r = V.extract_keyframes(h264_clip, tmp_path, interval_s=0.5)
    assert r.frame_count >= 6


# --------------------------------------------------------------------------
# extract_keyframes — keyframe mode
# --------------------------------------------------------------------------

def test_extract_keyframe_mode(h264_clip, tmp_path):
    r = V.extract_keyframes(h264_clip, tmp_path, mode="keyframe")
    assert r.frame_count >= 1
    assert r.interval_s is None
    for fr in r.frames:
        assert (r.frames_dir / fr.filename).exists()


def test_extract_keyframe_dense_gop(tmp_path):
    # Force a keyframe every 15 frames → ~8 keyframes in 4s @ 30fps.
    clip = _make_clip(
        tmp_path / "gop.mp4", vcodec="libx264",
        extra=["-g", "15", "-keyint_min", "15"],
    )
    r = V.extract_keyframes(clip, tmp_path / "out", mode="keyframe")
    assert r.frame_count >= 4
    ts = [f.timestamp_s for f in r.frames]
    assert ts == sorted(ts)


# --------------------------------------------------------------------------
# max_frames cap + validation
# --------------------------------------------------------------------------

def test_max_frames_cap_widens_interval(h264_clip, tmp_path):
    r = V.extract_keyframes(
        h264_clip, tmp_path, mode="interval",
        interval_s=0.1, max_frames=5,
    )
    assert r.frame_count <= 5
    # Interval was widened from 0.1 to ~duration/5 = 0.8.
    assert r.interval_s > 0.1


def test_invalid_mode_raises(h264_clip, tmp_path):
    with pytest.raises(ValueError, match="mode"):
        V.extract_keyframes(h264_clip, tmp_path, mode="bogus")


def test_invalid_interval_raises(h264_clip, tmp_path):
    with pytest.raises(ValueError, match="interval_s"):
        V.extract_keyframes(h264_clip, tmp_path, interval_s=0)


def test_reextract_cleans_stale_frames(h264_clip, tmp_path):
    # First a dense extraction, then a sparse one into the same id dir.
    r1 = V.extract_keyframes(h264_clip, tmp_path, interval_s=0.5)
    r2 = V.extract_keyframes(h264_clip, tmp_path, interval_s=2.0)
    assert r1.frames_dir == r2.frames_dir
    on_disk = list(r2.frames_dir.glob("frame_*.jpg"))
    # No leftover frames from the denser first pass.
    assert len(on_disk) == r2.frame_count
    assert r2.frame_count < r1.frame_count


# --------------------------------------------------------------------------
# manifest.json
# --------------------------------------------------------------------------

def test_manifest_schema(h264_clip, tmp_path):
    r = V.extract_keyframes(h264_clip, tmp_path, interval_s=1.0)
    path = V.write_manifest(r)
    assert path.name == "manifest.json"
    data = json.loads(path.read_text())
    for key in (
        "video_id", "fps", "duration_s", "frame_count",
        "codec", "audio_track_count", "extraction_mode",
        "interval_s", "frames", "schema_version",
        "width", "height", "source_name",
    ):
        assert key in data, f"missing manifest key: {key}"
    assert data["frame_count"] == len(data["frames"])
    assert data["codec"] == "h264"
    first = data["frames"][0]
    assert set(first) == {"frame_id", "timestamp_s", "filename"}


def test_import_video_writes_manifest(h264_clip, tmp_path):
    r = V.import_video(h264_clip, tmp_path, interval_s=1.0)
    assert (r.frames_dir / "manifest.json").exists()
    assert r.frame_count >= 3
    # frames_dir is laid out as <output>/video_frames/<video_id>/
    assert r.frames_dir.parent.name == "video_frames"
    assert r.frames_dir.name == r.meta.video_id


# --------------------------------------------------------------------------
# codec coverage — h.264 / h.265 / ProRes
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# v2.0-P2-1 — proxy downscale (--max-dim)
# --------------------------------------------------------------------------

def _frame_size(path):
    from PIL import Image
    with Image.open(path) as im:
        return im.size  # (w, h)


def test_extract_max_dim_caps_long_edge(h264_clip, tmp_path):
    # h264_clip is 320×240; cap the long edge to 160 → 160×120.
    r = V.extract_keyframes(h264_clip, tmp_path, interval_s=1.0, max_dim=160)
    w, h = _frame_size(r.frames_dir / r.frames[0].filename)
    assert max(w, h) == 160
    assert w % 2 == 0 and h % 2 == 0          # even dims for the encoder
    assert abs((w / h) - (320 / 240)) < 0.02  # aspect preserved


def test_extract_max_dim_none_is_full_res(h264_clip, tmp_path):
    r = V.extract_keyframes(h264_clip, tmp_path, interval_s=1.0)
    assert _frame_size(r.frames_dir / r.frames[0].filename) == (320, 240)


def test_extract_max_dim_keyframe_mode(h264_clip, tmp_path):
    r = V.extract_keyframes(h264_clip, tmp_path, mode="keyframe", max_dim=128)
    w, h = _frame_size(r.frames_dir / r.frames[0].filename)
    assert max(w, h) == 128


def test_import_video_max_dim(h264_clip, tmp_path):
    r = V.import_video(h264_clip, tmp_path, interval_s=1.0, max_dim=160)
    w, h = _frame_size(r.frames_dir / r.frames[0].filename)
    assert max(w, h) == 160
    # manifest still written + frames recorded.
    assert (r.frames_dir / "manifest.json").exists()


@pytest.mark.parametrize("encoder,expected_codec", [
    ("libx264", "h264"),
    ("libx265", "hevc"),
    ("prores_ks", "prores"),
])
def test_codec_probe_and_extract(encoder, expected_codec, tmp_path):
    if not _encoder_available(encoder):
        pytest.skip(f"{encoder} not compiled into this ffmpeg")
    ext = ".mov" if encoder == "prores_ks" else ".mp4"
    clip = _make_clip(tmp_path / f"c{ext}", vcodec=encoder)
    m = V.probe_video(clip)
    assert m.codec == expected_codec
    r = V.extract_keyframes(clip, tmp_path / "out", interval_s=1.0)
    assert r.frame_count >= 3
