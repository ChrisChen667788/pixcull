# What is still open, and who it is waiting on

Written 2026-09-08, before starting the next block. Two blocks of work have
closed since the last time anyone counted, and the open items were spread across
three documents in two different shapes. This page is the count.

**Sixteen versions are nominally open. They are four requests.** Every one of
them is waiting on a person, and the harness for each is built — the work left
is not engineering.

---

## The four asks

### 1. One API spend ceiling — unblocks 8 measurements

v2.91, v3.3, v3.4, v3.5, v3.6, v3.11, v3.17, v3.18.

All eight wait on the same decision. `pixcull/scoring/measurement_plan.py`
estimates the whole block, refuses before the first call if it would exceed the
ceiling, and prices the three-calls-per-frame arms as three so the refusal lands
early rather than at 300% of the estimate.

> **v2.91 was outside this until v3.36.** It had waited since the v2.77–v2.95
> block on the same single thing, kept its own harness because the planner did
> not exist yet, and was listed separately in the v3.1–v3.27 close. An owner who
> set a ceiling and ran "the block" would still have had one measurement sitting
> outside it, waiting on a decision they had already made. It is in the planner
> now; the run still goes through `prompt_ab.plan`, which enforces the
> arms-differ-only-in-the-prompt rule this planner deliberately relaxes.

### 2. A correction set with the shoot type recorded — unblocks 3

v2.83, v3.8, v3.9.

There is no `annotations.jsonl` anywhere on this machine. The fitted profile at
`~/.pixcull/personal_profile.json` records 70 blind-provenance annotations and
the examples behind it are gone; a profile cannot be re-fitted from its own
output.

`personal_learn.readiness()` says how many more are needed and by which
vertical, counting the cheapest route to two eligible verticals rather than
every vertical that exists. `pixcull m3 label` is the session that produces
them.

### 3. Human judgement — unblocks 4

**v2.80, v2.88, v2.89** need raters who are working photographers and are not
the author. `blind_eval.py` and `ground_truth.py` hold the protocol and the
refusal guard that declines to publish a headline number when inter-rater
agreement falls below threshold. **Never synthesise these labels** — that is the
exact defect v2.88 exists to prevent.

**v3.12** is different in kind: it asks whether the burst face strip changes the
override rate, which is a question about the owner's own behaviour rather than
about a third party's opinion. `strip_effect.py` records it as a side effect of
ordinary use — off unless asked for, written to the run's own directory, never
transmitted, and refusing to report a rate below five observations per side.

### 4. One real Lightroom catalogue — unblocks 1

v3.10. Every test builds its own SQLite fixture in the shape the reader expects,
which proves the reader is self-consistent and nothing about Adobe's schema.
`pixcull import-catalog <file.lrcat>` is dry-run by default and prints the
refusal with the tables and columns it wanted when the shape differs — which is
a result, not a failure.

---

## Three gaps that are NOT waiting on a person

Recorded because "waiting on the owner" is a comfortable place to put something
that is actually unfinished.

~~**v3.28's fix is construction-tested, not effect-tested.**~~ **Closed by
v3.41 — and it found something.** The test went into CI rather than onto anyone's
machine, following the ffmpeg precedent from v2.45, so no install was needed.

The four assertions that protect the photographer's metadata passed on the first
run: the three exiftool behaviours v3.28 took on trust are correct. The fifth
failed. `preserve_existing=False`, the documented escape hatch, emitted a bare
`-IPTC:Keywords=` and then `-IPTC:Keywords+=ours`, and those two do not net to
"only ours" in one invocation — the photographer's keyword survived a write that
had been explicitly asked to replace everything.

No construction test could have found it. The arguments were exactly what the
docstring described; exiftool simply did not compose them that way.

**v3.29's second half did not run.** The charter asked for `evaluate()` re-run
with and without the non-human rows, so that if the delta is material every
published personalisation figure could be marked as computed over polluted
labels. That needs the same correction set as ask 2. The provenance fix shipped;
the impact measurement did not.

**`24-transcript-edit.png` is still synthetic**, and declared as such. It needs
footage with speech in it; the owner's working copy of the source clip is no
longer on this machine.

---

## Closed since the last count

Six items that had been sitting as "NOT MEASURED" turned out to be perfectly
runnable once someone tried — v3.14, v3.15, v3.19, v3.20, v3.21, v3.27, measured
during the v3.1–v3.27 close. Two of them were only unmeasured because nobody had
attempted the measurement, which is a different and less comfortable reason than
"we are waiting on the owner".

`BLOCK-v3.1-v3.27-CLOSE.md` has those numbers. The lesson is on this page
because it will apply again: before recording something as blocked, try it.

---

### 5. Which palette is canonical — unblocks the design-token ratchet

Found 2026-09-09, auditing what the design-system track actually shipped.
Three files hold a brand ramp and no two agree:

| where | brand ramp | what it is |
|---|---|---|
| `design-system/tokens.json` | `#c4b9a9` `#988b78` `#6a6052`, still **named** `indigo` / `violet` / `pink`, alongside untouched `indigo-b` `#5841C7` etc. | Phase A's source of truth, holding values from a mid-flight version of the warm palette |
| `pixcull/report/templates/results.html` | `#d5b584` `#eaca98` `#93743f` | what a photographer actually sees |
| `scripts/brand/pixcull-brand.json` | `#f2ead9` `#dfcfae` `#c2a878` | the brand kit, what the README banner is drawn from |

The design system was never told about the redesign that came after it.
Phase A shipped a token file and a "no new visual debt" ratchet; the
visual redesign shipped separately; nobody reconnected them.

This is most of the ratchet's number. `scripts/lint_design_tokens.py`
counts a hex as debt when it is *not one of the design-system tokens*, so
every use of the shipped `#d5b584` counts — correctly, by its own rule,
because that colour is not in the design system.

**The ask is one decision:** which of the three is canonical. Then
`design-system/tokens.json` is regenerated from it, `build_design_tokens.py`
re-emits the CSS / Swift / Python outputs, and the ratchet's number drops
on its own — it lowers its own baseline whenever violations fall.

Not engineering judgement: renaming `indigo` to something true and picking
between three golds is a brand call. Flagged rather than guessed at.

---

### 6. ~~What number the next release carries~~ — answered: 3.53.0

Found 2026-09-09, updating the public description.

`pyproject.toml` used to be bumped in lockstep with the iteration
number — v2.73 → `2.73.0`, v2.74 → `2.74.0`, v2.75 → `2.75.0`. The last
bump was commit `0a1f5f7` on 2026-08-22. Since then v2.76 through v2.99
and v3.1 through v3.53 have shipped and the version has not moved.

So two things are stale in a way that feeds each other:

| | says | actually |
|---|---|---|
| `pyproject.toml` | 2.75.0 | 78 iterations later |
| latest GitHub Release | v2.47.0 (2026-08-06) | ditto, plus 28 |

The release badge at the top of the README reads the second one, so the
first thing a visitor sees is a version from a month ago.

**The ask is one number.** The convention says pyproject mirrors the
iteration, and the current iteration is v3.53 — which makes the next
release `3.53.0`, a major bump with the meaning that carries on PyPI.
Continuing in 2.x (`2.99.0`) is the other honest reading. Both are
defensible and neither is an engineering call.

Once it is chosen: bump `pyproject.toml`, push the tag, and
`.github/workflows/release.yml` builds the wheel and sdist, runs
`twine check`, smoke-tests the wheel in a clean venv and creates the
GitHub Release with both attached. PyPI upload stays a separate manual
step, so tagging publishes nothing to PyPI on its own.

**Answered 2026-09-09: `3.53.0`,** following the convention rather than
softening it. v3.1 was already a deliberate major step in the charter
numbering; continuing to publish 2.x would have hidden something that had
already happened.

And a thing worth writing down, because I got it wrong out loud. I told
the owner that tagging would not touch PyPI and that upload was a
separate manual step. It was not: `PYPI_API_TOKEN` is configured, and the
upload step ran on any tag push where the token existed. So an ordinary
reversible act performed an irreversible one — PyPI refuses a version
number twice, and a mistagged release burns it for good.

The release now goes out on GitHub only. Upload is `workflow_dispatch`
with an opt-in that defaults to false, and
`tests/test_release_rail.py` fails if a tag push can reach it again, if
the default flips, if the reversible half gets swept behind the same
gate, or if the packaged version starts trailing the newest release
again. PyPI stays on 2.47.0 until somebody decides to move it
deliberately.

---

## Three gaps the skip ledger now names

v3.51 turned the CI skip census into `tests/ci_skip_dispositions.tsv`,
where a row marked `gap` has to say what closes it. Three do, and each is
the same one-line shape as the fix that closed the face extra:

1. **`zeroconf not installed`** — multi-machine sync discovery, three
   tests, no CI coverage. Closed by adding the `sync` extra to the
   hermetic install.
2. **`shot detection extra not installed`** — README claim 17 says a reel
   candidate never spans a hard cut. Closed by adding `pixcull[shots]`.
3. **`scikit-image unavailable`** — the public-domain astronaut face.
   v3.50 installs it, so this should already be gone; if the reason
   reappears the install did not take.

These are engineering, not owner asks. They are here so the next block
starts from a list rather than from another accident.

---

## Known red, pre-existing and now fixed

`test_visual_smoke::test_grid_and_lightbox_have_no_legacy_palette` had flagged
the disagreement-review button since before v3.20. It stayed hidden because the
local gate convention skips that file — it needs a real browser render. Fixed on
`fix/info-token-runtime-palette-guard`: the button never hard-coded a colour, the
dark-theme `--c-info` value itself sat in the one-step gap between the static
guard (`b >= 190`) and the runtime one (`b > 180`).
