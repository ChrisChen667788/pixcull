# Every producer of `annotations.jsonl`, and whether its provenance is true — v3.29

`annotations.jsonl` is the file the taste profile learns from. Before v3.9 every
writer stamped `"source": "human"`, because it was hard-coded. v3.9 fixed one
producer. This is the sweep for the rest.

Published in full, including the rows where nothing was wrong.

## The producers

| producer | writes | provenance | learned from? |
|---|---|---|---|
| lightbox / API `POST /annotation/` | a person's keep/maybe/cull | `human` — or one of the restricted values a client may pass (v3.9) | yes |
| compare modal, winner | the frame chosen as best | `compare_winner` | yes |
| compare modal, rejected siblings | N−1 near-identical frames | `compare_rejected` | **no** — v3.9. Their axis stars are the winner's, so averaging them into the cull bucket flattens the gap `axis_weights` is built from |
| Lightroom / Capture One round-trip | ratings read back out of sidecars | `lr_round_trip` | yes |
| **cloud sync download** | annotations from another machine | **was: whatever the peer sent** | **was: yes** |
| blind-labelling CLI | the owner judging with no system opinion on screen | stamps `label_provenance: blind` on the profile | yes, and it is the only provenance the personalisation gate trusts |
| client picks | what the client pointed at | **never written here** — `client_picks.jsonl`, because this index is latest-wins on the whole record | no |

## The one that was wrong

The sync handler wrote the peer's record **verbatim**, minus a single routing
field:

```python
clean = {k: v for k, v in rec.items() if k != "__run_id"}
f.write(json.dumps(clean) + "\n")
```

Three things follow, and all three were live:

1. **Arbitrary keys.** A remote record could carry anything, into a file six
   consumers read.
2. **Self-declared provenance.** A peer could send `"source": "blind"` —
   `blind` is one of the two values `PersonalProfile.TRUSTED` accepts.
3. **No mark of origin.** A correction another photographer made on their own
   machine was indistinguishable from one made here, so `personal_learn` fitted
   one taste profile to two people.

That third one is v3.9's defect with a different producer, which is the reason
this sweep exists rather than a spot fix.

Now: keys are whitelisted, `source` goes through the same allowlist a local POST
does, and every synced record is stamped `synced: true` — which
`gather_examples_from_runs` uses to leave it out. It is a real human correction;
it is not *this* photographer's, and this file exists to learn one person's taste.

## What multi-shooter sync is still for

Nothing here stops synced annotations reaching the report, the bias audit, the
review sheet or the export. A second shooter's judgement is worth having and
worth seeing. It is worth having *as theirs* — the exclusion is from one
consumer, the personal taste profile, and the mark is what makes every other
consumer able to choose.

## How to extend this

A new producer belongs in the table with an honest answer in the provenance
column. The test that matters is not "does it write a source" but "is the source
it writes true", and the only way to check that is to know who or what actually
made the label.
