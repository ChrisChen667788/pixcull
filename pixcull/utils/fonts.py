"""v3.94.2 — a font that can draw the text it is given.

The proof-sheet watermark and the contact-sheet PDF each kept a list of
font paths and took the first one that *opened*. Opening says nothing
about drawing: a Latin font opens fine and renders every Chinese, Japanese
or Korean character as a box. PR #4 fixed the order of one list so that a
Chinese font came first, which was enough on a Windows or Mac machine
asked for Chinese. It left three cases that still came out as boxes, with
no message anywhere:

* Korean on a Mac — the first CJK font there, Hiragino Sans GB, has no
  Hangul;
* any CJK text on Linux without a CJK font, which includes PixCull's own
  Docker image;
* the contact sheet, whose list never had a CJK font in it at all.

So the choice is made against the text: each candidate is asked to draw
every character, a character drawn as the font's "missing glyph" box
counts as missing, and the first font missing nothing wins. When no
installed font can draw the text, the one missing the fewest characters
is used and the caller is told which characters will be boxes.
"""
from __future__ import annotations

import functools
import glob
import logging
import os

logger = logging.getLogger(__name__)

#: Fonts with CJK coverage, every platform. Which of several covering fonts
#: is preferred is the only thing the order decides; coverage decides use.
CJK_FONTS = (
    "C:/Windows/Fonts/msyh.ttc",                     # 微软雅黑
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",                   # 黑体
    "C:/Windows/Fonts/simsun.ttc",                   # 宋体
    "C:/Windows/Fonts/malgun.ttf",                   # 맑은 고딕 (Hangul)
    "C:/Windows/Fonts/YuGothM.ttc",                  # 游ゴシック
    "C:/Windows/Fonts/meiryo.ttc",
    "/System/Library/Fonts/PingFang.ttc",            # absent on current macOS
    "/System/Library/Fonts/Hiragino Sans GB.ttc",    # no Hangul
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",    # Hangul
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",   # Debian/Ubuntu
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
)

#: Latin-only fallbacks, for text that needs nothing more.
LATIN_FONTS = (
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)

# Other distributions put the same fonts elsewhere (Fedora:
# /usr/share/fonts/google-noto-sans-cjk-vf-fonts/, Arch: /usr/share/fonts/noto-cjk/).
_FONT_DIRS = ("/usr/share/fonts", "/usr/local/share/fonts",
              "~/.local/share/fonts", "~/.fonts")
_CJK_NAMES = ("*NotoSansCJK*", "*NotoSerifCJK*", "*SourceHanSans*",
              "*SourceHanSerif*", "*wqy-*", "*DroidSansFallback*")

# Plane 16 private use: no font a user has installed carries it, so it
# draws as the font's missing-glyph box, whatever that box looks like.
_PROBE = "\U0010fffd"


@functools.cache
def _discovered() -> tuple[str, ...]:
    found: list[str] = []
    for d in _FONT_DIRS:
        root = os.path.expanduser(d)
        if not os.path.isdir(root):
            continue
        for pat in _CJK_NAMES:
            for ext in ("ttc", "otf", "ttf"):
                found += sorted(glob.glob(os.path.join(root, "**", f"{pat}.{ext}"),
                                          recursive=True))
    return tuple(dict.fromkeys(found))


def candidates(latin_first: bool = False) -> tuple[str, ...]:
    """Every font path worth trying, CJK-capable first unless asked.

    ``latin_first`` keeps a caller's existing look for Latin text (the
    contact sheet has always been Arial) and still reaches a CJK font the
    moment the text needs one, because use is decided by coverage."""
    cjk = CJK_FONTS + _discovered()
    return tuple(dict.fromkeys(LATIN_FONTS + cjk if latin_first else cjk + LATIN_FONTS))


def _bitmap(font, ch: str):
    from PIL import Image, ImageDraw
    left, top, right, bottom = font.getbbox(ch)
    im = Image.new("L", (max(1, right - left + 2), max(1, bottom - top + 2)))
    ImageDraw.Draw(im).text((1 - left, 1 - top), ch, font=font, fill=255)
    return im.size, im.tobytes()


def missing_glyphs(font, text: str) -> list[str]:
    """The characters of ``text`` that ``font`` would draw as a box."""
    box = _bitmap(font, _PROBE)
    out = []
    for ch in dict.fromkeys(text):
        if ch.isspace() or not ch.isprintable():
            continue
        if _bitmap(font, ch) == box:
            out.append(ch)
    return out


def _bundled(size: int):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:            # Pillow < 10.1: a fixed ~11 px bitmap font
        return ImageFont.load_default()


@functools.lru_cache(maxsize=256)
def _choose(text: str, latin_first: bool = False) -> tuple[str | None, tuple[str, ...]]:
    """(path, missing): the first candidate missing nothing, otherwise the
    one missing least. ``path`` None means Pillow's bundled font."""
    from PIL import ImageFont
    best: tuple[str | None, tuple[str, ...]] | None = None
    for path in candidates(latin_first):
        try:
            font = ImageFont.truetype(path, 32)
        except Exception:  # noqa: BLE001 — absent, unreadable, wrong format
            continue
        miss = tuple(missing_glyphs(font, text))
        if not miss:
            return path, ()
        if best is None or len(miss) < len(best[1]):
            best = (path, miss)
    miss = tuple(missing_glyphs(_bundled(32), text))
    if best is None or len(miss) < len(best[1]):
        best = (None, miss)
    return best


def unrenderable(text: str) -> str:
    """The characters of ``text`` no installed font can draw ("" if none)."""
    return "".join(_choose(text)[1])


def font_for(text: str, size: int, *, latin_first: bool = False):
    """A font of ``size`` px that draws ``text``, or comes closest.

    Logs a warning naming the characters that will come out as boxes; a
    caller that can show the user something should also check
    :func:`unrenderable`.
    """
    from PIL import ImageFont
    path, miss = _choose(text, latin_first)
    if miss:
        _warn(miss)
    if path is None:
        return _bundled(size)
    return ImageFont.truetype(path, size)


@functools.cache
def _warn(miss: tuple[str, ...]) -> None:
    logger.warning(
        "No installed font can draw %s; they will appear as boxes. %s",
        " ".join(miss), INSTALL_HINT)


INSTALL_HINT = ("Install a CJK font: on Debian or Ubuntu "
                "`sudo apt-get install fonts-wqy-microhei` (5 MB, the one "
                "the PixCull Docker image carries) or `fonts-noto-cjk`.")
