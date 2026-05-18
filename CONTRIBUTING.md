# Contributing to PixCull

Thanks for your interest. PixCull is a single-author project that took shape
through hundreds of small, scoped commits — the same rhythm works for
contributions.

## Quick start for contributors

```bash
git clone https://github.com/ChrisChen667788/pixcull.git
cd pixcull
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q                       # 240+ tests, ~60 s on Apple Silicon
python scripts/serve_demo.py    # localhost:8770
```

## Workflow

1. **One concern per PR.** A change like "filter pill row no longer wraps
   on 13" displays" is much easier to review than "polish the UI".
2. **Tag with a prefix** in the commit subject so the log stays readable:
   - `P-UX-N` for a results-page UX milestone
   - `INFRA-N` for sync / tether / API plumbing
   - `Vx.y` for a versioned model / pipeline change
   - `docs:` / `tests:` / `chore:` for non-code work
3. **Tests.** Anything touching `pixcull/scoring/`, `pixcull/pipeline/`, or
   `scripts/serve_demo.py` needs a pytest entry. UI-only changes need a
   browser smoke note in the PR description (size, screen, browser).
4. **No emojis in code** — keep `pixcull/`, `scripts/`, `tests/` ASCII so
   `grep` stays useful. Emojis are fine in commit messages, README,
   issues, and UI labels.
5. **Don't open up sync / license / billing layers** without flagging it
   first — those are intentionally minimal and any growth needs an
   explicit design discussion in an issue.

## What's a good first PR?

- A new entry in the cull-reason taxonomy
  (`_CULL_REASONS` in `scripts/serve_demo.py` + `I18N_SIM_REASON`-style
  label in `pixcull/report/templates/results.html`)
- A new vertical's scoring policy (`pixcull/verticals.py`)
- A new scene template (`pixcull/scoring/templates/scene_templates.yaml`)
- A new XMP keyword in the export path (`pixcull/io/xmp.py`)
- Translating the UI to another language (extend the `I18N_*` maps)

## Anything that's NOT a good first PR

- Rewriting the rescorer (V1.x → V2.x took weeks)
- New scoring axes (the 6-axis rubric is calibrated against thousands
  of human labels; adding a 7th breaks the rescorer joblibs)
- Multi-user / multi-tenant changes (V28 already exists; talk first)

## Code style

- Python: PEP 8, 80-col soft limit, no formatter enforced. Type hints
  where it clarifies intent, not as decoration.
- JS in `results.html`: no framework, no build step. Prefer plain DOM
  + delegated event listeners. Read existing code first — there are
  patterns you'll want to mirror (`registerModal`, `pushUndo`, etc).
- CSS: keep variables in `:root` block. Don't introduce a preprocessor.

## License

By contributing, you agree your code is released under the MIT License
that covers the rest of the project.
