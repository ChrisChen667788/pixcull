"""v2.7 — tests for the BLIP ONNX inference path in reel_caption.

Strategy: mock onnxruntime.InferenceSession so we never load a real ONNX
model.  All tests complete in milliseconds with zero network/disk access.
"""

from __future__ import annotations

import json
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from pixcull.scoring import reel_caption as C


# ── helpers ──────────────────────────────────────────────────────────────────

def _cand(**kw):
    base = dict(rank=1, start_s=1.0, end_s=3.0,
                why="精彩瞬间 + 平稳运镜",
                best_frame_score=0.80, scene="portrait")
    base.update(kw)
    return base


def setup_function():
    C.reset()


# ── fixtures ─────────────────────────────────────────────────────────────────

def _make_onnx_dir(tmp_path: Path, *, with_tokenizer: bool = False,
                   cfg_override: dict | None = None) -> Path:
    """Create a fake blip-onnx directory with sentinel ONNX placeholders.

    ``tmp_path`` is the parent directory (e.g. ``<base>/models``); the
    ``blip-onnx`` sub-directory is created inside it.  Uses ``parents=True``
    so the parent is auto-created if it doesn't exist yet.
    """
    d = tmp_path / "blip-onnx"
    d.mkdir(parents=True, exist_ok=True)
    (d / "visual_encoder.onnx").write_bytes(b"FAKE_VE")
    (d / "text_decoder.onnx").write_bytes(b"FAKE_TD")
    cfg = {
        "model_id": "Salesforce/blip-image-captioning-base",
        "image_size": 64,   # tiny for tests
        "vocab_size": 30524,
        "max_length": 8,
        "bos_token_id": 30522,
        "eos_token_id": 102,
        "pad_token_id": 0,
    }
    if cfg_override:
        cfg.update(cfg_override)
    (d / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    if with_tokenizer:
        # Minimal tokenizer.json with a tiny vocab.
        tok = {"model": {"vocab": {"a": 1, "dog": 2, "runs": 3, "##s": 4}}}
        (d / "tokenizer.json").write_text(json.dumps(tok), encoding="utf-8")
    return d


class _FakeSession:
    """Minimal mock of an onnxruntime.InferenceSession."""

    def __init__(self, path: str, *, output_shape: tuple, output_dtype=np.float32):
        self._path = path
        self._output_shape = output_shape
        self._output_dtype = output_dtype
        self._inputs = [types.SimpleNamespace(name="input")]

    def get_inputs(self):
        return self._inputs

    def run(self, output_names, feed_dict):
        return [np.zeros(self._output_shape, dtype=self._output_dtype)]


def _make_session_factory(blip_dir: Path, *, enc_seq: int = 16,
                          hidden: int = 32, vocab: int = 30524):
    """Return a fake InferenceSession constructor that serves both sub-graphs."""
    class _VisSession(_FakeSession):
        def __init__(self, path, providers=None):
            super().__init__(path, output_shape=(1, enc_seq, hidden))
            self._model_path = path  # mirror real ort attribute

        def get_inputs(self):
            return [types.SimpleNamespace(name="pixel_values")]

        def run(self, output_names, feed_dict):
            return [np.zeros((1, enc_seq, hidden), dtype=np.float32)]

    class _DecSession(_FakeSession):
        def __init__(self, path, providers=None):
            # Produce 2-token output then EOS on the third call.
            super().__init__(path, output_shape=(1, 1, vocab))
            self._model_path = path
            self._call_count = 0
            self._eos = 102

        def get_inputs(self):
            return [
                types.SimpleNamespace(name="input_ids"),
                types.SimpleNamespace(name="encoder_hidden_states"),
                types.SimpleNamespace(name="attention_mask"),
            ]

        def run(self, output_names, feed_dict):
            self._call_count += 1
            seq_len = feed_dict.get("input_ids",
                                    feed_dict.get(self.get_inputs()[0].name,
                                                   np.array([[0]]))).shape[1]
            logits = np.zeros((1, seq_len, vocab), dtype=np.float32)
            # Emit token id 1 twice, then EOS.
            if self._call_count >= 3:
                logits[0, -1, self._eos] = 100.0
            else:
                logits[0, -1, 1] = 100.0
            return [logits]

    ve_path = str(blip_dir / "visual_encoder.onnx")
    td_path = str(blip_dir / "text_decoder.onnx")

    def _factory(path, providers=None):
        if "visual" in path:
            return _VisSession(path, providers=providers)
        return _DecSession(path, providers=providers)

    return _factory


# ── tests ─────────────────────────────────────────────────────────────────────

class TestTryVlmOnnx:
    """_try_vlm_onnx() returns a triple when the dir exists + ort installed,
    else None."""

    def test_returns_none_when_dir_absent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pixcull.models_manager.PIXCULL_HOME", tmp_path)
        C.reset()
        assert C._try_vlm_onnx() is None

    def test_returns_none_when_visual_encoder_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pixcull.models_manager.PIXCULL_HOME", tmp_path)
        d = tmp_path / "models" / "blip-onnx"
        d.mkdir(parents=True)
        (d / "text_decoder.onnx").write_bytes(b"x")
        # visual_encoder.onnx is missing
        C.reset()
        assert C._try_vlm_onnx() is None

    def test_returns_none_when_onnxruntime_absent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pixcull.models_manager.PIXCULL_HOME", tmp_path)
        d = tmp_path / "models"
        _make_onnx_dir(d)   # creates blip-onnx/ under d
        C.reset()
        # Hide onnxruntime via sys.modules — the import inside _try_vlm_onnx
        # checks for onnxruntime, so removing it from sys.modules and making
        # a future import raise ImportError is the cleanest approach.
        import sys
        import builtins

        real_import = builtins.__import__

        def _no_ort(name, *args, **kwargs):
            if name == "onnxruntime":
                raise ImportError("onnxruntime not installed (test)")
            return real_import(name, *args, **kwargs)

        # Also remove from sys.modules so the cached import doesn't bypass us.
        saved = sys.modules.pop("onnxruntime", None)
        try:
            with patch("builtins.__import__", side_effect=_no_ort):
                C.reset()
                result = C._try_vlm_onnx()
        finally:
            if saved is not None:
                sys.modules["onnxruntime"] = saved
        assert result is None

    def test_returns_triple_when_available(self, tmp_path, monkeypatch):
        models_root = tmp_path / "models"
        blip_dir = _make_onnx_dir(models_root)
        monkeypatch.setattr(
            "pixcull.models_manager.PIXCULL_HOME", tmp_path)
        factory = _make_session_factory(blip_dir)

        ort_stub = types.ModuleType("onnxruntime")
        ort_stub.InferenceSession = factory
        C.reset()
        with patch.dict("sys.modules", {"onnxruntime": ort_stub}):
            result = C._try_vlm_onnx()
        assert result is not None
        vis_sess, dec_sess, cfg = result
        assert cfg["image_size"] == 64
        assert cfg["max_length"] == 8

    def test_caches_result(self, tmp_path, monkeypatch):
        models_root = tmp_path / "models"
        blip_dir = _make_onnx_dir(models_root)
        monkeypatch.setattr(
            "pixcull.models_manager.PIXCULL_HOME", tmp_path)
        factory = _make_session_factory(blip_dir)
        call_count = [0]

        def _counting_factory(path, providers=None):
            call_count[0] += 1
            return factory(path, providers=providers)

        ort_stub = types.ModuleType("onnxruntime")
        ort_stub.InferenceSession = _counting_factory
        C.reset()
        with patch.dict("sys.modules", {"onnxruntime": ort_stub}):
            r1 = C._try_vlm_onnx()
            r2 = C._try_vlm_onnx()
        assert r1 is r2   # same cached object
        assert call_count[0] == 2   # two sessions built once total


class TestCaptionWithOnnx:
    """_caption_with_onnx() runs the full two-stage inference; returns str or None."""

    def _setup(self, tmp_path, monkeypatch, with_tokenizer=False):
        models_root = tmp_path / "models"
        blip_dir = _make_onnx_dir(models_root, with_tokenizer=with_tokenizer)
        monkeypatch.setattr(
            "pixcull.models_manager.PIXCULL_HOME", tmp_path)
        factory = _make_session_factory(blip_dir)
        ort_stub = types.ModuleType("onnxruntime")
        ort_stub.InferenceSession = factory
        C.reset()
        return blip_dir, ort_stub

    def test_returns_none_when_onnx_absent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pixcull.models_manager.PIXCULL_HOME", tmp_path)
        C.reset()
        # No blip-onnx dir → no sessions → should return None gracefully.
        result = C._caption_with_onnx("/nonexistent/frame.jpg")
        assert result is None

    def test_returns_string_with_fake_onnx(self, tmp_path, monkeypatch):
        pytest.importorskip("PIL")
        from PIL import Image

        blip_dir, ort_stub = self._setup(tmp_path, monkeypatch)
        # Create a tiny fake JPEG.
        img_path = tmp_path / "frame.jpg"
        Image.new("RGB", (64, 64), (100, 150, 200)).save(img_path)
        with patch.dict("sys.modules", {"onnxruntime": ort_stub}):
            result = C._caption_with_onnx(str(img_path))
        # We may get a token-id string or a cleaned caption — either way it
        # should be a non-empty string (the decode path ran without error).
        assert isinstance(result, str)

    def test_returns_none_on_bad_image(self, tmp_path, monkeypatch):
        _blip_dir, ort_stub = self._setup(tmp_path, monkeypatch)
        img_path = tmp_path / "bad.jpg"
        img_path.write_bytes(b"not an image")
        with patch.dict("sys.modules", {"onnxruntime": ort_stub}):
            result = C._caption_with_onnx(str(img_path))
        assert result is None


class TestVlmCaptionFromImage:
    """vlm_caption_from_image uses ONNX first, falls back to transformers, then None."""

    def test_onnx_path_wins(self, tmp_path, monkeypatch):
        """When _try_vlm_onnx succeeds, _caption_with_onnx is used."""
        # Patch _caption_with_onnx to return a known string.
        monkeypatch.setattr(C, "_caption_with_onnx",
                            lambda p: "A person smiles")
        C.reset()
        result = C.vlm_caption_from_image("/any/frame.jpg")
        assert result == "A person smiles"

    def test_falls_back_to_transformers_when_onnx_none(self, monkeypatch):
        """When ONNX returns None, the transformers VLM is tried."""
        monkeypatch.setattr(C, "_caption_with_onnx", lambda p: None)
        # Mock _try_vlm to return a fake (proc, model) pair.
        mock_proc = MagicMock()
        mock_model = MagicMock()
        mock_model.generate.return_value = [[1, 2, 3]]
        mock_proc.decode.return_value = "A bride looks back"
        monkeypatch.setattr(C, "_try_vlm", lambda: (mock_proc, mock_model))
        # Patch torch.no_grad and PIL.Image.open so no real files are needed.
        import torch
        monkeypatch.setattr(torch, "no_grad", MagicMock(
            return_value=MagicMock(__enter__=lambda s, *a: s,
                                   __exit__=lambda s, *a: None)))
        from unittest.mock import MagicMock as _MM
        pil_img = _MM()
        pil_img.convert.return_value = pil_img
        with patch("PIL.Image.open", return_value=pil_img):
            result = C.vlm_caption_from_image("/any/frame.jpg")
        assert result == "A bride looks back"

    def test_falls_back_to_none_when_both_absent(self, monkeypatch):
        """When neither ONNX nor transformers is available, return None."""
        monkeypatch.setattr(C, "_caption_with_onnx", lambda p: None)
        monkeypatch.setattr(C, "_try_vlm", lambda: None)
        C.reset()
        assert C.vlm_caption_from_image("/any/frame.jpg") is None


class TestReelCaptionOnnxIntegration:
    """End-to-end: vlm_caption_from_image wired through vlm_caption_bilingual
    and caption_bilingual."""

    def test_onnx_caption_propagates_to_vlm_bilingual(self, tmp_path, monkeypatch):
        # Plant a fake frame file.
        fd = tmp_path / "video_frames" / "v"
        fd.mkdir(parents=True)
        (fd / "frame_000001.jpg").write_bytes(b"x")
        monkeypatch.setattr(C, "vlm_caption_from_image",
                            lambda p: "A wedding moment")
        monkeypatch.setattr(C, "_try_llm", lambda: None)
        cand = _cand(best_frame_id="frame_000001", start_s=1.0, end_s=3.0)
        pair = C.vlm_caption_bilingual(cand, tmp_path)
        assert pair is not None
        zh, en = pair
        assert "wedding" in zh and "wedding" in en

    def test_caption_bilingual_source_is_vlm_when_onnx_fires(self, tmp_path,
                                                               monkeypatch):
        fd = tmp_path / "video_frames" / "v"
        fd.mkdir(parents=True)
        (fd / "frame_000001.jpg").write_bytes(b"x")
        monkeypatch.setattr(C, "vlm_caption_from_image",
                            lambda p: "Dogs playing in the park")
        monkeypatch.setattr(C, "_try_llm", lambda: None)
        cand = _cand(best_frame_id="frame_000001", start_s=2.0, end_s=4.0)
        zh, en, src = C.caption_bilingual(cand, tmp_path)
        assert src == "vlm"
        assert "Dogs" in zh

    def test_onnx_absent_falls_back_to_template(self, monkeypatch):
        """With no ONNX and no transformers VLM, template is the result."""
        monkeypatch.setattr(C, "_caption_with_onnx", lambda p: None)
        monkeypatch.setattr(C, "_try_vlm", lambda: None)
        monkeypatch.setattr(C, "_try_llm", lambda: None)
        cand = _cand()
        zh, en, src = C.caption_bilingual(cand)
        assert src == "template"
        assert zh and en

    def test_enrich_adds_why_semantic_en_with_onnx_source(
            self, tmp_path, monkeypatch):
        fd = tmp_path / "video_frames" / "v"
        fd.mkdir(parents=True)
        (fd / "frame_000001.jpg").write_bytes(b"x")
        monkeypatch.setattr(C, "vlm_caption_from_image",
                            lambda p: "Sunset over the mountains")
        monkeypatch.setattr(C, "_try_llm", lambda: None)
        cand = _cand(best_frame_id="frame_000001")
        out = C.enrich([cand], frames_root=tmp_path)
        c = out[0]
        assert c["caption_source"] == "vlm"
        assert "Sunset" in c["why_semantic"]
        assert c["why_semantic_en"]


class TestModelsManagerBlipOnnx:
    """blip-onnx is registered in REGISTRY; pull raises NotPublishedError."""

    def test_blip_onnx_in_registry(self):
        from pixcull.models_manager import REGISTRY, get_spec
        assert "blip-onnx" in REGISTRY
        spec = get_spec("blip-onnx")
        assert spec.filename == "blip-onnx"
        assert not spec.published     # no URL → opt-in local-only

    def test_pull_blip_onnx_raises_not_published(self):
        from pixcull.models_manager import NotPublishedError, pull
        with pytest.raises(NotPublishedError):
            pull("blip-onnx")

    def test_list_models_includes_blip_onnx(self, tmp_path):
        from pixcull.models_manager import list_models
        rows = list_models(base=tmp_path)
        names = {r.spec.name for r in rows}
        assert "blip-onnx" in names

    def test_reset_clears_onnx_cache(self):
        """reset() must zero out _vlm_onnx_probed so tests don't bleed state."""
        C._vlm_onnx_probed = True
        C._vlm_onnx = object()
        C.reset()
        assert C._vlm_onnx_probed is False
        assert C._vlm_onnx is None
