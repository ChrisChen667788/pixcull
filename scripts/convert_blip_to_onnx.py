#!/usr/bin/env python3
"""v2.7 — export Salesforce/blip-image-captioning-base to ONNX for PixCull.

This is an **opt-in offline tool**.  Run it once on a machine that has the
full transformers + torch stack (or optimum) installed, then the resulting
ONNX is picked up automatically by ``pixcull video`` — no transformers needed
at inference time, only ``onnxruntime``.

Output layout::

    ~/.pixcull/models/blip-onnx/
        visual_encoder.onnx   — ViT image encoder: [1,3,H,W] → [1,S,768]
        text_decoder.onnx     — causal LM decoder: input_ids + encoder_hidden
                                states + attention_mask → next-token logits
        config.json           — vocab_size, max_length, bos/eos/pad ids

Usage (throwaway venv — keep heavy deps out of the project venv)::

    python3 -m venv /tmp/blipconv
    /tmp/blipconv/bin/pip install \\
        "transformers>=4.37" torch "optimum[exporters]" Pillow

    # preferred path (cleaner, handles dynamic axes):
    /tmp/blipconv/bin/python scripts/convert_blip_to_onnx.py \\
        --model Salesforce/blip-image-captioning-base \\
        --out ~/.pixcull/models/blip-onnx

    # fallback if optimum not available (torch.onnx):
    /tmp/blipconv/bin/python scripts/convert_blip_to_onnx.py \\
        --model Salesforce/blip-image-captioning-base \\
        --out ~/.pixcull/models/blip-onnx \\
        --no-optimum

After export ``pixcull`` detects the directory automatically; re-run with
``--force`` to overwrite an existing export.

Dependencies (conversion only — NOT required to *run* the ONNX):
    transformers>=4.37, torch>=2.0, Pillow
    optimum[exporters]  (preferred; pip install optimum[exporters])

This script is NOT executed by CI.  It is a developer tool for creating the
optional self-hosted ONNX artefact.  The runtime side (onnxruntime) is
deliberately kept separate so that the PixCull main venv stays lean.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


_DEFAULT_MODEL = "Salesforce/blip-image-captioning-base"
_DEFAULT_OUT = Path.home() / ".pixcull" / "models" / "blip-onnx"


def _export_with_optimum(model_id: str, out_dir: Path) -> None:
    """Export via optimum.exporters.onnx — handles dynamic axes cleanly."""
    from optimum.exporters.onnx import main_export  # type: ignore
    main_export(
        model_name_or_path=model_id,
        output=str(out_dir),
        task="image-to-text",
        opset=14,
        no_post_process=False,
    )
    print(f"[optimum] exported to {out_dir}")


def _export_with_torch(model_id: str, out_dir: Path) -> None:
    """Fallback: manual torch.onnx export of the two BLIP sub-graphs."""
    import torch  # noqa: F401
    from transformers import BlipForConditionalGeneration, BlipProcessor

    print(f"[torch.onnx] loading {model_id} …")
    proc = BlipProcessor.from_pretrained(model_id)
    model = BlipForConditionalGeneration.from_pretrained(model_id)
    model.eval()

    image_size = proc.image_processor.size.get("height", 384)

    # ── visual encoder ────────────────────────────────────────────────────
    vis_enc = model.vision_model
    dummy_pixel = torch.zeros(1, 3, image_size, image_size)

    ve_path = out_dir / "visual_encoder.onnx"
    torch.onnx.export(
        vis_enc,
        (dummy_pixel,),
        str(ve_path),
        input_names=["pixel_values"],
        output_names=["last_hidden_state"],
        dynamic_axes={
            "pixel_values": {0: "batch"},
            "last_hidden_state": {0: "batch"},
        },
        opset_version=14,
        do_constant_folding=True,
    )
    print(f"  visual encoder → {ve_path} ({ve_path.stat().st_size:,} bytes)")

    # ── text decoder (one step) ────────────────────────────────────────────
    # Export the language model head for a single greedy step.
    class _DecoderStep(torch.nn.Module):
        def __init__(self, blip_model):
            super().__init__()
            self.text_decoder = blip_model.text_decoder

        def forward(self, input_ids, encoder_hidden_states, attention_mask):
            out = self.text_decoder(
                input_ids=input_ids,
                encoder_hidden_states=encoder_hidden_states,
                attention_mask=attention_mask,
            )
            return out.logits

    seq_len = 1
    hidden = model.config.text_config.hidden_size
    enc_seq = 577  # ViT-base 384px patch grid + CLS
    dummy_ids = torch.zeros(1, seq_len, dtype=torch.long)
    dummy_enc = torch.zeros(1, enc_seq, hidden)
    dummy_mask = torch.ones(1, enc_seq, dtype=torch.long)

    dec_step = _DecoderStep(model)
    td_path = out_dir / "text_decoder.onnx"
    torch.onnx.export(
        dec_step,
        (dummy_ids, dummy_enc, dummy_mask),
        str(td_path),
        input_names=["input_ids", "encoder_hidden_states", "attention_mask"],
        output_names=["logits"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "seq"},
            "encoder_hidden_states": {0: "batch"},
            "attention_mask": {0: "batch"},
            "logits": {0: "batch", 1: "seq"},
        },
        opset_version=14,
        do_constant_folding=True,
    )
    print(f"  text decoder   → {td_path} ({td_path.stat().st_size:,} bytes)")

    # ── config sidecar ────────────────────────────────────────────────────
    cfg = model.config
    tc = cfg.text_config
    config_data = {
        "model_id": model_id,
        "image_size": image_size,
        "vocab_size": tc.vocab_size,
        "max_length": 30,
        "bos_token_id": tc.bos_token_id,
        "eos_token_id": tc.sep_token_id,
        "pad_token_id": tc.pad_token_id,
    }
    cfg_path = out_dir / "config.json"
    cfg_path.write_text(json.dumps(config_data, indent=2), encoding="utf-8")
    print(f"  config         → {cfg_path}")


def convert(model_id: str, out_dir: Path, *,
            use_optimum: bool = True, force: bool = False) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    marker = out_dir / "config.json"
    if marker.exists() and not force:
        print(f"Already exported at {out_dir}  (pass --force to overwrite)")
        return

    if use_optimum:
        try:
            _export_with_optimum(model_id, out_dir)
            return
        except ImportError:
            print("[optimum] not installed — falling back to torch.onnx")
        except Exception as exc:
            print(f"[optimum] failed ({exc}) — falling back to torch.onnx")

    _export_with_torch(model_id, out_dir)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--model", default=_DEFAULT_MODEL,
                    help="HuggingFace model id (default: %(default)s)")
    ap.add_argument("--out", type=Path, default=_DEFAULT_OUT,
                    help="output directory (default: %(default)s)")
    ap.add_argument("--no-optimum", dest="use_optimum",
                    action="store_false", default=True,
                    help="skip optimum and use torch.onnx directly")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing export")
    args = ap.parse_args()

    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    convert(args.model, args.out, use_optimum=args.use_optimum, force=args.force)
    print(f"\nDone.  PixCull will auto-detect {args.out} at runtime.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
