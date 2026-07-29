#!/usr/bin/env python3
"""Web demo for PixCull — dev entry point for the packaged server.

v2.31 — the ~12.5k-line implementation moved INTO the package as
``pixcull/report/serve_app.py`` so a pip-installed user can run
``pixcull serve``.  Before this, the review workspace only launched from
a git clone: this file lived in ``scripts/`` and resolved every asset
path relative to a repo root that a wheel doesn't have.

``python scripts/serve_demo.py --port 8770`` still works — this file is
now a one-line forwarder so there is exactly ONE copy of the server to
maintain.  Code that needs the server's internals (tests, tooling)
should import ``pixcull.report.serve_app`` directly rather than loading
this path: a path-load would create a *second* module object whose
globals the running handler doesn't read.
"""
from pixcull.report.serve_app import main

if __name__ == "__main__":
    main()
