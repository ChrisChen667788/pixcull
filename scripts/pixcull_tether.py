"""P2.2 — CLI helper for live-cull tether watching.

For the photographer who doesn't run the PixCull server during a
shoot but still wants live verdicts. Spawns a watcher process that
polls a Lr/C1 tether destination folder and prints live decisions.

Usage:
    # Watch a Lr tether dest folder
    python scripts/pixcull_tether.py \\
        ~/Pictures/Lightroom-Tether/2026-05-16-wedding

    # With a vertical for per-batch scoring policy
    python scripts/pixcull_tether.py \\
        --vertical wedding \\
        ~/Pictures/Lightroom-Tether/2026-05-16-wedding

Ctrl-C stops the watcher; partial scores.csv is preserved under
``/tmp/pixcull_demo/tether_<session>/output/scores.csv`` for later
review via the PixCull browser UI.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

from pixcull.tether import start_session


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("folder", type=Path,
                    help="Lr/C1 tether destination folder")
    p.add_argument("--vertical", default=None,
                    help="optional per-batch vertical "
                         "(wedding/wildlife/etc) for scoring policy")
    p.add_argument("--session-id", default=None,
                    help="optional explicit session_id (default: random)")
    args = p.parse_args()

    if not args.folder.is_dir():
        print(f"ERROR: {args.folder} is not a directory", file=sys.stderr)
        return 1

    print(f"[tether] watching {args.folder}", file=sys.stderr)
    if args.vertical:
        print(f"[tether] vertical: {args.vertical}", file=sys.stderr)
    print(f"[tether] press Ctrl-C to stop", file=sys.stderr)

    session = start_session(args.folder, vertical=args.vertical,
                              session_id=args.session_id)
    print(f"[tether] session {session.session_id} started", file=sys.stderr)
    print(f"[tether] results at /tmp/pixcull_demo/{session.run_id}/output/scores.csv",
          file=sys.stderr)

    # Wait for SIGINT — the watcher runs in its own thread so we just
    # park the main thread here. Print a periodic status every 30s
    # so the user knows it's alive.
    def _shutdown(signum, frame):
        print(f"\n[tether] stopping {session.session_id}…", file=sys.stderr)
        session.stop()
        s = session.status()
        print(f"[tether] final: {s['n_analyzed']} analyzed, "
              f"{s['n_failed']} failed", file=sys.stderr)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    last_count = 0
    while True:
        time.sleep(30.0)
        s = session.status()
        if s["n_analyzed"] != last_count:
            print(f"[tether] {s['n_analyzed']} photos analyzed "
                  f"(elapsed {s['elapsed_s']:.0f}s); last: "
                  f"{s['last']['filename']} → {s['last']['decision']}",
                  file=sys.stderr)
            last_count = s["n_analyzed"]


if __name__ == "__main__":
    raise SystemExit(main())
