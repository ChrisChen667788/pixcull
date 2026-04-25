"""XMP sidecar read/write for Lightroom / Capture One interop.

We write a minimal Adobe-flavored XMP packet with two fields:

* ``xmp:Rating`` — 0..5 stars. Lightroom and Capture One both read this.
* ``xmp:Label`` — color flag (``Green``/``Yellow``/``Red``/...). Optional;
  empty string means "don't set a label".

The sidecar lives next to the image as ``<stem>.xmp``. Both editors look
for the sidecar by stem, so ``IMG_0042.JPG`` and ``IMG_0042.CR3`` share
the same ``IMG_0042.xmp`` — when both exist on disk, the editor that
opens the JPG and the editor that opens the RAW will both see the rating.

Why a hand-written XMP rather than ``python-xmp-toolkit``: the toolkit
needs the Exempi C library, which is a heavy dep for a one-tag write.
The format below is what Lightroom itself emits when you star an image
via Develop → Metadata → Save Metadata to File, minus the dozens of
tags Lightroom adds for its own bookkeeping. Tested in LR Classic 13.x
and Capture One 23.

If a sidecar already exists, ``write_xmp`` overwrites it. We never edit
in-place — round-tripping arbitrary XMP would require a real parser.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

# UUID required by the XMP spec to mark the start/end of a packet — must be
# this exact byte sequence for Adobe tools to recognize the file as XMP.
_XPACKET_UUID = "W5M0MpCehiHzreSzNTczkc9d"

# Adobe's color label vocabulary. Lightroom recognizes these strings; case
# matters. We export "" → no <xmp:Label> tag (LR shows "no label").
_VALID_LABELS = frozenset({"", "Red", "Yellow", "Green", "Blue", "Purple"})


def write_xmp(image_path: Path, rating: int, color_label: str = "") -> Path:
    """Write Lightroom-compatible XMP sidecar next to ``image_path``.

    Args:
        image_path: source image (any extension); sidecar is ``<stem>.xmp``
            in the same directory. The image itself doesn't need to exist —
            we only use its path for naming the sidecar.
        rating: 0..5; clamped silently if outside range. 0 = "unrated".
        color_label: one of "", "Red", "Yellow", "Green", "Blue", "Purple".
            Anything else raises ValueError to catch typos at the call site.

    Returns:
        Path to the written .xmp file.
    """
    if color_label not in _VALID_LABELS:
        raise ValueError(
            f"color_label must be one of {sorted(_VALID_LABELS)}, "
            f"got {color_label!r}"
        )
    rating = max(0, min(5, int(rating)))

    label_tag = (
        f"      <xmp:Label>{escape(color_label)}</xmp:Label>\n"
        if color_label else ""
    )

    body = (
        '<?xpacket begin="﻿" id="' + _XPACKET_UUID + '"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="PixCull">\n'
        '  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '    <rdf:Description rdf:about=""\n'
        '        xmlns:xmp="http://ns.adobe.com/xap/1.0/">\n'
        f'      <xmp:Rating>{rating}</xmp:Rating>\n'
        f'{label_tag}'
        '    </rdf:Description>\n'
        '  </rdf:RDF>\n'
        '</x:xmpmeta>\n'
        '<?xpacket end="w"?>\n'
    )

    sidecar = image_path.with_suffix(".xmp")
    sidecar.write_text(body, encoding="utf-8")
    return sidecar


def read_xmp(image_path: Path) -> dict:
    """Read existing XMP sidecar → ``{"rating": int, "color_label": str}``.

    Returns ``{"rating": 0, "color_label": ""}`` if the sidecar doesn't
    exist or is malformed — callers shouldn't have to special-case missing
    metadata. Uses a tiny regex pull rather than a full XML parser so we
    work on Lightroom-emitted sidecars that include a 200-line tag soup
    of camera-specific extensions we'd otherwise choke on.
    """
    import re  # local — read path is rarely hit

    sidecar = image_path.with_suffix(".xmp")
    out = {"rating": 0, "color_label": ""}
    if not sidecar.exists():
        return out
    try:
        text = sidecar.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out

    # Match either <xmp:Rating>5</xmp:Rating> form or attribute form
    # xmp:Rating="5" (Lightroom uses both depending on version).
    m = re.search(r'xmp:Rating(?:="(\d)"|>(\d)</xmp:Rating>)', text)
    if m:
        out["rating"] = int(m.group(1) or m.group(2))
    m = re.search(
        r'xmp:Label(?:="([^"]*)"|>([^<]*)</xmp:Label>)', text
    )
    if m:
        out["color_label"] = (m.group(1) or m.group(2) or "").strip()
    return out


# ---------------------------------------------------------------------------
# Decision → rating/label mapping. Kept here so CLI export, web demo, and
# any future bulk-export tool all agree on what "keep" means in LR-speak.
# ---------------------------------------------------------------------------
def decision_to_xmp(decision: str) -> tuple[int, str]:
    """Map pipeline decision to (stars, label).

    Mapping rationale: stars are the primary signal LR users sort by; we
    use 5 / 3 / 1 instead of 5 / 3 / 0 so cull rows still appear in
    "show ≥1 star" filters (some users prune by deleting unrated, which
    would lose them). Labels are a secondary cue — Green/Yellow/Red is
    the universal shoot-review code, and Capture One renders them as
    colored borders in the browser.
    """
    return {
        "keep":  (5, "Green"),
        "maybe": (3, "Yellow"),
        "cull":  (1, "Red"),
    }.get(decision, (0, ""))
