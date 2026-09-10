"""v3.69 — the names PixCull answers to, and a warning when you use another.

Fifty-five ``PIXCULL_*`` variables are read across the package, the
scripts and the workflows, and nothing checked that the one you set was
one of them. An unrecognised name is accepted by the shell, ignored by
the product, and never mentioned again.

That is a nuisance for most settings and a privacy failure for one. The
switch deciding whether photographs are uploaded for cloud judging was
reachable only as a CLI flag, ``--vlm-mode off``. Meanwhile
``PIXCULL_VLM_MODEL``, ``PIXCULL_VLM_API_KEY`` and ``PIXCULL_VLM_WORKERS``
all exist — so ``PIXCULL_VLM_MODE`` is both the obvious guess and one
character from a real name. Setting it did nothing, said nothing, and the
photographs went to the judge.

Found by doing exactly that while testing the offline path. Nothing left
the machine that time, but only because the verdict cache happened to be
warm — the setting had no part in it.

Two changes: ``--vlm-mode`` reads ``PIXCULL_VLM_MODE`` now, and anything
matching ``PIXCULL_*`` that is not on this list is reported at startup
with the nearest real name.
"""
from __future__ import annotations

import difflib
import os
import sys

#: Every ``PIXCULL_*`` name the tree reads, with what it is for. Kept in
#: step with the source by tests/test_env_registry.py, which re-derives
#: the set and fails on either direction of drift — a registry nobody is
#: forced to update is a registry that stops describing the program.
KNOWN: dict[str, str] = {
    "PIXCULL_ADVISE_CULL":          "include culled frames in the advice pass",
    "PIXCULL_API_CORS_ORIGINS":     "allowed CORS origins for the review server",
    "PIXCULL_API_KEY":              "API key for the containerised server",
    "PIXCULL_APPCAST_URL":          "Sparkle appcast URL for the desktop app",
    "PIXCULL_ASPECT_GUARD":         "aspect-ratio guard in near-duplicate matching",
    "PIXCULL_AUDIO_MODEL":          "audio tagger model id",
    "PIXCULL_AUDIO_SYNC":           "enable audio-to-moment sync",
    "PIXCULL_AXIS_GROUPS":          "axis grouping strategy",
    "PIXCULL_BURST_MULTI_IMAGE":    "send a whole burst to the judge in one call",
    "PIXCULL_CONSISTENCY_DRAWS":    "repeat draws for the consistency measurement",
    "PIXCULL_CRITIQUE_EXEMPLARS":   "exemplar bank for the critique pass",
    "PIXCULL_DATA_DIR":             "data directory for the containerised server",
    "PIXCULL_DEBUG":                "verbose server logging",
    "PIXCULL_DEMO_ROOT":            "root the demo server serves from",
    "PIXCULL_DETECTOR_CACHE":       "detector cache on/off",
    "PIXCULL_DETECTOR_CACHE_DIR":   "detector cache location",
    "PIXCULL_DISABLE_QUOTA":        "bypass the licence quota (development)",
    "PIXCULL_ENV":                  "environment name reported in telemetry",
    "PIXCULL_HOME":                 "PixCull home directory (models, caches)",
    "PIXCULL_INLINE_ROWS":          "how many rows the first paint inlines",
    "PIXCULL_KEYWORD_PREFIX":       "prefix for IPTC keywords written back",
    "PIXCULL_LIBRARY_DIR":          "cross-run library index location",
    "PIXCULL_LICENSE_API":          "licence server base URL",
    "PIXCULL_LICENSE_KEY":          "licence key for issuing scripts",
    "PIXCULL_LLM_BUDGET_YUAN":      "daily cloud-judging spend ceiling",
    "PIXCULL_LOG_LEVEL":            "logging level",
    "PIXCULL_MEASURE_STRIP":        "measure the film-strip effect",
    "PIXCULL_MLX_WHISPER_MODEL":    "MLX Whisper model id for transcription",
    "PIXCULL_NL_EXPLAIN":           "natural-language explanations on/off",
    "PIXCULL_NL_MODEL_PATH":        "local GGUF model for explanations",
    "PIXCULL_NOTARY_PROFILE":       "notarytool keychain profile (release only)",
    "PIXCULL_NO_AUTO_INDEX":        "skip adding the run to the library index",
    "PIXCULL_PLUGINS_AUTOLOAD":     "autoload plugins on start",
    "PIXCULL_PORT":                 "port for the screenshot capture server",
    "PIXCULL_RAW_TRANSCODER":       "RAW transcoder backend",
    "PIXCULL_REEL_CAPTION":         "reel captioning on/off",
    "PIXCULL_REEL_VLM":             "reel VLM backend (ModelScope Studio)",
    "PIXCULL_RESOLUTION_ROUTER":    "resolution routing strategy",
    "PIXCULL_SENTRY_DSN":           "Sentry DSN for error reporting",
    "PIXCULL_SIGN_IDENTITY":        "codesign identity (release only)",
    "PIXCULL_SMOKE_RUN":            "run directory for the visual smoke test",
    "PIXCULL_STRIPE_WEBHOOK_SECRET": "Stripe webhook secret (licence issuing)",
    "PIXCULL_SYNC_DIR":             "multi-machine sync directory",
    "PIXCULL_TELEMETRY":            "telemetry on/off",
    "PIXCULL_TEST_DEMO_ROOT":       "demo root for fixture generation",
    "PIXCULL_TEST_RUN":             "run id for fixture generation",
    "PIXCULL_TETHER_XMP":           "write XMP sidecars in tether mode",
    "PIXCULL_UNSPLASH_PING":        "allow the Unsplash reachability ping",
    "PIXCULL_USER":                 "current user for multi-user runs",
    "PIXCULL_VERTICAL_AXIS_PRIOR":  "per-vertical axis prior on/off",
    "PIXCULL_VLM_API_KEY":          "API key for the cloud judge",
    "PIXCULL_VLM_MODE":             "off | minimax | local — WHETHER PHOTOGRAPHS ARE UPLOADED",
    "PIXCULL_VLM_MODEL":            "captioning model id",
    "PIXCULL_VLM_WORKERS":          "concurrent cloud-judge workers",
    "PIXCULL_WECHAT_APIV3_KEY":     "WeChat Pay APIv3 key (licence issuing)",
    "PIXCULL_WORKERS":              "worker processes for analysis",
}

#: Settings where being ignored means photographs may leave the machine.
#: Named so the message can say what is at stake instead of "unknown
#: option": the cost of a typo is not the same for every name here.
PRIVACY_RELEVANT = frozenset({
    "PIXCULL_VLM_MODE", "PIXCULL_VLM_API_KEY", "PIXCULL_TELEMETRY",
    "PIXCULL_SENTRY_DSN", "PIXCULL_UNSPLASH_PING",
})


def unknown_variables(environ=None) -> list[tuple[str, str | None]]:
    """``[(name, nearest_known_or_None)]`` for every unrecognised name."""
    env = os.environ if environ is None else environ
    out = []
    for name in sorted(env):
        if not name.startswith("PIXCULL_") or name in KNOWN:
            continue
        near = difflib.get_close_matches(name, KNOWN, n=1, cutoff=0.75)
        out.append((name, near[0] if near else None))
    return out


def warn_about_unknown_variables(environ=None, stream=None) -> int:
    """Report unrecognised ``PIXCULL_*`` names. Returns how many.

    A warning rather than an error on purpose: people wrap this tool in
    scripts of their own and a shared prefix is not ours to forbid. But
    it is printed for every one, and when the nearest real name is a
    privacy setting it says so, because the failure that prompted this
    was silent in exactly that case.
    """
    stream = stream or sys.stderr
    unknown = unknown_variables(environ)
    if not unknown:
        return 0
    print("\n⚠ PixCull: this environment sets names PixCull does not read:",
          file=stream)
    for name, near in unknown:
        if near:
            note = f"did you mean {near}?"
            if near in PRIVACY_RELEVANT:
                note += ("  ← that one decides whether photographs leave "
                         "this machine; as typed it has no effect")
            print(f"    {name} — {note}", file=stream)
        else:
            print(f"    {name} — not a PixCull setting", file=stream)
    # Not "run `pixcull doctor`" — there is no such command. Writing
    # that here, inside the fix for a setting that silently did nothing,
    # would have been the same defect one layer down. The names are in
    # KNOWN above and in docs/USER-GUIDE.md.
    print("  Every name PixCull reads is listed in docs/USER-GUIDE.md.\n",
          file=stream)
    return len(unknown)
