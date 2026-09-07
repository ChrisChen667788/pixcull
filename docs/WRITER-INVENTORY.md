# Every writer that puts a file where the photographer may already have one — v3.28

v3.23 found `write_xmp` building a fresh sidecar over whatever was there,
destroying hand-set ratings, labels and keywords. That was one writer, found
while answering a charter item that said it might already be correct.

This is the sweep for the rest of the class. **The inventory is published even
where nothing was wrong**, because the two defects this block is built on had
already evaded ordinary attention — "we looked and found nothing" has to show
what it looked at.

## The writers

| writer | writes where | if something is already there | verdict |
|---|---|---|---|
| `io.xmp.write_xmp` | `<original>.xmp`, beside the photograph | **fixed in v3.23** — existing rating and label win, their keywords stay, only `PixCull:*` are replaced | safe |
| `io.iptc_embed.write_iptc_to_file` | **inside the photograph** | **was destroying it — fixed here.** See below | safe |
| `_export_xmp` target `collected` | `<run>/xmp/` | PixCull's own directory; a second export replaces the first | allowed |
| `export.provenance.write` | beside the export | PixCull's own file, one per export | allowed |
| `export.proof_sheet.write_proof_sheet` | a folder the photographer names | writes derivatives and one HTML file into it | **see open question** |
| `export.view_folder.write_view_folder` | a folder the photographer names | copies, never links | **see open question** |
| `tether._write_sidecar` | the tether destination | `write_xmp`, so v3.23's rule applies | safe, opt-in |
| `pipeline` run outputs | `<run>/output/` | PixCull's own directory | allowed |
| `scoring.m3` verdict cache | `~/.pixcull/cache/` | append-only, content-keyed | allowed |
| `pipeline.detector_cache` | `~/.pixcull/cache/detectors/` | content-keyed, atomic replace | allowed |

## The one that was wrong, and it was worse than v3.23

`write_iptc_to_file` writes **into the photograph**, and it was doing all three
of the things v3.23 fixed in the sidecar:

```
-XMP:Rating=<ours>      # overwrote theirs, unconditionally
-XMP:Label=<ours>       # same
-IPTC:Keywords=         # cleared EVERY keyword in the file
-XMP-dc:Subject=        # same
```

with `-overwrite_original` set by default, so exiftool kept no `_original`
backup to recover from. A photographer who had keyworded and rated their
originals in Lightroom or Capture One lost it inside the files themselves.

It now follows the same rule as the sidecar: their rating and label win, their
keywords are untouched, and only PixCull's own previous keywords are removed —
by value, with `-Keywords-=`, not by clearing the tag.

`preserve_existing=False` restores the old behaviour for a caller that means it.

**Not verified against exiftool.** It is not installed on this machine, so the
command line is asserted as a pure function (`build_args`) rather than by
running it. A rule about somebody's photographs should not go untested because a
binary is missing — but this is a construction test, not an effect test, and the
distinction matters.

## Open question, not a defect

`proof_sheet` and `view_folder` write into a folder the photographer names on the
command line. If they name a folder that already has work in it, files are
overwritten by name. That is arguably correct — they asked for output there —
and arguably the same trap as v3.23 with a different shape.

It is recorded here rather than fixed because the answer depends on what the
owner expects from an output directory, and guessing would produce either a tool
that refuses to overwrite its own last export or one that quietly eats a folder.

## How to extend this

A new writer belongs in the table. The question is always the same one and it
has never been asked systematically before this page: *if something is already
there, what happens to it* — demonstrated by a test that puts something there
first, not by reading the code and forming an opinion.
