# PixCull v3.47 → v3.51 charter — the tests that report green by not running

Written 2026-09-09, after closing the v3.37–v3.41 block and the five
versions that fell out of it.

This block has one subject. Four times in the last ten versions the same
defect turned up: a test that exists, is committed, is counted in the
suite total, and does not run where it matters — so the tick is green and
nothing was checked. ffmpeg in v2.45, exiftool in v3.41, the whole
browser lane in v3.42, the design-token ratchet in v3.46.

Each of those was found by accident. So this block does not go looking
for another instance by intuition; it starts from the CI log. The
hermetic job prints one `SKIPPED` line per skipped test, and reading
them is the census nobody had run:

| skipped in CI | count | why |
|---|---|---|
| `test_video.py` | 25 | ffmpeg not installed |
| `test_reel_assembly.py` | 6 | ffmpeg not installed |
| `test_edit_render.py`, `test_e2e_smoke.py` | 6 | ffmpeg not installed |
| `test_raw_proxy.py`, `test_audio_events.py` | 2 | ffmpeg not installed |
| `test_client_present.py` | 4 | playwright — and the run fixture |
| `test_sync_discovery.py` | 3 | zeroconf not installed |
| `test_rescorer_is_reachable_after_install.py` | 3 | "joblib/sklearn unavailable or version-drifted" |
| `test_face.py`, `test_serve_faces.py` | 4 | mediapipe / weights unavailable |
| `test_reel_caption.py`, `_model_gate.py` | 2 | model weights not cached |

Two of those are correct and stay. The weekly real-model lane owns the
cached-weights ones. `test_repo_hygiene.py`'s skip is right for a
reason worth repeating: it checks that the maintainer's own username has
not been pasted into a doc, and on a build account there is no personal
username to leak — the machine that can leak the name is the machine
that checks for it.

The rest are this block.

---

### v3.47 — the leftovers, and the one test fixture that lived on one laptop

Closing what the last block left: the v3.37 result was never written into
its own charter, and v3.38's inventory recorded the iOS companion as
"source only" while the README claim went on reading like something
`pip install` hands you — the inventory is a document a maintainer opens,
the claim is what a photographer reads.

Then the fixture. `test_client_present.py` guards the one screen a
photographer turns toward someone who is not paying to see the machine's
opinion of their work: Shift+C hides every verdict, score and star. Four
of its tests need a served run with more than ten cards, and they were
pointed at `/tmp/pixcull_perf/perf5069` — 5,069 rows on one laptop.
Everywhere else they skipped. The server was also launched through a
hard-coded path into that laptop's venv, so even with a run they would
not have started.

**Measure:** the four tests run, in CI, against a committed fixture.
**Wrong, not late:** a generated fixture is not the realistic subject, so
the real run still wins when it is there — the fixture is the floor, not
the replacement.

### v3.48 — ffmpeg arrives after the tests that need it

v2.45 added `apt-get install ffmpeg` to CI and wrote down why: without it
four journey tests reported green having tested nothing. The step went in
**below** `Run hermetic tests`, where it serves the video-journey step
alone. Thirty-nine tests in the hermetic run — the entire video, reel,
edit-render, raw-proxy and audio-event block — have skipped on every push
since.

So v2.45's lesson was learned and its fix landed one step too late in the
file. The video block shipped across v2.42–v2.44.3 with no unit-level CI
coverage at all.

**Measure:** the ffmpeg step moves above the hermetic run; the count of
CI skips attributable to ffmpeg goes to zero, and the tests either pass
or say what is broken.
**Wrong, not late:** if moving it turns something red, that is the
finding, not a setback — those 39 tests have never run on Linux.

### v3.49 — the rescorer ships, and nothing can open it

v3.44 put the eight rescorer artifacts inside the package because
`pip install pixcull` could never resolve the working-directory path.
That was half the problem. `scikit-learn` and `joblib` are not
dependencies of this project. They arrive transitively through
`imagededup`, completely unpinned, and the artifacts are version-
sensitive pickles: loading a joblib trained under scikit-learn 1.8 with
1.9 installed raises `ModuleNotFoundError: No module named '_loss'`.

So the version of the library PixCull's learned head depends on is
decided by a deduplication package's dependency graph, and when it drifts
the failure is a stderr line nobody reads and a silent fall back to
rule-only — the exact outcome v3.44 was written to end.

`tests/test_rescorer_is_reachable_after_install.py` — my own gate, three
versions old — **skips** in CI on precisely this, rather than failing.
Written that way to be tolerant of a thin environment, which is how every
other instance in this list started.

**Measure:** declare and pin the pair; the three tests run in CI instead
of skipping; and record which scikit-learn version the committed
artifacts were pickled under, so the next drift is a readable error.
**Wrong, not late:** pinning an ML library upward hurts; the alternative
is a learned head that silently is not there, which is what the last
three versions were about.

### v3.50 — faces are a README claim with no CI coverage

Claim 4 of eighteen: InsightFace ArcFace embeddings, DBSCAN, a cross-run
face library. v3.38's inventory marked it reachable only behind
`pixcull[face]`, which is honest. What the inventory could not see is
that four tests — `test_face.py` ×3, `test_serve_faces.py` ×1 — skip in
CI for want of mediapipe and its weights, so the detector that the whole
identity feature stands on is exercised nowhere automatic.

The two `.task`/`.tflite` weights **are** in the wheel (measured in
v3.38). Only the runtime is missing.

**Measure:** install the `face` extra in a lane and let the four run; if
mediapipe cannot be installed on the runner, say so in the skip message
with the reason, which is more than "unavailable".
**Wrong, not late:** a portrait fixture that cannot be committed is a
real constraint — two of these skip on that separately, and that half
stays a documented gap rather than a synthesised face.

### v3.51 — a skip has to be a decision, once

The three versions above are instances. This one is the rule, and it is
the same shape as v3.39's deferral ledger, which worked: a
promise-shaped comment now needs a disposition, and the gate fails when
one appears without an answer.

A skip is the same kind of object. It is a claim that this test cannot
run here and that somebody thought about it. Four times running, nobody
had.

**Measure:** the CI skip census becomes a committed file with one row per
skip reason and a disposition — `covered-elsewhere`, `owner-blocked`,
`deliberate`, `gap`. A skip reason not in the file fails the suite. A
reason marked `gap` has to name what closes it.
**Wrong, not late:** the file must be keyed on the *reason*, not the test
id, or a rename rewrites the ledger; and it must be generated from a real
CI run rather than from grepping the source, because what skips on a
laptop and what skips on a runner are different lists — which is the
whole reason this block exists.

---

## Deliberately declined

**Migrating the 42 brand-gradient literals.** They are the visible half of
`OPEN-ITEMS` ask 5, and which of the three palettes is canonical is a
brand decision. Guessing it in order to make a number go down would be
the wrong kind of tidy.

**§5.1, removing 212 emoji for Phosphor icons.** The design-system
roadmap's highest-value short-term item, and out of scope for a block
about test coverage — it is a visual change across 26 files that wants
its own block and its own before/after.
