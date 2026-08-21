"""v2.50 — the public promises must match the shipped default.

The whole reason P1 and P5 had to land together is that they can fall
out of step silently.  Flip the default and the README lies; rewrite the
README first and it lies the other way.  A charter note saying "do these
together" is a promise, and promises rot.

So this is the mechanical version of that coupling.  It reads the actual
default out of the source, then asserts the public copy is consistent
with it — in both directions.  Change one without the other and the gate
goes red with a message naming the other file.

Scope note: this checks the *absolute* claims — "never", "100%", "no
uploads".  It deliberately does NOT ban the words "local" or "on-device",
because after v2.50 those are still true statements about a real,
supported mode (``--vlm-mode off``), and a lint that forbade them would
push the copy into pretending the local path does not exist.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# What does the code actually do?
# ---------------------------------------------------------------------------

def shipped_vlm_authority() -> str:
    """The default read out of ``decide``'s signature, not out of a doc."""
    src = (REPO / "pixcull" / "scoring" / "decision.py").read_text("utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "decide":
            names = [a.arg for a in node.args.kwonlyargs]
            if "vlm_authority" not in names:
                pytest.fail("decide() no longer takes vlm_authority")
            default = node.args.kw_defaults[names.index("vlm_authority")]
            assert isinstance(default, ast.Constant), (
                "vlm_authority's default is computed — this lint can no "
                "longer tell what ships")
            return str(default.value)
    pytest.fail("decide() not found")


def uploads_by_default() -> bool:
    """Does a plain `pixcull run` send photos anywhere?

    v2.58 — this read `vlm_authority`, which is the wrong variable. The
    authority level decides how much a verdict may CHANGE; whether one is
    requested at all is `vlm_mode`. With the two split, a future change
    that turned uploads on while leaving authority `off` would have kept
    this lint saying "nothing is uploaded".

    And the real gate is not the signature default either: `pixcull run`
    resolves `vlm_mode=None` to `"minimax"` when a key is present. So a
    machine with a key AND recorded consent uploads on a bare
    `pixcull run` — which is the honest answer, and the one the absolute
    claims below have to survive.
    """
    src = (REPO / "pixcull" / "cli.py").read_text("utf-8")
    return 'vlm_mode = "minimax" if api_key_from_env()' in src


# ---------------------------------------------------------------------------
# What does the product say?
# ---------------------------------------------------------------------------

#: Claims that are absolute. Each is (pattern, human name). These may
#: only appear while nothing is uploaded by default.
_ABSOLUTE_CLAIMS = [
    (r"[Nn]o photo ever leaves your disk", "no photo ever leaves your disk"),
    (r"[Pp]hotos never leave your disk", "photos never leave your disk"),
    (r"photos%20never%20upload", "the never-upload badge"),
    (r"no uploads, no cloud", "no uploads, no cloud"),
    (r"原图永远不离开", "原图永远不离开"),
    (r"照片永远不出本机", "照片永远不出本机"),
    (r"照片永不上传", "照片永不上传"),
    (r"原图不上传", "原图不上传"),
    (r"100%\s*本地运行", "100% 本地运行"),
    (r"100%\s*locally", "everything runs 100% locally"),
    (r"100\s*%\s*lokal", "100% lokal"),
    (r"100\s*%\s*en local", "100% en local"),
    (r"100\s*%\s*local", "100% local"),
    (r"100%\s*in locale", "100% in locale"),
    (r"100%\s*ローカル", "100% ローカル"),
    (r"100%\s*로컬", "100% 로컬"),
    (r"100%\s*lokaal", "100% lokaal"),
    (r"100%\s*локально", "100% локально"),
    (r"%100\s*yerel", "%100 yerel"),
    (r"محلياً\s*100%", "محلياً 100%"),
]

#: Files whose copy is a promise to the public.
_PUBLIC = (
    "README.md", "README-PYPI.md", "modelscope/README.md", "SECURITY.md",
    "pyproject.toml",
    "docs/launch-post-en.md",
    "pixcull/report/templates/pages/upload.html",
    "pixcull/report/templates/results.html",
)


def _public_files() -> list[Path]:
    out = [REPO / p for p in _PUBLIC]
    out += sorted((REPO / "pixcull" / "locale").glob("*.json"))
    return [p for p in out if p.exists()]


def test_absolute_no_upload_claims_match_the_default():
    """The coupling, enforced.

    If this fails after a default flip, the fix is not to weaken the
    lint — it is to rewrite the copy the message names.
    """
    uploads = uploads_by_default()
    offenders: list[str] = []
    for path in _public_files():
        text = path.read_text("utf-8", errors="ignore")
        for pattern, name in _ABSOLUTE_CLAIMS:
            for m in re.finditer(pattern, text):
                line = text[:m.start()].count("\n") + 1
                offenders.append(
                    f"{path.relative_to(REPO)}:{line} — “{name}”")
    if uploads:
        assert not offenders, (
            f"vlm_authority ships as {shipped_vlm_authority()!r}, so photos "
            f"ARE uploaded by default — these absolute claims are now "
            f"false and must be rewritten:\n  " + "\n  ".join(offenders))
    # When nothing uploads by default the claims are true; nothing to check.


def test_pyproject_keywords_match_the_default():
    text = (REPO / "pyproject.toml").read_text("utf-8")
    kw = re.search(r"keywords\s*=\s*\[(.*?)\]", text, re.S)
    assert kw, "keywords block is gone"
    banned = {"local-first", "on-device-ai"}
    present = banned & set(re.findall(r'"([^"]+)"', kw.group(1)))
    if uploads_by_default():
        assert not present, (
            f"PyPI indexes these and people search on them: {present}. "
            f"With cloud judging on by default they misdescribe the "
            f"package to exactly the users who would most object.")


def test_the_local_only_escape_hatch_still_exists():
    """After v2.50 this is the load-bearing honesty claim.

    "Cloud by default" is only defensible while a real, documented,
    fully-functional local path remains — for photographers whose
    contracts forbid third-party cloud processing. If `off` ever stops
    being accepted, the copy promising it becomes the new lie.
    """
    from pixcull.config import PixCullConfig
    from pixcull.scoring.decision import Decision, decide

    cfg = PixCullConfig.load()
    # v2.68 — the claim is "the judge does not reach the decision", so it
    # is asserted against the no-judge verdict. Pinning it to CULL tied
    # an honesty guarantee to a rule-stack threshold, and the guarantee
    # then failed when that threshold moved for unrelated reasons.
    local_only, _ = decide(0.72, ["closed_eyes"], cfg, scene="portrait")
    dec, reasons = decide(0.72, ["closed_eyes"], cfg, scene="portrait",
                          vlm_label="keep", vlm_axes={"technical": 5},
                          vlm_authority="off")
    assert dec is local_only, (
        "vlm_authority='off' no longer means 'ignore the cloud judge'")
    assert not any("vlm" in r for r in reasons)
    # And it is a real decision, not a degenerate one: a judge saying
    # "keep" on a flagged frame must be able to differ from `off`.
    with_judge, _ = decide(0.72, ["closed_eyes"], cfg, scene="portrait",
                           vlm_label="keep", vlm_axes={"technical": 5},
                           vlm_authority="primary")
    assert with_judge is not local_only, (
        "`off` and `primary` agree here, so this asserts nothing")


def test_cli_documents_that_photos_are_uploaded():
    """A user turning this on must be told, in the help text, what it does."""
    import inspect

    from pixcull.cli import run as run_cmd

    # The NAME comes from the parser — Rich wraps it across lines on a
    # narrow console, which failed on CI while passing locally (v2.57.1).
    # The WORDING still has to be read out of the help string, because
    # that is the thing a user actually sees.
    prm = inspect.signature(run_cmd).parameters["vlm_mode"]
    decls = set(getattr(prm.default, "param_decls", None) or [])
    assert "--vlm-mode" in decls, f"option renamed or gone: {decls}"
    assert re.search(r"upload", str(getattr(prm.default, "help", "")), re.I), (
        "--vlm-mode's help does not say photos are uploaded")


@pytest.mark.parametrize("path", sorted(
    (REPO / "pixcull" / "locale").glob("*.json")), ids=lambda p: p.stem)
def test_every_locale_says_the_same_thing_about_uploads(path):
    """13 languages drift independently; that is how one gets forgotten."""
    d = json.loads(path.read_text("utf-8"))
    foot = d.get("tour.foot", "")
    assert foot, f"{path.name} lost tour.foot"
    if uploads_by_default():
        for pattern, name in _ABSOLUTE_CLAIMS:
            assert not re.search(pattern, foot), (
                f"{path.name} still claims “{name}” in the onboarding tour, "
                f"which every user sees on first open")


def test_the_lint_would_actually_fire(tmp_path):
    """A guard nobody has seen fail is a guard nobody can trust."""
    specimen = "No photo ever leaves your disk. 全部能力 100% 本地运行。"
    hits = [name for pattern, name in _ABSOLUTE_CLAIMS
            if re.search(pattern, specimen)]
    assert len(hits) >= 2, f"the patterns match nothing real: {hits}"


def test_eval_accepts_more_than_one_review_pass():
    """v2.53.2 — ``--review`` was a single Path, so passing two review
    files silently kept only the last one.

    The failure mode is the worst kind this repo has: it does not error,
    it reports a *smaller* evidence base as though it were the whole one.
    Two review passes exist precisely because one was not enough.
    """
    import inspect

    from pixcull.cli import m3_eval

    ann = inspect.signature(m3_eval).parameters["review"].annotation
    assert "list" in str(ann).lower(), (
        f"--review is {ann}, not a list: a second --review would silently "
        "replace the first instead of merging")


def test_the_three_authority_defaults_cannot_diverge():
    """`decide`, `run_pipeline` and the CLI each carry this default.

    v2.58 lowered it from `primary` to `off`. Changing only `decide()`
    would have been decoration: `run_pipeline` has its own default and
    that is what every real run passes down, so the shipped behaviour
    would not have moved an inch while the signature suggested it had.

    Pinned mechanically because three copies of one decision is exactly
    how a repo ends up with a documented default nothing implements.
    """
    import inspect

    from pixcull.cli import run as run_cmd
    from pixcull.pipeline.orchestrator import run_pipeline
    from pixcull.scoring.decision import decide

    got = {
        "decide": inspect.signature(decide).parameters[
            "vlm_authority"].default,
        "run_pipeline": inspect.signature(run_pipeline).parameters[
            "vlm_authority"].default,
    }
    cli_default = inspect.signature(run_cmd).parameters["vlm_authority"].default
    got["cli"] = getattr(cli_default, "default", cli_default)

    assert len(set(got.values())) == 1, (
        f"the authority default disagrees across layers: {got}. The one "
        f"that governs a real run is run_pipeline's.")
    assert got["decide"] == "primary", (
        f"shipped authority is {got['decide']!r}. v2.64 moved it to "
        f"`primary` on 394 blind frames: it destroys 15 keepers against "
        f"the rule stack's 126, finds 4 culls against 5, and gains +14.6 "
        f"macro-F1 with a 95% CI of [+6.8, +23.1]. If that changed, change "
        f"this test WITH the evidence.")


def test_turning_the_judge_on_without_authority_says_so():
    """A paid no-op has to announce itself.

    `--vlm-mode minimax` with the new `off` authority uploads photos,
    scores them, and changes no decision. That is a legitimate mode — the
    reasoning still lands in the report — but "I turned the model on and
    nothing happened" must not be left for the user to work out.
    """
    import inspect

    from pixcull.cli import run as run_cmd

    src = inspect.getsource(run_cmd)
    assert 'vlm_mode != "off" and vlm_authority == "off"' in src, (
        "nothing detects the judge-on/authority-off combination")
    assert "Advisory only" in src, "the combination is not reported"
