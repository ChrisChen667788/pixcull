"""v3.94.2 — what the client sees is text and photographs, not boxes.

Re-checking every report from the contributor of PR #4 against main found
their CJK-watermark fix holding for Chinese on Windows and macOS, and
three ways it still drew boxes, silently: Korean on a Mac (the first CJK
font there has no Hangul), anything CJK in PixCull's own Docker image (no
CJK font installed), and the contact-sheet PDF, whose font list had no CJK
font at all. Each font was taken because it *opened*. The choice is now
made against the text, see pixcull/utils/fonts.py.

The same file held a worse one: since v2.56.2 every cell of every contact
sheet said "(image unavailable)". `ImageOps` was imported inside another
function, the NameError landed in the cell's `except`, and the only test
of that path checked a missing image was handled gracefully.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from pixcull.utils import fonts

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_RUN = ROOT / "samples" / "output"


@pytest.fixture(autouse=True)
def _fresh_choice():
    """The choice is cached per text; a monkeypatched one must not leak."""
    for f in (fonts._choose, fonts._warn, fonts._discovered):
        f.cache_clear()
    yield
    for f in (fonts._choose, fonts._warn, fonts._discovered):
        f.cache_clear()


# ------------------------------------------------------------ the measure


def test_a_missing_glyph_is_told_apart_from_a_drawn_one():
    """Pillow's bundled font is Latin-only, which makes it the control:
    the measure has to pass its letters and flag every CJK character."""
    font = fonts._bundled(32)
    assert fonts.missing_glyphs(font, "ZHANG PROOF 0123") == []
    assert fonts.missing_glyphs(font, "张 스 ス") == ["张", "스", "ス"]


# ------------------------------------------------------------ the choice


def _fake_fonts(monkeypatch, coverage: dict[str, set[str]]):
    """Candidates that open, each claiming only the characters given.

    Each is a real (bundled) font underneath, so an export can draw with
    it; only what it reports as drawable is faked."""
    import PIL.ImageFont as ImageFont
    real_truetype = ImageFont.truetype
    made: dict[int, str] = {}

    def truetype(path, size, *a, **k):
        if isinstance(path, str):
            if path not in coverage:
                raise OSError(path)
            font = fonts._bundled(size)
            made[id(font)] = path
            return font
        return real_truetype(path, size, *a, **k)     # load_default's own call

    def missing(font, text):
        drawn = coverage.get(made.get(id(font)), set(
            c for c in text if c.isascii()))
        return [c for c in dict.fromkeys(text)
                if not c.isspace() and c not in drawn]

    monkeypatch.setattr(ImageFont, "truetype", truetype)
    monkeypatch.setattr(fonts, "candidates", lambda latin_first=False: tuple(coverage))
    monkeypatch.setattr(fonts, "missing_glyphs", missing)


def test_a_font_that_opens_but_cannot_draw_the_text_is_passed_over(monkeypatch):
    """The bug in one line: Hiragino Sans GB opened, so Korean got it."""
    _fake_fonts(monkeypatch, {"zh-only": set("张三婚礼"),
                              "ko-too": set("张三婚礼스튜디오")})
    assert fonts._choose("스튜디오") == ("ko-too", ())
    assert fonts.unrenderable("스튜디오") == ""


def test_text_every_font_draws_keeps_the_first_one(monkeypatch):
    """No change for a Latin watermark: the preferred font still wins."""
    _fake_fonts(monkeypatch, {"first": set("PROOF"), "second": set("PROOF")})
    assert fonts._choose("PROOF")[0] == "first"


def test_when_nothing_draws_it_all_the_closest_is_used_and_the_gap_named(
        monkeypatch, caplog):
    _fake_fonts(monkeypatch, {"none": set(), "most": set("张三婚")})
    with caplog.at_level("WARNING", logger="pixcull.utils.fonts"):
        fonts.font_for("张三婚礼", 20)
        fonts.font_for("张三婚礼", 40)
    assert fonts._choose("张三婚礼") == ("most", ("礼",))
    assert fonts.unrenderable("张三婚礼") == "礼"
    warnings = [r for r in caplog.records if "礼" in r.getMessage()]
    assert len(warnings) == 1, "warned per call instead of once"
    assert "fonts-wqy-microhei" in warnings[0].getMessage()


def test_the_contact_sheet_keeps_its_latin_face_for_latin_text(monkeypatch):
    """Choosing by coverage must not restyle what already worked: the
    contact sheet has always drawn Latin text in Arial, the watermark in
    the system's CJK face. Only text a font cannot draw moves it."""
    real_candidates = fonts.candidates
    _fake_fonts(monkeypatch, {"cjk": set("PixCull-run张三"), "latin": set("PixCull-run")})
    monkeypatch.setattr(fonts, "candidates", real_candidates)
    monkeypatch.setattr(fonts, "CJK_FONTS", ("cjk",))
    monkeypatch.setattr(fonts, "LATIN_FONTS", ("latin",))
    monkeypatch.setattr(fonts, "_discovered", lambda: ())
    assert fonts._choose("PixCull-run", True)[0] == "latin"
    assert fonts._choose("PixCull-run张三", True)[0] == "cjk"
    assert fonts._choose("PixCull-run", False)[0] == "cjk", "the watermark's order moved"


def test_with_no_font_at_all_the_bundled_one_still_exports(monkeypatch):
    _fake_fonts(monkeypatch, {})
    assert fonts._choose("PROOF") == (None, ())
    assert fonts.font_for("PROOF", 24) is not None
    assert fonts.unrenderable("张三") == "张三"


# ------------------------------------------------------------ real fonts


def _any_cjk_font() -> bool:
    return any(os.path.exists(p) for p in fonts.CJK_FONTS) or bool(fonts._discovered())


@pytest.mark.skipif(not _any_cjk_font(), reason="no CJK font installed on this machine")
@pytest.mark.parametrize("lang,text", [
    ("zh", "张三婚礼写真工作室"),
    ("zh-Hant", "張三婚禮寫真攝影"),
    ("ja", "スタジオありがとう写真"),
    ("ko", "스튜디오 사진관"),
])
def test_each_cjk_language_is_drawn_by_the_fonts_this_machine_has(lang, text):
    """Real fonts, real glyphs. Korean is the case that was boxes on a Mac.
    CI installs fonts-wqy-microhei (the Docker image's font) so this runs
    there too; see the lane test below."""
    # Measured on the font actually handed out, not read back from the
    # chooser's own bookkeeping: with the choice broken to "first font that
    # opens", the chooser reported nothing missing and a check of
    # unrenderable() passed while Korean came out as boxes.
    font = fonts.font_for(text, 48)
    missing = fonts.missing_glyphs(font, text)
    assert missing == [], (
        f"{lang}: {''.join(missing)!r} drawn as boxes by {fonts._choose(text)[0]}")


def test_ci_installs_the_font_the_docker_image_ships():
    """Without it the real-font test above would skip on CI, and a test
    that only runs on the maintainer's Mac guards nothing on Linux."""
    import yaml
    wf = yaml.safe_load((ROOT / ".github/workflows/tests.yml").read_text("utf-8"))
    steps = wf["jobs"]["pytest"]["steps"]
    runs = " ".join(str(s.get("run", "")) for s in steps)
    assert re.search(r"apt-get install[^\n]*\bfonts-wqy-microhei\b", runs), (
        "the hermetic lane no longer installs fonts-wqy-microhei")


# ------------------------------------------------------------ docker


_PACKAGE_FONT = {
    "fonts-wqy-microhei": "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "fonts-wqy-zenhei": "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "fonts-noto-cjk": "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
}


def _apt_packages(dockerfile: str) -> set[str]:
    # Docker drops whole comment lines inside a continued RUN, newline and all.
    text = re.sub(r"(?m)^[ \t]*#[^\n]*\n", "", dockerfile).replace("\\\n", " ")
    pkgs: set[str] = set()
    for m in re.finditer(r"apt-get install([^&\n]*)", text):
        pkgs |= {w for w in m.group(1).split() if not w.startswith("-")}
    return pkgs


def test_the_docker_image_installs_a_cjk_font_the_lookup_knows():
    """python:3.12-slim has no fonts at all. Measured before this release:
    a Chinese watermark in the image drew every character as a box."""
    pkgs = _apt_packages((ROOT / "Dockerfile").read_text("utf-8"))
    shipped = [p for p in pkgs if p in _PACKAGE_FONT]
    assert shipped, f"Dockerfile installs no CJK font package: {sorted(pkgs)}"
    assert any(_PACKAGE_FONT[p] in fonts.CJK_FONTS for p in shipped), (
        "the font the image installs is not where the lookup looks")
    assert any(p in fonts.INSTALL_HINT for p in shipped), (
        "the hint tells users to install a font the image does not carry")


def test_the_apt_parser_reads_a_continued_install_line():
    assert _apt_packages("RUN apt-get install -y \\\n  libgl1 \\\n"
                         "  # a comment\n  fonts-wqy-microhei \\\n"
                         "  && rm -rf x") == {"libgl1", "fonts-wqy-microhei"}


# ------------------------------------------------------------ proof sheet


def test_the_proof_sheet_reports_characters_it_drew_as_boxes(tmp_path, monkeypatch):
    from PIL import Image
    from pixcull.export.proof_sheet import write_proof_sheet
    src = tmp_path / "a.jpg"
    Image.new("RGB", (1200, 800), (90, 120, 160)).save(src)
    rows = [{"filename": "a.jpg", "decision": "keep", "orig_filename": "a.jpg"}]
    _fake_fonts(monkeypatch, {"latin": set("ZHANG PROOF")})
    boxed = write_proof_sheet(rows, tmp_path / "zh", resolve=lambda _f: src,
                              title="张三婚礼")
    fine = write_proof_sheet(rows, tmp_path / "en", resolve=lambda _f: src,
                             title="ZHANG")
    assert boxed["written"] == fine["written"] == 1
    assert boxed["unrenderable"] == "张三婚礼"
    assert fine["unrenderable"] == ""


@pytest.mark.skipif(not (SAMPLE_RUN / "scores.csv").is_file(),
                    reason="sample run not present")
def test_the_proof_sheet_command_says_so_before_it_is_sent(tmp_path, monkeypatch):
    """The watermark is on every frame the client sees; the photographer
    hears about boxes in it from the command, not from the client."""
    from typer.testing import CliRunner
    from pixcull.cli import app
    _fake_fonts(monkeypatch, {"latin": set("ZHANG PROOF")})
    res = CliRunner().invoke(app, ["proof-sheet", str(SAMPLE_RUN),
                                   "--out", str(tmp_path / "ps"),
                                   "--title", "张三婚礼"])
    assert res.exit_code == 0, res.output
    assert "张 三 婚 礼 as boxes" in res.output, res.output
    assert "fonts-wqy-microhei" in res.output


def test_numbering_five_hundred_photos_chooses_a_font_once():
    """Review of v3.94.2 — the number burned into each photo was used as
    the text to choose a font for, so "1" … "500" were 500 choices and the
    cache (256 entries) never hit: a 500-photo sheet took 3x as long."""
    from PIL import Image, ImageDraw
    from pixcull.export.proof_sheet import _burn_index
    im = Image.new("RGB", (400, 300))
    for n in range(1, 501):
        _burn_index(im, ImageDraw, n)
    info = fonts._choose.cache_info()
    assert info.misses == 1 and info.hits == 499, info


# ------------------------------------------------------------ contact sheet


def _captured_pages(monkeypatch):
    from PIL import Image
    pages: list = []
    real_save = Image.Image.save

    def save(self, fp, fmt=None, **kw):
        if fmt == "PDF":
            pages[:] = [self, *kw.get("append_images", [])]
        return real_save(self, fp, fmt, **kw)

    monkeypatch.setattr(Image.Image, "save", save)
    return pages


def _red_pixels(im) -> int:
    px = im.convert("RGB").load()
    return sum(1 for y in range(0, im.height, 4) for x in range(0, im.width, 4)
               if px[x, y][0] > 200 and px[x, y][1] < 60 and px[x, y][2] < 60)


def test_a_readable_photo_is_on_the_contact_sheet(tmp_path, monkeypatch):
    """Both sides: the photo that exists is drawn, the one that does not
    is marked. Only the second half was ever tested."""
    from PIL import Image
    from pixcull.report.contact_sheet import render_contact_sheet
    red = tmp_path / "red.jpg"
    Image.new("RGB", (800, 600), (230, 20, 20)).save(red)
    pages = _captured_pages(monkeypatch)
    render_contact_sheet([(red, "IMG_0001.jpg")], tmp_path / "one.pdf", title="T")
    assert _red_pixels(pages[0]) > 2000, "the photograph is not on the page"

    pages = _captured_pages(monkeypatch)
    render_contact_sheet([(tmp_path / "gone.jpg", "gone.jpg")], tmp_path / "two.pdf",
                         title="T")
    assert _red_pixels(pages[0]) == 0


def test_the_contact_sheet_draws_its_title_with_a_font_that_has_it(tmp_path, monkeypatch):
    from PIL import Image
    from pixcull.report import contact_sheet
    asked: list[str] = []
    real = contact_sheet._font

    def spy(size, text=""):
        asked.append(text)
        return real(size, text)

    monkeypatch.setattr(contact_sheet, "_font", spy)
    src = tmp_path / "a.jpg"
    Image.new("RGB", (400, 300), (90, 120, 160)).save(src)
    contact_sheet.render_contact_sheet(
        [(src, "张三_001.jpg")], tmp_path / "c.pdf", title="张三婚礼 精选",
        cover={"title": "张三婚礼", "studio": "스튜디오"})
    assert asked and all("张三婚礼" in t for t in asked), (
        "a font was chosen without the title it has to draw")
    assert any("张三_001.jpg" in t for t in asked), "captions were not considered"
    assert any("스튜디오" in t for t in asked), "the cover's studio line was not considered"


# ------------------------------------------------------------ m3 eval --review


def test_m3_eval_reads_a_review_pass(tmp_path, monkeypatch):
    """`lab` was assigned after the review loop that writes into it, so
    every `--review` raised UnboundLocalError before reading a verdict.
    The key lookup is stubbed out: this must never reach the network or
    the keychain."""
    from typer.testing import CliRunner
    import pixcull.scoring.m3 as m3
    from pixcull.cli import app
    monkeypatch.setattr(m3, "api_key_from_env", lambda: "")
    labels = tmp_path / "labels.csv"
    labels.write_text("filename,manual_label\na.jpg,keep\nb.jpg,cull\n", "utf-8")
    review = tmp_path / "review.json"
    review.write_text(json.dumps({"verdicts": {"a.jpg": "cull"}}), "utf-8")
    res = CliRunner().invoke(app, ["m3", "eval", "--labels", str(labels),
                                   "--review", str(review)])
    assert not isinstance(res.exception, UnboundLocalError), res.output
    assert "review: 1 label(s) replaced" in res.output, res.output
    assert "No MiniMax key" in res.output and res.exit_code == 2, res.output
