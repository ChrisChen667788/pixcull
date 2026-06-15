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


# --------------------------------------------------------------------------
# v2.4-P0-1 — true VLM best-frame caption
# --------------------------------------------------------------------------

def test_enrich_sets_caption_source(monkeypatch):
    monkeypatch.setattr(C, "_try_llm", lambda: None)
    monkeypatch.setattr(C, "_try_vlm", lambda: None)
    out = C.enrich([_cand()])
    assert out[0]["caption_source"] == "template"   # default → no regression
    assert out[0]["why_semantic"]


def test_caption_with_source_prefers_vlm(monkeypatch):
    # VLM wins over LLM + template when it returns a caption. v2.7 — the real
    # path is vlm_caption_bilingual (zh, en); caption_with_source returns the
    # zh half + source.
    monkeypatch.setattr(
        C, "vlm_caption_bilingual",
        lambda cand, frames_root=None: ("4.5–7.5s:狗在奔跑", "4.5–7.5s:A dog runs"))
    txt, src = C.caption_with_source(_cand(), frames_root="/x")
    assert src == "vlm" and "狗" in txt


def test_resolve_best_frame(tmp_path):
    fd = tmp_path / "video_frames" / "vid1"
    fd.mkdir(parents=True)
    (fd / "frame_000005.jpg").write_bytes(b"x")
    got = C._resolve_best_frame(_cand(best_frame_id="frame_000005"), tmp_path)
    assert got is not None and got.name == "frame_000005.jpg"
    # missing frame / missing id / no root → None (graceful)
    assert C._resolve_best_frame(_cand(best_frame_id="frame_999999"), tmp_path) is None
    assert C._resolve_best_frame(_cand(best_frame_id=None), tmp_path) is None
    assert C._resolve_best_frame(_cand(best_frame_id="frame_000005"), None) is None


def test_vlm_caption_zh_rewrite(tmp_path, monkeypatch):
    """v2.5 — with the local zh LLM present, the English BLIP description
    is rewritten to Chinese; without it (or on garbage output) the
    English passes through unchanged."""
    fd = tmp_path / "video_frames" / "v"; fd.mkdir(parents=True)
    (fd / "frame_000001.jpg").write_bytes(b"x")
    monkeypatch.setattr(C, "vlm_caption_from_image",
                        lambda p: "A dog runs on the beach")
    cand = _cand(best_frame_id="frame_000001", start_s=1.0, end_s=2.0)

    # no LLM → English passthrough
    monkeypatch.setattr(C, "_try_llm", lambda: None)
    assert C.vlm_caption(cand, tmp_path) == "1.0–2.0s:A dog runs on the beach"

    # fake zh LLM → Chinese rewrite
    monkeypatch.setattr(
        C, "_try_llm",
        lambda: (lambda prompt, **kw:
                 {"choices": [{"text": "狗在海滩上奔跑"}]}))
    assert C.vlm_caption(cand, tmp_path) == "1.0–2.0s:狗在海滩上奔跑"

    # LLM returns non-CJK garbage → sanity check rejects, English kept
    monkeypatch.setattr(
        C, "_try_llm",
        lambda: (lambda prompt, **kw:
                 {"choices": [{"text": "I cannot translate that."}]}))
    assert C.vlm_caption(cand, tmp_path) == "1.0–2.0s:A dog runs on the beach"


def test_vlm_caption_real_model(tmp_path, monkeypatch):
    """Integration: the real captioning VLM looks at the best frame.
    Skips cleanly where transformers / the model can't load (CI)."""
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    pytest.importorskip("PIL")
    from PIL import Image
    fd = tmp_path / "video_frames" / "v"
    fd.mkdir(parents=True)
    Image.new("RGB", (320, 240), (90, 140, 200)).save(fd / "frame_000003.jpg")
    monkeypatch.setattr(C, "_VLM_ENABLED", True)
    C.reset()
    if C._try_vlm() is None:
        pytest.skip("captioning VLM unavailable")
    cand = _cand(best_frame_id="frame_000003", start_s=2.0, end_s=4.0)
    out = C.vlm_caption(cand, frames_root=tmp_path)
    assert out and out.startswith("2.0–4.0s:")
    assert len(out) > len("2.0–4.0s:")              # a real description, not empty
    _, src = C.caption_with_source(cand, frames_root=tmp_path)
    assert src == "vlm"


# ── v2.7 bilingual caption ──────────────────────────────────────────────

def test_template_caption_en_is_english_only():
    """v2.7 — the EN template carries only language-neutral atoms (time +
    scene word + best frame), never a translated zh fragment."""
    cap = C.template_caption_en(
        {"start_s": 1.0, "end_s": 3.0, "scene": "landscape",
         "best_frame_score": 0.82, "why": "构图稳 + 主体清晰"})
    assert cap.startswith("1.0–3.0s:")
    assert "landscape" in cap and "best frame 0.82" in cap
    assert not any("一" <= c <= "鿿" for c in cap)        # no CJK leaked


def test_caption_bilingual_three_tuple():
    """caption_bilingual returns (zh, en, source); en is always present."""
    zh, en, src = C.caption_bilingual(
        {"start_s": 0.0, "end_s": 2.0, "scene": "food"})
    assert src == "template"
    assert zh and en
    assert "food" in en                                   # EN template scene word


def test_vlm_bilingual_returns_zh_and_en(tmp_path, monkeypatch):
    """vlm_caption_bilingual: en = raw BLIP, zh = local-LLM rewrite of it."""
    fd = tmp_path / "video_frames" / "v"; fd.mkdir(parents=True)
    (fd / "frame_000001.jpg").write_bytes(b"x")
    monkeypatch.setattr(C, "vlm_caption_from_image",
                        lambda p: "A bride looks back")
    monkeypatch.setattr(
        C, "_try_llm",
        lambda: (lambda prompt, **kw: {"choices": [{"text": "新娘回眸"}]}))
    cand = _cand(best_frame_id="frame_000001", start_s=1.0, end_s=2.0)
    pair = C.vlm_caption_bilingual(cand, tmp_path)
    assert pair is not None
    zh, en = pair
    assert "新娘" in zh and "bride" in en                  # zh translated, en raw
    assert zh.startswith("1.0–2.0s:") and en.startswith("1.0–2.0s:")


def test_vlm_bilingual_no_llm_en_passthrough(tmp_path, monkeypatch):
    """No LLM → the zh half falls back to the English (never worse)."""
    fd = tmp_path / "video_frames" / "v"; fd.mkdir(parents=True)
    (fd / "frame_000001.jpg").write_bytes(b"x")
    monkeypatch.setattr(C, "vlm_caption_from_image", lambda p: "A dog runs")
    monkeypatch.setattr(C, "_try_llm", lambda: None)
    cand = _cand(best_frame_id="frame_000001", start_s=1.0, end_s=2.0)
    zh, en = C.vlm_caption_bilingual(cand, tmp_path)
    assert zh == en == "1.0–2.0s:A dog runs"


def test_enrich_adds_why_semantic_en():
    """v2.7 — enrich writes both why_semantic (zh) and why_semantic_en (en)."""
    out = C.enrich([_cand()])            # no frames_root → template path
    c = out[0]
    assert c["why_semantic"] and c["why_semantic_en"]
    assert c["caption_source"] == "template"
    assert not any("一" <= ch <= "鿿" for ch in c["why_semantic_en"])  # en is English
