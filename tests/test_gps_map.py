"""v2.2-P2-1 — tests for the GPS travel-map projection."""
import pytest

from pixcull.io.gps_map import (
    gps_points_for_video,
    haversine_km,
    project_track,
    track_length_km,
)

# A short synthetic path (~Xiapu coast), a few hundred metres.
TRACK = [
    {"lat": 26.8850, "lon": 119.9990},
    {"lat": 26.8852, "lon": 119.9995},
    {"lat": 26.8858, "lon": 120.0001},
    {"lat": 26.8861, "lon": 120.0010},
]


def test_haversine_one_degree_lat():
    d = haversine_km(0.0, 0.0, 1.0, 0.0)
    assert 110.0 < d < 112.0          # ~111.19 km
    assert haversine_km(10, 20, 10, 20) == 0.0


def test_track_length():
    assert track_length_km(TRACK) > 0
    assert track_length_km(TRACK[:1]) == 0.0


def test_project_basic_shape():
    proj = project_track(TRACK, width=320, height=190, pad=14)
    assert proj is not None
    assert proj["n"] == 4 and len(proj["points"]) == 4
    assert proj["path"].startswith("M")
    assert proj["distance_km"] > 0
    for p in proj["points"]:          # inside the padded box (± rounding)
        assert 14 - 0.6 <= p["x"] <= 320 - 14 + 0.6
        assert 14 - 0.6 <= p["y"] <= 190 - 14 + 0.6


def test_project_north_up_east_right():
    proj = project_track([{"lat": 10.0, "lon": 10.0},
                          {"lat": 11.0, "lon": 11.0}])
    sw, ne = proj["points"]
    assert ne["y"] < sw["y"]          # north → up (smaller svg y)
    assert ne["x"] > sw["x"]          # east  → right


def test_project_degenerate_returns_none():
    assert project_track([]) is None
    assert project_track([{"lat": 1, "lon": 2}]) is None
    assert project_track([{"lat": 1, "lon": 2}, {"lat": 1, "lon": 2}]) is None


def test_project_flat_track_vertically_centered():
    proj = project_track([{"lat": 5.0, "lon": 5.0},
                          {"lat": 5.0, "lon": 6.0},
                          {"lat": 5.0, "lon": 7.0}], width=320, height=190)
    assert proj is not None
    ys = {p["y"] for p in proj["points"]}
    assert len(ys) == 1                       # a flat horizontal line
    assert abs(next(iter(ys)) - 95.0) < 1.0   # centered (~height/2)


def test_gps_points_for_video_missing_file(tmp_path):
    assert gps_points_for_video(tmp_path / "nope.mp4") == {"points": [], "source": ""}


def test_gps_points_for_video_maps_telemetry(tmp_path, monkeypatch):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00")

    class _Tel:
        gps = [{"lat": 1.0, "lon": 2.0, "alt_m": 5.0},
               {"lat": 1.1, "lon": 2.1, "alt_m": 6.0}]
        gps_source = "dji_srt"

    import pixcull.io.gpmf as gpmf
    monkeypatch.setattr(gpmf, "parse_telemetry", lambda *a, **k: _Tel())
    out = gps_points_for_video(clip)
    assert out["source"] == "dji_srt"
    assert out["points"] == [{"lat": 1.0, "lon": 2.0}, {"lat": 1.1, "lon": 2.1}]
