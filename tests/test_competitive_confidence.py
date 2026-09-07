"""v3.26 — the refresh protocol stops trusting its own confidence field.

The 2026-08-31 scan wrote `confidence: verified` on 25 of 41 entries.  The
fact-check pass then audited ten headline claims and overturned ten of
ten — including two of the three products the next charter was built
around.

A self-reported confidence that wrong is worse than none, because the
next reader weights it: a later charter, a later refresh, a release note.
So the field belongs to the verification pass and to nothing else.
"""
import json
from pathlib import Path

import pytest

SNAPSHOTS = sorted((Path(__file__).resolve().parent.parent / "docs"
                    / "competitive").glob("snapshot-*.json"))

#: The only values an entry may carry.
ALLOWED = {"verified", "partial", "unverified"}


def _entries(path):
    return json.loads(path.read_text(encoding="utf-8")).get("entries", [])


@pytest.mark.parametrize("path", SNAPSHOTS, ids=lambda p: p.name)
def test_verified_requires_a_verification_record(path):
    """The rule. `verified` is a claim about work somebody did, so it has
    to name the work."""
    bad = [e["name"] for e in _entries(path)
           if e.get("confidence") == "verified" and not e.get("verified_by")]
    assert not bad, (
        f"{path.name}: entries claiming `verified` with no `verified_by`: "
        + ", ".join(bad[:6]))


@pytest.mark.parametrize("path", SNAPSHOTS, ids=lambda p: p.name)
def test_no_entry_invents_a_confidence_value(path):
    bad = [(e["name"], e.get("confidence")) for e in _entries(path)
           if e.get("confidence") not in ALLOWED]
    assert not bad, f"{path.name}: unknown confidence values: {bad[:6]}"


@pytest.mark.parametrize("path", SNAPSHOTS, ids=lambda p: p.name)
def test_the_snapshot_states_the_contract(path):
    """A rule that lives only in a test gets deleted by whoever the test
    inconveniences. It travels with the data too."""
    d = json.loads(path.read_text(encoding="utf-8"))
    assert "confidence_contract" in d
    assert "verified_by" in d["confidence_contract"]


@pytest.mark.parametrize("path", SNAPSHOTS, ids=lambda p: p.name)
def test_a_downgraded_entry_says_why(path):
    """An entry that silently changed value is indistinguishable from one
    nobody ever scanned."""
    for e in _entries(path):
        if e.get("downgraded_by"):
            assert e["confidence"] == "unverified"
            assert "fact-check" in e["downgraded_by"] or \
                   "verification" in e["downgraded_by"]


def test_the_protocol_document_tells_the_next_reader_not_to_undo_this():
    """A snapshot where almost everything reads `unverified` looks like a
    regression. Without this paragraph someone helpfully fixes it back."""
    doc = (Path(__file__).resolve().parent.parent / "docs"
           / "COMPETITIVE-REFRESH-PROTOCOL.md").read_text(encoding="utf-8")
    assert "A scan may not write `confidence`" in doc
    assert "about to \"fix\" this" in doc
    assert "10 of 10" in doc or "ten of ten" in doc


def test_the_migration_actually_dropped_the_count():
    """The charter's measure: the number of `verified` entries goes DOWN.
    If a later edit reattaches the field to the scan, this catches it."""
    for path in SNAPSHOTS:
        entries = _entries(path)
        verified = [e for e in entries if e.get("confidence") == "verified"]
        assert len(verified) < len(entries) / 2, (
            f"{path.name}: {len(verified)}/{len(entries)} claim `verified` — "
            f"that is scan-written confidence again")
