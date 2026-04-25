from pixcull.config import PixCullConfig


def test_load_default_config():
    c = PixCullConfig.load()
    assert c.version
    assert "portrait" in c.scenes
    assert "wildlife" in c.scenes


def test_scene_template_fallback_to_defaults():
    c = PixCullConfig.load()
    tpl = c.template_for("landscape")
    assert tpl.weights or tpl.blur


def test_portrait_weights_sum_to_one():
    c = PixCullConfig.load()
    w = c.scenes["portrait"].weights
    total = sum(w.values())
    assert abs(total - 1.0) < 1e-6, f"portrait weights sum to {total}"


def test_wildlife_sharpness_stricter_than_portrait():
    c = PixCullConfig.load()
    assert (
        c.scenes["wildlife"].blur["laplacian_subject_min"]
        > c.scenes["portrait"].blur["laplacian_subject_min"]
    )
