"""v0.10-P1-1 — studio team workflows.

Builds on top of the V28 multi-user profile layer (pixcull/users.py)
to add the workflow shape an actual photo studio needs:

  * **Team taste aggregation** — pool every team member's
    per-axis preference into one "studio baseline" and surface
    the discrepancy ("二摄 prefers higher contrast than 主摄").
  * **Head-shooter override** — in a LAN sync event, one user
    can be designated head_shooter; their edits trump everyone
    else's in conflict resolution.

These are *opt-in*: a solo photographer never sees them; a
studio of 3-5 photographers gets a `/admin/team_taste` page +
the conflict modal's auto-pick-head-shooter branch.
"""

from pixcull.team.taste import (
    PROFILE_AXES,
    aggregate_taste,
    discrepancy_report,
    load_user_taste,
)
from pixcull.team.roles import (
    clear_head_shooter,
    get_head_shooter,
    set_head_shooter,
)

__all__ = [
    "PROFILE_AXES",
    "aggregate_taste",
    "discrepancy_report",
    "load_user_taste",
    "clear_head_shooter",
    "get_head_shooter",
    "set_head_shooter",
]
