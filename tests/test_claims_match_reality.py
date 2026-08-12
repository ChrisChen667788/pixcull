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
    return shipped_vlm_authority() != "off"


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
    dec, reasons = decide(0.72, ["closed_eyes"], cfg, scene="portrait",
                          vlm_label="keep", vlm_axes={"technical": 5},
                          vlm_authority="off")
    assert dec is Decision.CULL, (
        "vlm_authority='off' no longer means 'ignore the cloud judge'")
    assert not any("vlm" in r for r in reasons)


def test_cli_documents_that_photos_are_uploaded():
    """A user turning this on must be told, in the help text, what it does."""
    from typer.testing import CliRunner

    from pixcull.cli import app
    out = CliRunner().invoke(app, ["run", "--help"]).output
    assert "--vlm-mode" in out
    assert re.search(r"upload", out, re.I), (
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
