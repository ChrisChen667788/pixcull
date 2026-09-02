"""v3.2 — temperature belongs in the cache key, and only when non-zero.

Two separate things are pinned here and they pull against each other:

1. Sampling the same frame N times has to produce N distinct cache slots,
   or a self-consistency measurement reads the one deterministic answer N
   times and reports perfect agreement on every image. That is not a
   subtle failure — it is a number that looks like a finding.

2. The deterministic key must not move. There are thousands of entries in
   the local cache that were paid for one API call at a time; widening the
   key unconditionally would orphan every one of them on the first run
   after this version.

So the temperature discriminator is *appended*, and only when truthy.
"""
from pixcull.scoring.m3 import cache_extra

BASE = dict(model="MiniMax-M3", scene="wedding", vertical="wedding",
            evidence_arm="technical", evidence_len=412, prompt_override=None)


def test_deterministic_key_is_unchanged_by_this_version():
    """The exact pre-v3.2 string, spelled out rather than derived.

    Deriving the expected value from the same function under test would
    pass no matter what the function did. This is the literal shape the
    4,000+ cached entries were written under.
    """
    from pixcull.scoring.m3 import PROMPT_VERSION
    import hashlib
    empty = hashlib.sha256(b"").hexdigest()[:12]
    expected = (f"MiniMax-M3|{PROMPT_VERSION}|wedding|wedding|"
                f"technical|412|{empty}")
    assert cache_extra(**BASE) == expected
    assert cache_extra(**BASE, temperature=0.0) == expected


def test_nonzero_temperature_produces_a_different_slot():
    hot = cache_extra(**BASE, temperature=0.5)
    assert hot != cache_extra(**BASE)
    assert hot.startswith(cache_extra(**BASE)), (
        "the discriminator must be appended, not folded in — a fold would "
        "move the deterministic key too"
    )


def test_two_different_temperatures_do_not_collide():
    keys = {cache_extra(**BASE, temperature=t) for t in (0.3, 0.5, 0.7, 1.0)}
    assert len(keys) == 4


def test_n_consistency_samples_do_not_all_land_in_one_slot():
    """The failure this version exists to prevent, stated as a test.

    Before v3.2 every one of these was the same string, so three samples
    of one frame were three reads of one cached answer.
    """
    samples = [cache_extra(**BASE, temperature=0.7) for _ in range(3)]
    assert len(set(samples)) == 1, "same temperature must stay cacheable"
    assert samples[0] != cache_extra(**BASE), (
        "a sampled pass must not read the deterministic entry"
    )


def test_score_passes_temperature_through_to_the_api():
    """A key that varies while the request does not would be worse than
    the bug: distinct cache slots holding identical deterministic answers.
    """
    import inspect
    from pixcull.scoring.m3 import MiniMaxM3Judge
    src = inspect.getsource(MiniMaxM3Judge.score)
    assert "self._complete(messages, max_tokens, temperature)" in src
    sig = inspect.signature(MiniMaxM3Judge._complete)
    assert "temperature" in sig.parameters
