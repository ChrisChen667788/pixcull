"""V17.0 — verticals registry + sample bank tests."""

from __future__ import annotations

import pytest

from pixcull import verticals


# ---------------------------------------------------------------------------
# Registry shape
# ---------------------------------------------------------------------------

def test_ten_verticals_present():
    """User explicitly named 10 — pin the count so a future PR that
    accidentally drops or duplicates one fails this test."""
    assert len(verticals.VERTICALS) == 10


def test_keys_are_unique():
    keys = [v.key for v in verticals.VERTICALS]
    assert len(keys) == len(set(keys))


def test_keys_are_url_safe():
    """Keys end up in URL paths and on-disk dir names — no spaces, no
    Chinese, no slashes."""
    for v in verticals.VERTICALS:
        assert v.key.isascii()
        assert " " not in v.key
        assert "/" not in v.key
        assert v.key == v.key.lower()


def test_every_vertical_has_zh_label_and_icon():
    for v in verticals.VERTICALS:
        assert v.zh, f"vertical {v.key} missing zh label"
        assert v.icon, f"vertical {v.key} missing icon"


def test_parent_genres_are_real():
    """Parent_genres must be a subset of the 14 internal genres so
    eval slicing can map vertical → genre filter."""
    real_genres = {
        "portrait", "wildlife", "event", "stilllife", "landscape",
        "street", "architecture", "documentary", "fashion", "macro",
        "food", "sports", "astro", "abstract",
    }
    for v in verticals.VERTICALS:
        assert v.parent_genres
        unknown = v.parent_genres - real_genres
        assert not unknown, f"vertical {v.key} has unknown parent genre: {unknown}"


def test_user_named_verticals_present():
    """Direct check: every vertical the user named at V17 kickoff
    exists by key. Fails loudly if someone removes one."""
    expected = {"landscape", "wildlife", "wedding", "travel", "cosplay",
                "kids", "pet", "bird", "event", "sports"}
    actual = {v.key for v in verticals.VERTICALS}
    missing = expected - actual
    assert not missing, f"missing verticals: {missing}"


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def test_get_vertical_returns_match():
    v = verticals.get_vertical("wedding")
    assert v is not None
    assert v.zh == "婚纱摄影"


def test_get_vertical_unknown_returns_none():
    assert verticals.get_vertical("__not_a_vertical__") is None


# ---------------------------------------------------------------------------
# Sample bank — roundtrip + counters + path safety
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    """Redirect _data_root() to a tmp dir so tests don't pollute
    ~/Library/Application Support/PixCull."""
    monkeypatch.setattr(verticals, "_data_root", lambda: tmp_path)
    return tmp_path


def test_save_and_count_sample(isolated_data_dir):
    info = verticals.save_sample("wedding", "good",
                                  "DSC_0042.jpg", b"fake-jpeg-bytes")
    assert info["bucket"] == "good"
    assert info["filename"].endswith(".jpg")
    counts = verticals.count_samples("wedding")
    assert counts == {"good": 1, "bad": 0, "total": 1}


def test_save_sample_hash_avoids_collision(isolated_data_dir):
    """Same original name + different content → different hashed names."""
    a = verticals.save_sample("kids", "good", "x.jpg", b"img-A")
    b = verticals.save_sample("kids", "good", "x.jpg", b"img-B")
    assert a["filename"] != b["filename"]
    assert verticals.count_samples("kids")["good"] == 2


def test_save_sample_rejects_unknown_vertical(isolated_data_dir):
    with pytest.raises(ValueError):
        verticals.save_sample("__not_real__", "good", "x.jpg", b"x")


def test_save_sample_rejects_unknown_bucket(isolated_data_dir):
    with pytest.raises(ValueError):
        verticals.save_sample("wedding", "ugly", "x.jpg", b"x")


def test_delete_sample(isolated_data_dir):
    info = verticals.save_sample("pet", "bad", "blurry.jpg", b"oops")
    assert verticals.delete_sample("pet", "bad", info["filename"]) is True
    assert verticals.count_samples("pet")["bad"] == 0


def test_delete_sample_missing_file_returns_false(isolated_data_dir):
    assert verticals.delete_sample("pet", "good", "nope.jpg") is False


def test_sample_path_blocks_traversal(isolated_data_dir):
    verticals.save_sample("bird", "good", "ok.jpg", b"x")
    # Traversal attempts return None
    assert verticals.sample_path("bird", "good", "../../../etc/passwd") is None
    assert verticals.sample_path("bird", "good", "..\\evil") is None
    # Hidden-file pattern blocked
    assert verticals.sample_path("bird", "good", ".hidden.jpg") is None


def test_list_samples_newest_first(isolated_data_dir):
    import time
    a = verticals.save_sample("travel", "good", "a.jpg", b"a")
    time.sleep(0.01)
    b = verticals.save_sample("travel", "good", "b.jpg", b"b")
    samples = verticals.list_samples("travel", "good")
    assert len(samples) == 2
    assert samples[0]["filename"] == b["filename"]
    assert samples[1]["filename"] == a["filename"]


# ---------------------------------------------------------------------------
# Progress snapshot
# ---------------------------------------------------------------------------

def test_progress_uses_balanced_min(isolated_data_dir):
    """50 good + 0 bad should NOT report 100% — both buckets matter."""
    for i in range(50):
        verticals.save_sample("wedding", "good", f"{i}.jpg", str(i).encode())
    snap = next(x for x in verticals.registry_with_progress()
                  if x["key"] == "wedding")
    assert snap["counts"]["good"] == 50
    assert snap["counts"]["bad"] == 0
    assert snap["progress"] == 0.0  # bad bucket empty → 0


def test_progress_clamps_to_one(isolated_data_dir):
    target = next(v.sample_target for v in verticals.VERTICALS if v.key == "kids")
    for i in range(target + 5):
        verticals.save_sample("kids", "good", f"{i}.jpg", str(i).encode())
        verticals.save_sample("kids", "bad", f"{i}.jpg", str(i).encode())
    snap = next(x for x in verticals.registry_with_progress()
                  if x["key"] == "kids")
    assert snap["progress"] == 1.0


def test_registry_snapshot_shape(isolated_data_dir):
    out = verticals.registry_with_progress()
    assert len(out) == 10
    keys = {x["key"] for x in out}
    assert keys == {"landscape", "wildlife", "wedding", "travel", "cosplay",
                    "kids", "pet", "bird", "event", "sports"}
    for v in out:
        assert "zh" in v and "icon" in v and "counts" in v
        assert v["counts"]["total"] == v["counts"]["good"] + v["counts"]["bad"]


# ---------------------------------------------------------------------------
# V17.1 — list_samples shape used by the /verticals/list endpoint
# ---------------------------------------------------------------------------

def test_list_samples_returns_size_and_mtime(isolated_data_dir):
    """Each entry must carry filename + size + mtime — the /verticals/list
    endpoint and the drawer's grid both depend on this shape."""
    info = verticals.save_sample("kids", "good", "x.jpg", b"abcdefg")
    samples = verticals.list_samples("kids", "good")
    assert len(samples) == 1
    s = samples[0]
    assert s["filename"] == info["filename"]
    assert s["size"] == 7
    assert isinstance(s["mtime"], float)


def test_list_samples_empty_bucket(isolated_data_dir):
    samples = verticals.list_samples("bird", "bad")
    assert samples == []


def test_list_samples_unknown_vertical_raises(isolated_data_dir):
    """Unknown vertical → ValueError, not silent empty list (the
    /verticals/list endpoint translates this to a 404)."""
    with pytest.raises(ValueError):
        verticals.list_samples("__not_real__", "good")
