"""P-PRO-4 — wedding moment-list classifier.

Wedding photographers shoot toward a known sequence of "moments":
preparations → first-look → ceremony → vows → ring exchange → first
kiss → recessional → group portraits → reception → first dance →
toasts → cake → bouquet toss → candids. Delivery packages are
typically organized by these moments, and a missing mandatory moment
("the album doesn't have the first kiss") is a contract-grade
failure.

PixCull's existing genre/vertical layer recognizes a photo IS a
wedding photo. This module goes one step further: tells you WHICH
moment within the wedding it is, so the export pipeline can drop
each frame into the right folder and surface coverage gaps in the
admin UI.

Architecture mirrors the scene detector (CLIP zero-shot + softmax
+ margin abstain), but lives in scoring/ instead of detectors/
because it's a vertical-specific *post* pass — only runs when
scene/vertical is "wedding". Importable without torch so the
coverage-audit helpers can run on CSV-loaded rows in tests + the
admin web UI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional


# Public moment vocabulary. Keys are short snake_case ASCII so they
# survive CSV/JSON round-trips cleanly; labels_zh are what the UI
# shows. Prompts are English (CLIP is English-trained) and were
# chosen to be sufficiently distinct from each other on visual
# semantics — not just verbal description — so softmax separates
# them cleanly.
@dataclass(frozen=True)
class MomentDef:
    key:      str
    label_zh: str
    prompt:   str
    mandatory: bool = False    # if True, coverage_audit flags absence


WEDDING_MOMENTS: list[MomentDef] = [
    # P-PRO-4.2 — prompts tightened after running classifier on
    # the 81-photo curated set from /Volumes/.../李慧&李翔/已调色.
    # Diagnostic showed:
    #   - preparation_bride matched 23% of frames (CLIP attaching
    #     to any woman with styled hair / makeup); tightened to
    #     anchor on the morning preparation context (silk robe,
    #     stylist tools, mirror) so it stops being a magnet.
    #   - vows / ring_exchange landed below 0.5 avg confidence;
    #     tightened with altar / hand-holding / officiant
    #     specificity so the visual canon is unambiguous.
    #   - first_dance / cake_cutting hit 0 frames on the curated
    #     set; tightened with dance-floor / multi-tier-cake
    #     specificity to give CLIP a clearer visual anchor in
    #     case the moments WERE present but mis-attributed.
    #   - recessional disambiguated from processional by
    #     anchoring on "applauding guests behind couple".
    MomentDef("preparation_bride", "新娘准备",
              "a bride in the morning before her wedding, a hairstylist or makeup artist working on her, white silk robe, indoor bridal suite with mirror and styling tools",
              mandatory=True),
    MomentDef("preparation_groom", "新郎准备",
              "a groom getting ready, putting on a suit jacket or tying a necktie, indoor preparation room",
              mandatory=False),
    MomentDef("first_look", "First Look",
              "a couple seeing each other for the first time before the ceremony, emotional reaction"),
    MomentDef("processional", "入场",
              "a bride walking down the aisle with her father at the start of the ceremony, guests seated on both sides",
              mandatory=True),
    MomentDef("vows", "宣誓",
              "a bride and groom standing facing each other at the wedding altar holding hands, officiant in robes visible, ceremony in progress",
              mandatory=False),
    MomentDef("ring_exchange", "交换戒指",
              "a close-up of two hands during a wedding ceremony, placing a gold or diamond ring onto the ring finger of the bride or groom",
              mandatory=True),
    MomentDef("first_kiss", "第一吻",
              "a bride and groom kissing at the altar, ceremony moment, applauding guests visible behind",
              mandatory=True),
    MomentDef("recessional", "退场",
              "a newly married bride and groom walking together away from the altar back down the aisle while applauding guests stand and cheer behind"),
    MomentDef("group_portraits", "合影",
              "a formal group portrait of the wedding party or extended family lined up together posing for the camera"),
    MomentDef("first_dance", "第一支舞",
              "a bride in her white wedding gown slow-dancing with her groom alone on a dance floor under warm spotlight, embracing while turning",
              mandatory=True),
    MomentDef("speeches", "致辞",
              "a wedding guest standing at a banquet hall holding a microphone giving a speech, other guests seated at decorated tables"),
    MomentDef("toast", "敬酒",
              "a wedding guest standing at a banquet table raising a single champagne flute upward, other guests holding raised glasses around"),
    MomentDef("cake_cutting", "切蛋糕",
              "a bride and groom together cutting into a tall multi-tier white wedding cake with a single knife, smiling at the cake",
              mandatory=True),
    MomentDef("bouquet_toss", "捧花",
              "a bride throwing her bouquet of flowers backward over her shoulder to a crowd of women trying to catch it"),
    MomentDef("reception_general", "宴席",
              "a wide overview of a wedding banquet hall full of guests seated at multiple round tables with food being served, chandeliers and decorations visible"),
    MomentDef("candid", "花絮",
              "a candid behind-the-scenes moment between wedding guests, laughing and hugging without posing"),
    # P-PRO-4.3 — Chinese wedding-specific moments.  These don't
    # share the western mandatory list (no first_dance / cake_cutting
    # in a traditional ceremony) so they're added here as separate
    # vocab; the MANDATORY_CHINESE constant below builds the right
    # mandatory list for these ceremonies.  All mandatory=False
    # in the MomentDef itself because the mandatory-ness depends
    # on which ceremony tradition the user selects — passed into
    # coverage_audit() via the new ``mandatory_keys`` parameter.
    MomentDef("door_block",       "堵门 / 接亲",
              "a groom and groomsmen at a door negotiating with bridesmaids blocking it, traditional Chinese fetching-the-bride ritual"),
    MomentDef("hair_combing",     "梳头",
              "a mother combing the bride's hair before her wedding ceremony, traditional Chinese pre-wedding ritual"),
    MomentDef("tea_ceremony",     "敬茶",
              "a bride and groom kneeling before parents and serving them tea cups with both hands, traditional Chinese wedding tea ceremony"),
    MomentDef("kneeling_bow",     "跪拜 / 三鞠躬",
              "a bride and groom bowing deeply together three times before parents or ancestors, traditional Chinese wedding bow"),
    MomentDef("red_dress",        "红嫁衣",
              "a bride wearing a traditional Chinese red qipao or longfeng gua wedding gown with gold embroidery"),
    MomentDef("firecrackers",     "鞭炮 / 礼炮",
              "wedding firecrackers being lit, smoke and celebration noise in a traditional Chinese ceremony entrance"),
]


# P-PRO-4.3 — preset mandatory-keys lists per ceremony tradition.
# Pass one of these to ``coverage_audit(rows, mandatory_keys=...)``
# to swap the audit's missing-moment check to that tradition.
# The default behaviour (no arg) uses the WESTERN list to stay
# backwards-compatible with code from before P-PRO-4.3.
MANDATORY_WESTERN: list[str] = [
    "preparation_bride", "processional", "ring_exchange",
    "first_kiss", "first_dance", "cake_cutting",
]
MANDATORY_CHINESE: list[str] = [
    "hair_combing", "door_block", "tea_ceremony",
    "kneeling_bow",  "ring_exchange", "first_kiss",
]
# Lookup map so the CLI / admin UI can present a picker.
MANDATORY_PRESETS: dict[str, list[str]] = {
    "western": MANDATORY_WESTERN,
    "chinese": MANDATORY_CHINESE,
}


def known_moment_keys() -> list[str]:
    return [m.key for m in WEDDING_MOMENTS]


def mandatory_moment_keys() -> list[str]:
    return [m.key for m in WEDDING_MOMENTS if m.mandatory]


def moment_label_zh(key: str) -> str:
    for m in WEDDING_MOMENTS:
        if m.key == key:
            return m.label_zh
    return key


def moment_prompts() -> dict[str, str]:
    """Map moment_key → CLIP prompt, ready for batched encoding."""
    return {m.key: m.prompt for m in WEDDING_MOMENTS}


# Margin below which we abstain on the classifier output and tag
# the frame as "moment_uncertain" — same logic as the scene
# debiasing in P-CORE-2. Tightened slightly because moment
# confusion (cake_cutting vs first_dance) is much more common
# than scene confusion (landscape vs portrait).
MOMENT_ABSTAIN_MARGIN: float = 0.05
MOMENT_UNKNOWN_LABEL: str = "unknown"


def resolve_moment_with_abstain(
    probs: dict[str, float],
) -> tuple[str, float, bool]:
    """Pick the top moment, abstaining when margin is too tight.

    Returns (chosen_key, chosen_prob, abstained). Pure Python so
    it works on probabilities computed by *any* upstream — CLIP,
    a fine-tuned classifier, or the goldenset evaluator's manual
    overrides.
    """
    if not probs:
        return MOMENT_UNKNOWN_LABEL, 0.0, True
    pairs = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
    top_name, top_p = pairs[0]
    runner_p = pairs[1][1] if len(pairs) > 1 else 0.0
    if (top_p - runner_p) < MOMENT_ABSTAIN_MARGIN:
        return MOMENT_UNKNOWN_LABEL, float(top_p), True
    return str(top_name), float(top_p), False


@dataclass
class CoverageReport:
    """Result of auditing a wedding run for moment coverage."""
    n_rows:           int
    moment_counts:    dict[str, int]
    missing_mandatory: list[str]
    n_unknown:        int = 0
    # P-PRO-4.3 — record which mandatory list this report was scored
    # against, so downstream (UI / Markdown render) can label it
    # "Western mandatory" / "Chinese mandatory" / "Custom".
    mandatory_keys:   list[str] = field(default_factory=list)

    @property
    def coverage_pct(self) -> float:
        """% of mandatory moments that have at least one photo."""
        mand = self.mandatory_keys
        if not mand:
            return 100.0
        hit = sum(1 for k in mand if self.moment_counts.get(k, 0) > 0)
        return round(100.0 * hit / len(mand), 1)


def coverage_audit(
    rows: Iterable[dict],
    moment_field: str = "wedding_moment",
    mandatory_keys: Optional[list[str]] = None,
) -> CoverageReport:
    """Count moments + flag mandatory misses across a run.

    Each row should carry the classifier's chosen moment under
    ``moment_field`` (default "wedding_moment").  Unknown / missing
    values feed into n_unknown.

    P-PRO-4.3 — ``mandatory_keys`` lets callers override which
    moments count as mandatory.  Useful for Chinese / Indian /
    civil-ceremony weddings whose mandatory list differs from
    the western default (no first_dance / cake_cutting in a
    traditional tea-ceremony wedding, for example).

    When omitted, falls back to the legacy behaviour: the
    ``mandatory=True`` MomentDef flag, which matches the western
    tradition.  Callers can pass a preset from
    ``MANDATORY_PRESETS`` ("western" / "chinese") or any custom
    list of moment keys.
    """
    counts: dict[str, int] = {k: 0 for k in known_moment_keys()}
    n_rows = 0
    n_unknown = 0
    for r in rows:
        n_rows += 1
        mk = r.get(moment_field)
        if mk and mk in counts:
            counts[mk] += 1
        else:
            n_unknown += 1
    # Resolve mandatory list — explicit override wins; otherwise
    # default to the western (MomentDef.mandatory=True) list to
    # preserve pre-P-PRO-4.3 callers' behaviour.
    mand = (list(mandatory_keys)
            if mandatory_keys is not None
            else mandatory_moment_keys())
    missing = [k for k in mand if counts.get(k, 0) == 0]
    return CoverageReport(
        n_rows=n_rows,
        moment_counts=counts,
        missing_mandatory=missing,
        n_unknown=n_unknown,
        mandatory_keys=mand,
    )
