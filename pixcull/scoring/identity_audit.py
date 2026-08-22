"""v2.75 — photographs this run cannot show you.

Every map from a photo to its bytes in this product is keyed on the
**basename**: `manifest.json` is `{filename: path}`, the image endpoints
are `/thumb/<run>/<filename>`, the grid identifies a card by
`data-fn`, and `library index` builds `out[fn] = path`. Each of those is
a dict, and a dict keyed on a name that is not unique silently keeps the
last writer.

Measured on a real 5,069-frame run of the owner's own Downloads folder,
scanned recursively:

    scores.csv rows          5069
    manifest.json entries    4616
    photographs unreachable   453

Those 453 have a card in the grid. The card shows **another
photograph's** thumbnail, because the URL resolves the basename to
whichever file won the dict. The photographer cannot see them, cannot
open them, and any decision they make on that card is a decision about
a picture they were not shown.

This module does not fix the identity scheme — that reaches decisions,
annotations, XMP export and the library index, and doing it at speed is
how the next seventeen-version defect gets written. What it does is
refuse to let the loss stay silent, which is the same rule v2.71
established for fallbacks: a failure that is invisible is worse than a
failure that is loud, because only one of them gets fixed.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass(frozen=True)
class IdentityAudit:
    n_rows: int
    n_unique_names: int
    #: name -> the distinct paths that claim it, for the ones that collide
    collisions: dict[str, list[str]] = field(default_factory=dict)

    @property
    def n_colliding_names(self) -> int:
        return len(self.collisions)

    @property
    def n_unreachable(self) -> int:
        """Photographs whose bytes no URL in this product can address."""
        return sum(len(v) - 1 for v in self.collisions.values())

    @property
    def ok(self) -> bool:
        return not self.collisions

    def summary(self) -> str:
        if self.ok:
            return f"identity: {self.n_rows} photographs, all addressable"
        return (f"identity: {self.n_unreachable} of {self.n_rows} "
                f"photographs are UNREACHABLE — {self.n_colliding_names} "
                f"filenames are used by more than one file, and every map "
                f"from a photo to its bytes is keyed on the filename")


def audit_rows(rows) -> IdentityAudit:
    """``rows`` is any iterable of mappings with `filename` and a path.

    Same-name/same-path is not a collision — that is one photograph
    listed twice, which is a different (and harmless-looking) problem.
    Only distinct paths sharing a name can hide a photograph.
    """
    by_name: dict[str, set] = defaultdict(set)
    n = 0
    for r in rows:
        name = str(r.get("filename") or "").strip()
        path = str(r.get("path") or r.get("src_path") or "").strip()
        if not name:
            continue
        n += 1
        if path:
            by_name[name].add(path)
    collisions = {k: sorted(v) for k, v in by_name.items() if len(v) > 1}
    return IdentityAudit(n_rows=n, n_unique_names=len(by_name),
                         collisions=collisions)
