"""v3.25 — a claim about a competitor carries a source, or is not made.

The 2026-09 fact-check overturned two of three headline claims in that
batch, and the most damaging one was ours rather than theirs: an
unsourced assertion that a named competitor requires cloud upload, used
to draw a privacy contrast in PixCull's favour.  No source supported it,
and the coverage was in fact consistent with on-device processing.

That is the class of claim this project refuses to publish about its own
accuracy.  This gate applies the same bar outward.

SCOPED TO TABLE ROWS, DELIBERATELY.  A linter strict enough to fire on
prose would be disabled inside a month, and a disabled linter is worse
than none because it reads as coverage.  Tables are where the
side-by-side claims live, and a table already has a place to put a
source.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Files whose comparison tables are a public claim about someone else.
TARGETS = ["README.md", "modelscope/README.md"] + [
    str(p.relative_to(ROOT)) for p in sorted((ROOT / "docs").glob("COMPETITIVE-*.md"))
]

SOURCE_HEADERS = ("source", "来源", "出处", "evidence")

#: Absolute statements about what someone else can or must do. Each one
#: needs a citation or a hedge; none of them is safe bare.
ABSOLUTES = ("必须", "只能", "无法", "不能", "都不", "全都", "一律",
             "从不", "永远")

#: Wording that turns an assertion into a description of uncertainty.
HEDGES = ("以其自身条款为准", "请查", "各家", "多数", "未证实", "不代为断言",
          "取决于", "不同")


def _tables(text: str):
    """Yield (header_cells, [row_cells, ...]) for every markdown table."""
    lines = text.splitlines()
    i = 0
    while i < len(lines) - 1:
        line, nxt = lines[i], lines[i + 1]
        if line.strip().startswith("|") and re.match(r"^\s*\|[\s:|-]+\|\s*$", nxt):
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                rows.append([c.strip() for c in
                             lines[j].strip().strip("|").split("|")])
                j += 1
            yield header, rows
            i = j
            continue
        i += 1


def test_a_table_with_a_source_column_has_a_source_in_every_row():
    """The competitive documents already carry a Source column. An empty
    one is a claim published with the citation slot visibly blank."""
    missing = []
    for rel in TARGETS:
        p = ROOT / rel
        if not p.exists():
            continue
        for header, rows in _tables(p.read_text(encoding="utf-8")):
            idx = [n for n, h in enumerate(header)
                   if any(s in h.lower() for s in SOURCE_HEADERS)]
            if not idx:
                continue
            col = idx[0]
            for row in rows:
                if len(row) <= col:
                    missing.append(f"{rel}: short row {row[:1]}")
                elif not row[col].strip() or row[col].strip() in ("-", "—"):
                    missing.append(f"{rel}: {row[0][:48]}")
    assert not missing, "table rows with an empty Source cell: " + "; ".join(missing)


def test_no_bare_absolute_claim_about_a_competitor():
    """"They must upload" is the exact shape of the claim the fact-check
    overturned. It needs a link or a hedge; bare, it is an assertion this
    project cannot support."""
    offenders = []
    for rel in TARGETS:
        p = ROOT / rel
        if not p.exists():
            continue
        for header, rows in _tables(p.read_text(encoding="utf-8")):
            # Only tables that put someone else beside PixCull.
            joined = " ".join(header)
            if "PixCull" not in joined:
                continue
            them = [n for n, h in enumerate(header) if "PixCull" not in h]
            for row in rows:
                for n in them:
                    if n >= len(row):
                        continue
                    cell = row[n]
                    if not any(a in cell for a in ABSOLUTES):
                        continue
                    if any(h in cell for h in HEDGES) or "http" in cell:
                        continue
                    offenders.append(f"{rel}: {cell[:60]}")
    assert not offenders, (
        "absolute claims about a competitor with no source and no hedge: "
        + "; ".join(offenders))


def test_the_gate_can_actually_see_a_violation():
    """A linter that passes because it matches nothing is worse than no
    linter, because it reads as coverage."""
    bad = """
| 取舍 | 主流 SaaS | PixCull |
|---|---|---|
| 照片去向 | 必须上传,且常常进训练池 | **本机优先** |
"""
    header, rows = next(_tables(bad))
    them = [n for n, h in enumerate(header) if "PixCull" not in h]
    cells = [rows[0][n] for n in them]
    assert any(any(a in c for a in ABSOLUTES) and
               not any(h in c for h in HEDGES) for c in cells)


def test_the_gate_accepts_the_corrected_wording():
    ok = "多为云端处理;各家的留存与训练策略以其自身条款为准,本项目不代为断言"
    assert any(h in ok for h in HEDGES)


def test_it_looks_at_the_files_that_actually_make_claims():
    assert "modelscope/README.md" in TARGETS
    assert any("COMPETITIVE-" in t for t in TARGETS)
