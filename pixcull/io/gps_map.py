"""v2.2-P2-1 — GPS track → mini-map projection for the video timeline.

The "travel-story" view: GoPro/DJI clips carry a GPS track (GPMF GPS5,
or DJI SRT telemetry); this projects that lat/lon path into a compact
SVG box so the video-review timeline can draw it as a mini-map with a
marker that follows the playhead.

Two pure, well-tested pieces:

    project_track(points, ...)   lat/lon path → normalized SVG coords
    haversine_km(a_lat, a_lon, b_lat, b_lon)

plus a thin reader that reuses the existing telemetry extractor:

    gps_points_for_video(path)   → {"points": [{lat,lon}], "source": ...}

GPMF GPS5 samples carry no per-sample timestamp, so the timeline marker
maps playhead time → fractional position along the track (uniform-rate
assumption).  Good enough for a glanceable travel map.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

_EARTH_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * _EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def track_length_km(points: list) -> float:
    """Summed great-circle length of an ordered lat/lon track."""
    total = 0.0
    prev = None
    for p in points:
        lat, lon = p.get("lat"), p.get("lon")
        if lat is None or lon is None:
            continue
        if prev is not None:
            total += haversine_km(prev[0], prev[1], lat, lon)
        prev = (lat, lon)
    return total


def project_track(points: list, *, width: int = 320, height: int = 190,
                  pad: int = 14) -> Optional[dict]:
    """Project an ordered ``[{lat, lon}, …]`` track into an SVG box.

    Equirectangular projection (longitude scaled by cos(mean latitude) so
    the aspect ratio is right), uniformly scaled to fit ``width×height``
    inside ``pad``, north-up.  Returns ``None`` for < 2 distinct points.

    Returns ``{n, points:[{x,y}], path, distance_km, bbox, width, height}``.
    """
    raw = [(float(p["lat"]), float(p["lon"])) for p in points
           if p.get("lat") is not None and p.get("lon") is not None]
    if len(raw) < 2:
        return None

    lats = [a for a, _ in raw]
    lons = [b for _, b in raw]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)

    cos_lat = max(0.01, math.cos(math.radians((min_lat + max_lat) / 2.0)))
    # unscaled planar coords: x east (lon·cos), y north (lat)
    xs = [lon * cos_lat for _, lon in raw]
    ys = [lat for lat, _ in raw]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    dx, dy = maxx - minx, maxy - miny
    if dx <= 0 and dy <= 0:
        return None  # all coincident

    iw, ih = width - 2 * pad, height - 2 * pad
    sx = iw / dx if dx > 0 else float("inf")
    sy = ih / dy if dy > 0 else float("inf")
    scale = min(sx, sy)
    off_x = pad + (iw - dx * scale) / 2.0
    off_y = pad + (ih - dy * scale) / 2.0

    pts = []
    for x, y in zip(xs, ys):
        sxp = off_x + (x - minx) * scale
        syp = off_y + (maxy - y) * scale          # north (max lat) → top
        pts.append({"x": round(sxp, 2), "y": round(syp, 2)})

    path = "M" + " L".join(f"{p['x']} {p['y']}" for p in pts)
    return {
        "n": len(raw),
        "points": pts,
        "path": path,
        "distance_km": round(track_length_km(points), 3),
        "bbox": {"min_lat": min_lat, "max_lat": max_lat,
                 "min_lon": min_lon, "max_lon": max_lon},
        "width": width,
        "height": height,
    }


def gps_points_for_video(path, *, ffmpeg: Optional[str] = None) -> dict:
    """Read a clip's GPS track via the existing telemetry extractor.

    Returns ``{"points": [{lat, lon}], "source": "gpmf"|"dji_srt"|""}`` —
    empty points when the clip carries no GPS (or ffmpeg is unavailable).
    """
    p = Path(path)
    if not p.exists():
        return {"points": [], "source": ""}
    try:
        from pixcull.io.gpmf import parse_telemetry
        tel = parse_telemetry(p, ffmpeg=ffmpeg)
    except Exception:
        return {"points": [], "source": ""}
    pts = [{"lat": g["lat"], "lon": g["lon"]}
           for g in tel.gps
           if g.get("lat") is not None and g.get("lon") is not None]
    return {"points": pts, "source": tel.gps_source if pts else ""}
