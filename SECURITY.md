# Security Policy

## Supported versions

PixCull is a single-developer project. The latest `main` is the only
supported version. Patches for older commits are not backported.

## Reporting a vulnerability

If you think you've found a security issue, **do not open a public issue**.
Email the maintainer at `hello@pixcull.dev` with:

- A short description of the issue
- A reproduction recipe (commands, payload, expected vs actual)
- The affected commit SHA from `git rev-parse HEAD`
- Your handle if you'd like credit in the fix commit

Expected turnaround: acknowledgement within 72 hours, fix or mitigation
plan within 7 days for anything that lets a remote attacker read photos,
exfiltrate annotations, or escalate within the host.

## Threat model

PixCull is designed to run locally on a photographer's machine or LAN
deployment. It assumes:

- **Trusted local user.** The CLI + server APIs are not hardened against
  a malicious operator with shell access; treat the user as already
  authorized to read every photo in the configured roots.
- **Localhost or controlled LAN.** The server listens on `127.0.0.1` by
  default. Exposing it on a public network is supported only behind a
  reverse proxy + the `X-PixCull-API-Key` header check.
- **Untrusted image input.** EXIF + IPTC parsing goes through Pillow,
  which has had CVEs. We pin Pillow ≥ 10.2 and never run unsanitized
  metadata as code, but a malicious image is still potentially a
  resource-exhaustion vector.

Things that are explicitly **out of scope**:

- DoS via a giant batch (the user shipped that batch themselves)
- Self-XSS in the results page (filenames are HTML-escaped via `esc()`;
  if you find a path that isn't, that IS in scope — see V14.0)
- Reading the user's own files (the user invoked the tool)

## What's safe to share

Annotation files (`annotations.jsonl`) and score CSVs are designed to
be portable across machines. They contain filenames, axis stars,
free-form rationale text, and the `cull_reason` taxonomy token — but
no raw images, no API keys, no license tokens. Sharing them with
collaborators or attaching them to bug reports is safe.
