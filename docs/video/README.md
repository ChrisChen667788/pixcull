# The 30-second film

`pixcull-30s.mp4` is 1920×1080, 30 fps, 30 seconds, with music and no
narration. `pixcull-30s-poster.jpg` is its title frame.

It illustrates six things PixCull does. It is not a recording of the
app: the stack, the six-spoke diagram and the proof sheet are drawn for
the film. No score, accuracy figure or time saving appears on screen.
The one number shown, 6, is how many axes the rubric has.

## What each line rests on

| On screen | In the code |
|---|---|
| Near-duplicate grouping | `pixcull/scoring/near_dup.py` — connected components over CLIP cosine similarity |
| Keep, maybe, cull — with you in control | corrections go to `annotations.jsonl` and win over the machine's verdict (`pixcull/annotations.py`) |
| Six dimensions: technical, subject, composition, light, moment, aesthetic | `pixcull/scoring/rubric.py` |
| Local first. Cloud optional. `--vlm-mode off` | `pixcull/cli.py`. Cloud judging needs a MiniMax key and asks once before it uploads; with no key a run stays on the machine. Once consent is recorded, a run with a key uploads by default, and `--vlm-mode off` is the switch that holds — the README's *What a default run actually does* has the full table. |
| XMP ratings for your editor | `pixcull/io/xmp.py` |
| Watermarked proofs for your clients | `pixcull/export/proof_sheet.py` |

## Photographs and music

Eight frames from `samples/input`, byte-identical to the copies in this
repository: `3J0A5036`, `3J0A6924`, `3J0A7544`, `3J0A7615`, `3J0A7788`,
`3J0A7790`, `3J0A7799`, `3J0A7802`. Landscapes, no people; why each of
the sample set is in it is recorded in `scripts/brand/prepare_samples.py`.

The music was synthesised for the film. It uses no samples and no
licensed track.

The film was rendered on 2026-10-06 from the tree at commit `16eff07`.
Neither file carries metadata beyond the encoder's name.
