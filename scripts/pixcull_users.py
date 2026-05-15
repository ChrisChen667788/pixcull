"""V28 — CLI helper for multi-user / team sample bank management.

Use this when you don't have the PixCull server running (e.g. setting
up a fresh studio install, scripting via shell). The same operations
are exposed under /api/v1/users for the server-running case.

Usage
=====
    # List all user profiles + which one is active
    python scripts/pixcull_users.py list

    # Create a new user profile
    python scripts/pixcull_users.py create alice

    # Subscribe alice's wedding vertical to the studio's shared team bank
    python scripts/pixcull_users.py subscribe alice wedding wedding-team-1

    # Unsubscribe (restore alice's personal wedding bank)
    python scripts/pixcull_users.py subscribe alice wedding ""

    # Switch active user (just prints the env var hint; the actual
    # switch is via PIXCULL_USER in your shell or launcher)
    python scripts/pixcull_users.py switch alice
"""

from __future__ import annotations

import argparse
import sys

from pixcull.users import (
    create_user, get_active_user, list_users,
    subscribe_to_team_vertical,
)


def cmd_list(_args) -> int:
    active = get_active_user()
    users = list_users()
    if not users:
        print("(no user profiles found — create one with "
              "`python scripts/pixcull_users.py create <id>`)")
        return 0
    print(f"active: {active}")
    print(f"{'user_id':<24}{'verticals':>10}  status")
    print("-" * 50)
    for u in users:
        mark = "← active" if u["is_active"] else ""
        print(f"{u['user_id']:<24}{u['vertical_count']:>10}  {mark}")
    return 0


def cmd_create(args) -> int:
    try:
        result = create_user(args.user_id)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if result["created"]:
        print(f"created user '{args.user_id}' at {result['data_root']}")
    else:
        print(f"user '{args.user_id}' already exists at "
              f"{result['data_root']}")
    return 0


def cmd_subscribe(args) -> int:
    try:
        result = subscribe_to_team_vertical(
            args.user_id, args.vertical, args.team_id or "",
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if result["action"] == "subscribed":
        print(f"{args.user_id}/verticals/{args.vertical} → "
              f"team {result['team_id']}")
    else:
        print(f"{args.user_id}/verticals/{args.vertical} unsubscribed "
              f"from team (back to personal bank)")
    return 0


def cmd_switch(args) -> int:
    print(f"To switch active user to '{args.user_id}', set the env var:")
    print(f"  export PIXCULL_USER={args.user_id}")
    print(f"And restart PixCull (or the serve_demo process).")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list user profiles")

    pc = sub.add_parser("create", help="create a user profile")
    pc.add_argument("user_id")

    ps = sub.add_parser("subscribe",
                          help="redirect a user's vertical to a team bank "
                               "(empty team_id = unsubscribe)")
    ps.add_argument("user_id")
    ps.add_argument("vertical")
    ps.add_argument("team_id", nargs="?", default="")

    psw = sub.add_parser("switch",
                          help="show the env var to set for switching")
    psw.add_argument("user_id")

    args = p.parse_args()
    return {
        "list":      cmd_list,
        "create":    cmd_create,
        "subscribe": cmd_subscribe,
        "switch":    cmd_switch,
    }[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
