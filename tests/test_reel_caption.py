"""v2.1-P0-3 — tests for pixcull.scoring.reel_caption."""

from __future__ import annotations

import pytest

from pixcull.scoring import reel_caption as C


def _cand(**kw):
    base = dict(rank=1, start_s=4.5, end_s=7.5,
                why="精彩瞬间 + 平稳运镜 + 人物入镜",
                best_frame_score=0.85, scene="portrait")
    base.update(kw)
    return base


def setup_function():
    C.reset()


def test_template_caption_has_time_and_signals():
    cap = C.template_caption(_cand())
    assert "4.5" in cap and "7.5" in cap
    assert "精彩瞬间" in cap and "平稳运镜" in cap
    assert "人物特写" in cap          # scene word for portrait
    assert "0.85" in cap              # best-frame score


def test_template_caption_quiet_fallback():
    cap = C.template_caption(_cand(why="稳定可用片段", best_frame_score=None,
                                   scene=None))
    assert "稳定可用片段" in cap
    assert cap.startswith("4.5")      # still time-stamped


def test_template_caption_no_signals():
    cap = C.template_caption({"start_s": 0.0, "end_s": 1.0})
    assert "0.0" in cap and "1.0" in cap


def test_caption_falls_back_to_template(monkeypatch):
    # No LLM installed ⇒ caption == template.
    monkeypatch.setattr(C, "_try_llm", lambda: None)
    cand = _cand()
    assert C.caption(cand) == C.template_caption(cand)


def test_llm_caption_none_without_model(monkeypatch):
    monkeypatch.setattr(C, "_try_llm", lambda: None)
    assert C.llm_caption(_cand()) is None


def test_caption_uses_llm_when_available(monkeypatch):
    # Fake LLM returns a fluent line → caption uses it.
    class _FakeLLM:
        def __call__(self, prompt, **kw):
            return {"choices": [{"text": " 新娘回眸,暖光逆光 "}]}
    monkeypatch.setattr(C, "_try_llm", lambda: _FakeLLM())
    cap = C.caption(_cand())
    assert cap == "新娘回眸,暖光逆光"


def test_llm_caption_handles_crash(monkeypatch):
    class _BadLLM:
        def __call__(self, *a, **k):
            raise RuntimeError("model exploded")
    monkeypatch.setattr(C, "_try_llm", lambda: _BadLLM())
    assert C.llm_caption(_cand()) is None        # graceful
    assert C.caption(_cand()) == C.template_caption(_cand())  # → template


def test_enrich_adds_why_semantic(monkeypatch):
    monkeypatch.setattr(C, "_try_llm", lambda: None)
    cands = [_cand(rank=1), _cand(rank=2, start_s=10.0, end_s=12.0)]
    out = C.enrich(cands)
    assert all("why_semantic" in c for c in out)
    assert out[0]["why_semantic"].startswith("4.5")


def test_reel_detection_writes_why_semantic(tmp_path):
    # End-to-end: run_reel_detection enriches the JSON.
    import json
    from pixcull.scoring import reel as R
    temporal = {"schema_version": 1, "frames": [
        {"frame_id": f"frame_{i+1:06d}", "timestamp_s": i * 0.5,
         "score_final": 0.6, "score_temporal": (0.9 if i == 4 else 0.3),
         "burst_event": (1.0 if i == 4 else 0.0),
         "motion_continuity": 0.9, "temporal_stability": 0.9}
        for i in range(12)]}
    (tmp_path / "temporal.json").write_text(json.dumps(temporal))
    cands = R.run_reel_detection(tmp_path, n_min=1, n_max=4)
    data = json.loads((tmp_path / "reel_candidates.json").read_text())
    assert data and all("why_semantic" in c for c in data)
