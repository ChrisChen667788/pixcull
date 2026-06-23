"""v2.14-P2 — aerial scene: DJI / drone shots classified as 'aerial'."""

from pixcull.io.exif import is_drone_camera


def test_dji_make():
    assert is_drone_camera("DJI", "FC3582") is True
    assert is_drone_camera("dji", "anything") is True


def test_dji_camera_module_fc_codes():
    for m in ("FC220", "FC6310", "FC3582", "FC7303"):
        assert is_drone_camera("DJI", m) is True
    # "FC" without a digit must NOT match (avoid false positives)
    assert is_drone_camera("Acme", "FCX") is False


def test_mavic_hasselblad_models_are_drones():
    # Mavic 2 Pro / Mavic 3 report Make="Hasselblad" but a drone Model code
    assert is_drone_camera("Hasselblad", "L1D-20c") is True
    assert is_drone_camera("Hasselblad", "L2D-20c") is True


def test_real_hasselblad_body_is_not_a_drone():
    # A genuine Hasselblad medium-format body must NOT be misread as aerial
    for m in ("X1D II 50C", "907X", "H6D-100c", "X2D 100C"):
        assert is_drone_camera("Hasselblad", m) is False


def test_normal_cameras_not_drones():
    assert is_drone_camera("Canon", "Canon EOS R5") is False
    assert is_drone_camera("NIKON CORPORATION", "NIKON Z 9") is False
    assert is_drone_camera("SONY", "ILCE-7M4") is False
    assert is_drone_camera(None, None) is False


def test_dji_filename_fallback():
    # EXIF stripped on export → fall back to the DJI_ filename convention
    assert is_drone_camera(None, None, "DJI_0503.JPG") is True
    assert is_drone_camera("Canon", "EOS R5", "3J0A1234.JPG") is False


def test_aerial_registered_downstream():
    # the new scene must resolve cleanly in both the genre strategy table and
    # the scene-template config (no KeyError / crash for scene='aerial')
    from pixcull.scoring.genre_strategies import get_strategy
    from pixcull.config import PixCullConfig
    s = get_strategy("aerial")
    assert s.axis_emphasis.get("composition", 1.0) > 1.0   # composition-led
    assert s.check_overrides.get("action_at_peak") == "suppress"
    tpl = PixCullConfig.load().template_for("aerial")
    assert tpl.weights  # resolves (use_defaults → default weights)
