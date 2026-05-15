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


def write_xmp(image_path: Path, rating: int, color_label: str = "",
                 keywords: list[str] | None = None,
                 description: str = "",
                 headline: str = "") -> Path:
    """Write Lightroom-compatible XMP sidecar next to ``image_path``.

    Args:
        image_path: source image (any extension); sidecar is ``<stem>.xmp``
            in the same directory. The image itself doesn't need to exist —
            we only use its path for naming the sidecar.
        rating: 0..5; clamped silently if outside range. 0 = "unrated".
        color_label: one of "", "Red", "Yellow", "Green", "Blue", "Purple".
            Anything else raises ValueError to catch typos at the call site.
        keywords: V29 — list of IPTC ``dc:subject`` keywords to embed.
            Photojournalism + commercial workflows search by these in
            Lr / C1 catalogs ("show me all PixCull:keep + scene:portrait").
            Empty list / None = no <dc:subject> block.
        description: V29 — IPTC ``dc:description`` (LR's "Caption" field).
            Free-form text; typically PixCull's per-image verdict.
            Empty = no caption block written.
        headline: V29 — IPTC ``photoshop:Headline`` (LR's "Headline").
            Short single-line; typically PixCull's top strength phrase.
            Empty = no headline block.

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

    # V29 — IPTC namespace blocks. ``dc:`` is Dublin Core, the
    # standard XMP wrapper for keywords + descriptions. ``photoshop:``
    # is Adobe's extension for the Headline field LR specifically reads.
    iptc_blocks = ""
    if keywords:
        # ``rdf:Bag`` is an unordered keyword set; ``rdf:Seq`` would
        # imply ordering. LR treats both identically; Bag is the
        # conventional shape for keywords.
        items = "".join(
            f"          <rdf:li>{escape(str(k))}</rdf:li>\n"
            for k in keywords if str(k).strip()
        )
        if items:
            iptc_blocks += (
                "      <dc:subject>\n"
                "        <rdf:Bag>\n"
                f"{items}"
                "        </rdf:Bag>\n"
                "      </dc:subject>\n"
            )
    if description:
        # dc:description is an alt-lang Alt — LR reads the x-default
        # variant by default. We could emit per-language but that
        # adds complexity for zero gain in practice.
        iptc_blocks += (
            "      <dc:description>\n"
            "        <rdf:Alt>\n"
            f'          <rdf:li xml:lang="x-default">{escape(description)}</rdf:li>\n'
            "        </rdf:Alt>\n"
            "      </dc:description>\n"
        )
    if headline:
        iptc_blocks += (
            f"      <photoshop:Headline>{escape(headline)}</photoshop:Headline>\n"
        )

    # Build namespace declarations. Always include xmp:; conditionally
    # add dc: and photoshop: only when we're writing those blocks (the
    # XMP spec is permissive but Adobe tools warn on unused ns).
    ns_decls = ['xmlns:xmp="http://ns.adobe.com/xap/1.0/"']
    if keywords or description:
        ns_decls.append('xmlns:dc="http://purl.org/dc/elements/1.1/"')
    if headline:
        ns_decls.append('xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"')
    ns_str = "\n        ".join(ns_decls)

    body = (
        '<?xpacket begin="﻿" id="' + _XPACKET_UUID + '"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="PixCull">\n'
        '  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '    <rdf:Description rdf:about=""\n'
        f'        {ns_str}>\n'
        f'      <xmp:Rating>{rating}</xmp:Rating>\n'
        f'{label_tag}'
        f'{iptc_blocks}'
        '    </rdf:Description>\n'
        '  </rdf:RDF>\n'
        '</x:xmpmeta>\n'
        '<?xpacket end="w"?>\n'
    )

    sidecar = image_path.with_suffix(".xmp")
    sidecar.write_text(body, encoding="utf-8")
    return sidecar


def read_develop_settings(image_path: Path) -> dict:
    """V26.1 — parse Lightroom develop settings from the XMP sidecar.

    Returns a dict with the subset of Lr ``crs:*`` fields we can
    actually apply during a rawpy postprocess + PIL post-pass:

      ``exposure``       float, EV stops (Lr ``crs:Exposure2012``)
      ``contrast``       float, -1..+1 (mapped from Lr -100..+100)
      ``highlights``     float, -1..+1 (Lr ``crs:Highlights2012``)
      ``shadows``        float, -1..+1
      ``saturation``     float, -1..+1
      ``vibrance``       float, -1..+1 (treated as saturation for now —
                          Lr's vibrance is non-uniform per-channel;
                          we approximate with the same multiplier)
      ``temperature``    int, Kelvin (Lr ``crs:Temperature``)
      ``tint``           int, -150..+150 magenta-green

    Missing fields default to None. Returns an empty dict when:
      * the sidecar doesn't exist
      * the sidecar is unparseable
      * no Lr develop fields are present

    Pure regex parser — same approach as ``read_xmp`` for the
    rating/label case. We DON'T attempt the full crs: tone curve
    or per-channel HSL adjustments because those would require a
    real XMP parser + Lr's proprietary tone-curve math.
    """
    import re

    sidecar = image_path.with_suffix(".xmp")
    if not sidecar.exists():
        return {}
    try:
        text = sidecar.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    out: dict = {}

    def _attr_or_tag(key: str, scale: float = 1.0,
                       to_float: bool = True) -> object:
        # Lr writes either attribute (``crs:Exposure2012="0.50"``) or
        # tag (``<crs:Exposure2012>0.50</crs:Exposure2012>``); accept both.
        m = re.search(
            r'crs:%s(?:="([-+\d.]+)"|>([-+\d.]+)</crs:%s>)' % (key, key),
            text,
        )
        if not m:
            return None
        raw = m.group(1) or m.group(2)
        try:
            v = float(raw) * scale
        except (TypeError, ValueError):
            return None
        return v if to_float else int(v)

    # Exposure is in EV stops on the wire; Lr range is typically -5..+5
    exp = _attr_or_tag("Exposure2012")
    if exp is not None:
        out["exposure"] = exp
    # Contrast/Highlights/Shadows/Whites/Blacks are -100..+100; scale
    # to -1..+1 for the application code.
    for src, dst in [("Contrast2012",   "contrast"),
                      ("Highlights2012", "highlights"),
                      ("Shadows2012",    "shadows"),
                      ("Whites2012",     "whites"),
                      ("Blacks2012",     "blacks"),
                      ("Saturation",     "saturation"),
                      ("Vibrance",       "vibrance")]:
        v = _attr_or_tag(src, scale=0.01)
        if v is not None:
            out[dst] = max(-1.0, min(1.0, v))

    # Temperature / Tint are integers; absolute Kelvin + relative shift.
    temp = _attr_or_tag("Temperature", to_float=False)
    if temp is not None:
        out["temperature"] = int(temp)
    tint = _attr_or_tag("Tint", to_float=False)
    if tint is not None:
        out["tint"] = int(tint)

    return out


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


# V29 — build IPTC fields from a row + advice. Centralized here so
# the /export endpoint, the CLI ``pixcull export``, and any future
# bulk tooling all emit identical metadata.
def build_iptc_fields_from_row(
    row: dict,
    *,
    advice: dict | None = None,
    face_labels: dict[int, str] | None = None,
    vertical: str | None = None,
    run_id: str | None = None,
    auto_caption: str | None = None,
) -> dict:
    """V29 — turn a result row into IPTC keyword + caption fields.

    Returns ``{keywords: [str], description: str, headline: str}``
    ready to feed into ``write_xmp``.

    Keyword scheme (all are namespaced so search is unambiguous in
    LR's keyword tree):
      ``PixCull:keep`` / ``PixCull:maybe`` / ``PixCull:cull``
      ``PixCull:scene:<scene>``
      ``PixCull:vertical:<key>``                  (only when set)
      ``PixCull:person:<label>``                  (per-face for clusters
                                                    that have user labels)
      ``PixCull:run:<run_id_prefix>``             (last 4 chars; for
                                                    grouping in LR)
    Each keyword survives a LR catalog export. Photographers can
    filter "Find: keywords contains PixCull:person:Bride" to surface
    every catalog photo where PixCull identified the bride.
    """
    decision = str(row.get("decision") or "")
    scene = str(row.get("scene") or "")
    keywords: list[str] = []

    if decision in ("keep", "maybe", "cull"):
        keywords.append(f"PixCull:{decision}")
    if scene:
        keywords.append(f"PixCull:scene:{scene}")
    if vertical:
        keywords.append(f"PixCull:vertical:{vertical}")
    if run_id:
        # Last 4 chars is short + unambiguous within a single user's
        # catalog; the full run_id would clutter LR's keyword tree.
        keywords.append(f"PixCull:run:{run_id[-4:]}")

    # Per-face person keywords. ``face_clusters`` is a list of int
    # cluster ids; ``face_labels`` is the user-supplied {cluster_id:
    # label} from V22.1. Only labeled clusters contribute keywords —
    # unlabeled "Person N" doesn't survive LR catalog filtering well.
    fc = row.get("face_clusters") or []
    if face_labels and fc:
        seen = set()
        for cid in fc:
            try:
                cid_int = int(cid)
            except (TypeError, ValueError):
                continue
            label = (face_labels.get(cid_int) or "").strip()
            if label and label not in seen:
                keywords.append(f"PixCull:person:{label}")
                seen.add(label)

    # V20 advice → caption + headline. The verdict_short string is
    # designed to be a one-liner ("保留 ✓ — 亮点: Zone V 中灰..."), so
    # use it as the headline. The fuller description joins strengths
    # + weaknesses into a paragraph (skipped when both are empty —
    # don't want a blank caption shadow).
    #
    # P2.5 — when a per-photo ``auto_caption`` was passed in, it
    # WINS over the V20 advice-derived description. The auto-caption
    # is designed to read as a journalistic sentence and is what
    # agencies / wire services expect in IPTC:Caption-Abstract. The
    # advice-derived bullets stay as a useful "verbose annotation"
    # for solo photographers via the V20 path when auto_caption is None.
    headline = ""
    description = ""
    if advice:
        headline = str(advice.get("verdict_short") or "")
    if auto_caption:
        description = auto_caption
    elif advice:
        bits: list[str] = []
        for s in advice.get("strengths") or []:
            bits.append(f"+ {s}")
        for w in advice.get("weaknesses") or []:
            bits.append(f"- {w}")
        for sug in advice.get("suggestions") or []:
            bits.append(f"→ {sug}")
        if bits:
            description = "\n".join(bits)

    return {
        "keywords":    keywords,
        "description": description,
        "headline":    headline,
    }
