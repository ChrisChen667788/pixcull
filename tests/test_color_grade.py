"""v2.0-P2-2 — tests for pixcull.scoring.color_grade."""

from __future__ import annotations

import io

import numpy as np
import pytest

from pixcull.scoring import color_grade as C


def _grey(v=128, n=8):
    return np.full((n, n, 3), v, dtype=np.uint8)


# --------------------------------------------------------------------------
# presets / apply_grade
# --------------------------------------------------------------------------

def test_list_presets_has_film_looks():
    ids = {p["id"] for p in C.list_presets()}
    assert {"none", "arri_709a", "fuji_eterna",
            "kodak_vision3", "teal_orange", "bw"} <= ids
    assert C.list_presets()[0]["id"] == "none"   # Original first


def test_none_is_identity():
    img = _grey()
    out = C.apply_grade(img, "none")
    assert np.array_equal(out, img)


def test_unknown_preset_is_identity():
    img = _grey()
    assert np.array_equal(C.apply_grade(img, "does_not_exist"), img)


def test_bw_is_neutral_grey():
    out = C.apply_grade(_grey(), "bw")
    r, g, b = out[0, 0]
    assert r == g == b   # desaturated


def test_kodak_is_warm():
    # On neutral grey, a warm look lifts R relative to B.
    out = C.apply_grade(_grey(), "kodak_vision3")
    r, g, b = out[0, 0]
    assert int(r) > int(b)


def test_apply_preserves_shape_dtype():
    img = (np.random.default_rng(0).random((12, 9, 3)) * 255).astype("uint8")
    out = C.apply_grade(img, "teal_orange")
    assert out.shape == img.shape
    assert out.dtype == np.uint8
    assert out.min() >= 0 and out.max() <= 255


def test_apply_clamps_extremes():
    white = np.full((4, 4, 3), 255, dtype=np.uint8)
    black = np.zeros((4, 4, 3), dtype=np.uint8)
    for p in C.PRESETS:
        assert C.apply_grade(white, p).max() <= 255
        assert C.apply_grade(black, p).min() >= 0


# --------------------------------------------------------------------------
# grade_image_bytes
# --------------------------------------------------------------------------

def _jpeg(v=100, size=(60, 40)):
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(np.full((size[1], size[0], 3), v, dtype=np.uint8)).save(
        buf, "JPEG")
    return buf.getvalue()


def test_grade_bytes_none_passthrough():
    jb = _jpeg()
    assert C.grade_image_bytes(jb, "none") is jb or C.grade_image_bytes(jb, "none") == jb


def test_grade_bytes_applies_and_is_jpeg():
    jb = _jpeg()
    out = C.grade_image_bytes(jb, "kodak_vision3")
    assert out[:2] == b"\xff\xd8"          # JPEG SOI
    assert out != jb


def test_grade_bytes_resize_shrinks():
    jb = _jpeg(size=(120, 80))
    out = C.grade_image_bytes(jb, "none", max_w=40)
    from PIL import Image
    with Image.open(io.BytesIO(out)) as im:
        assert im.width == 40
        assert im.height == 27 or im.height == 26   # aspect ~preserved


def test_grade_bytes_thumb_plus_grade():
    jb = _jpeg(size=(100, 100))
    out = C.grade_image_bytes(jb, "bw", max_w=32)
    from PIL import Image
    with Image.open(io.BytesIO(out)) as im:
        assert im.width == 32


# --------------------------------------------------------------------------
# v2.1-P1-1 — .cube 3D LUT engine
# --------------------------------------------------------------------------

def _write_cube(path, n=2, *, invert=False, title="Test"):
    lines = [f'TITLE "{title}"', f"LUT_3D_SIZE {n}",
             "DOMAIN_MIN 0 0 0", "DOMAIN_MAX 1 1 1"]
    for b in range(n):              # red varies fastest
        for g in range(n):
            for r in range(n):
                rv, gv, bv = r / (n - 1), g / (n - 1), b / (n - 1)
                if invert:
                    rv, gv, bv = 1 - rv, 1 - gv, 1 - bv
                lines.append(f"{rv:.6f} {gv:.6f} {bv:.6f}")
    path.write_text("\n".join(lines) + "\n")
    return path


def test_load_cube_parses(tmp_path):
    cube = C.load_cube(_write_cube(tmp_path / "id.cube", n=2, title="Hello"))
    assert cube.size == 2
    assert cube.title == "Hello"
    assert cube.table.shape == (2, 2, 2, 3)
    assert cube.domain_max == (1.0, 1.0, 1.0)


def test_apply_identity_cube_is_noop(tmp_path):
    cube = C.load_cube(_write_cube(tmp_path / "id.cube", n=2))
    img = (np.random.default_rng(0).random((12, 10, 3)) * 255).astype("uint8")
    out = C.apply_cube(img, cube)
    assert np.abs(out.astype(int) - img.astype(int)).max() <= 2  # ~identity


def test_apply_invert_cube(tmp_path):
    cube = C.load_cube(_write_cube(tmp_path / "inv.cube", n=2, invert=True))
    img = np.full((6, 6, 3), 200, dtype="uint8")
    out = C.apply_cube(img, cube)
    assert np.abs(out.astype(int) - (255 - 200)).max() <= 3


def test_load_cube_errors(tmp_path):
    bad = tmp_path / "nosize.cube"
    bad.write_text("0 0 0\n1 1 1\n")
    with pytest.raises(ValueError, match="LUT_3D_SIZE"):
        C.load_cube(bad)
    wrong = tmp_path / "wrong.cube"
    wrong.write_text("LUT_3D_SIZE 2\n0 0 0\n1 1 1\n")  # needs 8 entries
    with pytest.raises(ValueError, match="expected"):
        C.load_cube(wrong)


def test_list_cubes(tmp_path):
    _write_cube(tmp_path / "Kodak2383.cube")
    _write_cube(tmp_path / "Fuji3513.cube")
    ids = {c["id"] for c in C.list_cubes(tmp_path)}
    assert ids == {"cube:Kodak2383", "cube:Fuji3513"}
    assert C.list_cubes(tmp_path / "nope") == []


def test_grade_bytes_with_cube(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "LUTS_DIR", tmp_path)
    C._CUBE_CACHE.clear()
    _write_cube(tmp_path / "inv.cube", n=2, invert=True)
    jb = _jpeg(v=200, size=(20, 20))
    out = C.grade_image_bytes(jb, "cube:inv")
    from PIL import Image
    with Image.open(io.BytesIO(out)) as im:
        arr = np.asarray(im)
    assert abs(int(arr.mean()) - 55) <= 6        # inverted 200 → ~55
