# PixCull v3.57 → v3.61 charter — the commands nobody drives

Written 2026-09-10, the morning after 3.53.1 went to PyPI.

The previous block ended the skip-as-a-pass campaign, and the numbers
say so. Re-measured from the CI log after v3.48–v3.51 landed:

| skips in CI | before | now |
|---|---|---|
| ffmpeg (video, reel, edit, raw-proxy, audio) | 39 | **0** |
| mediapipe (face, serve-faces) | 4 | **0** |
| the packaged rescorer | 3 | **0** |
| scikit-image (public-domain face) | 1 | **0** |
| still a `gap` | 4 reasons | **1** (zeroconf) |

What is left skipping is playwright in the hermetic lane (the browser job
runs those), two model-weight lanes, the client frame that will never be
committed, and the hygiene check that has no personal username to find on
a build account. Every one of them has a row.

So this block starts somewhere else, from the first thing a new user
does. 3.53.1 is on PyPI; `pip install pixcull` now reaches strangers.
Verifying the wheel end to end turned up two commands whose advertised
path does not work, and a coverage number that explains why nobody knew.

**Seven of twenty-five top-level commands are driven by a journey test.**
v2.45 recorded "four of seventeen" and built the video journey to fix its
share. Eight commands have been added since and the ratio has not moved.
Every one of the four outages the 2031Q1 audit named was a live feature
no user path reached, and unit tests were green throughout because unit
tests exercise functions.

---

### v3.57 — the quickstart on the PyPI page does not run

`README-PYPI.md` is the long description, so it is the PyPI landing page.
Its Quickstart says:

```
# write the decisions back as XMP sidecars for Lightroom / Capture One
pixcull export ./out --xmp
```

`export` takes `--format`, `--out` and `--target`. There is no `--xmp`.
The second command a new user runs exits 2 with "No such option".

The line exists only in `README-PYPI.md` — the main README does not carry
it, which is why the repo's own reading never caught it. Published to
PyPI on 2026-09-09, where it is now the first instruction strangers see.

**Measure:** every shell command in `README-PYPI.md` runs against a real
installed wheel, or is marked as needing something the test cannot
supply. **Wrong, not late:** a quickstart is a promise made to somebody
who has no other information, so it is checked against the artifact, not
against the source tree.

**Done, and the gate found a second one while it was being written.**
The quickstart line is `pixcull export ./out` — `--format xmp` is the
default, so the flag was superfluous as well as wrong.

Checking that every command on the page exists then reported that
`serve` did not. It does; `python -m pixcull.cli` could not see it.
Typer registers a command when its decorator runs, and
`if __name__ == "__main__": app()` was sitting around line 2814 of a
3,000-line file, so the module-execution path called `app()` before
`serve`, `cut` and `library` were defined. The console script imports
the whole module first and had all twenty-five; `python -m` had
twenty-two. Two front doors to one CLI, disagreeing by three commands,
one of them the one that opens the review page.

Moved to the end of the file, where it has to be. Two tests hold it: the
command sets have to match, and nothing may be registered after the
`__main__` block — the failure mode is silent, the command simply is not
listed.

### v3.58 — `view-folder` will not create the folder it was asked for

`pixcull view-folder <run> --out <dir>` is v2.99, the delivery folder,
and the first item in **What's new** on both front doors. Pointed at a
directory that does not exist yet it raises

```
FileNotFoundError: [Errno 2] No such file or directory: '…/_目录.json'
```

as an unhandled traceback. Its sibling `pixcull proof-sheet --out <dir>`
creates the directory and works. Same block, same shape of argument, two
behaviours — the twin-path drift this repository keeps producing.

**Measure:** both commands, pointed at a path that does not exist, write
their output. **Wrong, not late:** the fix is not only `mkdir -p`; a
command that cannot proceed should say so in a sentence rather than
printing a traceback at a photographer.

**Done, and "it forgot mkdir" was not the mechanism.** The destination
was created as a *side effect* of `out.parent.mkdir` while copying the
first photograph. So it existed whenever there was something to copy and
did not when there was nothing — every frame culled, or `--only`
matching none of them. A photographer who runs this before deciding
anything has no keeps yet, which makes the crash the normal first
encounter rather than an edge case. It is created up front now, as
`proof_sheet.py` has always done.

Fixing the traceback left the softer half of the same defect: a green
tick over "0 photographs", handed to somebody who asked for a folder to
give a client. It now says which filter matched nothing, suggests
`--only all`, and exits non-zero.

### v3.59 — a journey for the eighteen commands that have none

Not a full test each. The cheapest thing that would have caught both
defects above: invoke the command the way its own help says to, against
a real run, and assert it exits zero and produces the file it claims.

**Measure:** the count of top-level commands with no journey coverage
goes from 18 to 0, or a command is listed with the resource it needs
that CI cannot provide. A gate fails when a new command arrives without
either. **Wrong, not late:** eighteen thorough tests is a month and will
not be written; eighteen shallow ones are a day and would have caught
`--xmp` and the missing `mkdir`. Depth is the enemy here.

**Done: four driven, twenty-one listed with the reason they cannot be.**
The census fails when a command is in neither table, which is the rule
v3.51 applied to skips, applied to commands.

Two things it taught while being written.

The first fixture was `present_run` — rows without pictures — and three
journeys failed on it, because `export`, `contact-sheet` and
`view-folder` all resolve a filename to an original on disk and with no
originals they correctly do nothing. That is the fixture being wrong,
not the commands. They run against the six committed sample photographs
now.

The second is the sharper one. The empty-delivery check first used
`--only client`, which exits early on "no client picks recorded" —
*before* reaching the code that used to crash. It passed, and a mutation
restoring v3.58's defect went straight through it. A test that passes
for the wrong reason is the exact thing this block is against, so it now
builds a run where every frame is culled and asks for the keeps. Both of
this block's opening defects are caught by mutation.

### v3.60 — `pip install pixcull` installs pytest, ruff and yapf

Verified in a clean venv against the published wheel: a plain install
brings pytest 9.1.1, ruff 0.16.6 and yapf 0.43.0 into a photographer's
environment. They come through `pyiqa`, which lists its own development
tooling as runtime dependencies.

**Measure:** name the packages that arrive and are not needed at run
time, then decide per package: drop the dependency, vendor the one
function used, or accept it and write down why. **Wrong, not late:**
`pyiqa` supplies real scoring, so removing it is a product decision, not
a packaging one. If it stays, the honest outcome is a written note, not
a silent 50 MB.

### v3.61 — the last `gap` row

`zeroconf not installed` — three tests in `test_sync_discovery.py`.
Multi-machine sync discovery is README claim 14 and has no CI coverage.
The ledger already names the closer: add the extra to the hermetic
install, the same one line as v3.50's face extra.

**Measure:** the three run. **Wrong, not late:** if zeroconf cannot
install on the runner, the row changes from `gap` to `deliberate` with
the reason, and that is a real answer too.

---

## Deliberately declined

**Regenerating the screenshots.** Measured: not stale. The session-health
chip added in v3.21 only renders on a run with faults, v3.31's changes
are inside it, and `--c-info` moved `#6fa7bd` to `#72a4b2` on one button.
The bigger reason is that the current images come from a 19-frame museum
shoot whose source files are not in the repository; re-shooting from the
six committed samples would replace a dense grid with a sparse one.
Updating them needs the owner's source folder.

**§5.1, the 212 emoji.** Still the design-system roadmap's highest-value
short-term item and still wants its own block, with a before and after.
