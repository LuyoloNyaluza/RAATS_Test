"""
src/agents/permissions.py

Scoped write access, exactly as in the newsletter example:

    research_permissions = [
        FilesystemPermission(operations=["read", "write"], paths=["/research/**"], mode="allow"),
        FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
    ]
    editor_permissions = [
        FilesystemPermission(operations=["write"], paths=["/research/**"], mode="deny"),
    ]

Each subagent may write only inside its own zone (its scratch notes for the batch); the main
agent may READ those zones but must not write into them, and is free to write its own report
under /reports/.

Rules are first-match-wins, so a subagent's specific allow beats the broad write deny. A
subagent's `permissions` REPLACES the parent's rules; it does not add to them.

These rules govern the agents' BUILT-IN file tools (read_file / write_file / ...) on their
virtual filesystem. They do not govern our own tools. What keeps a subagent away from the
positions is that it has no tool that can touch them and does not hold the MT5 write token
(src/data/mt5_orders.py): only the position engine does.
"""

from dataclasses import dataclass
from typing import List

try:                                              # the real class, when deepagents is installed
    from deepagents import FilesystemPermission
except ImportError:                               # same fields, so the definitions still import
    @dataclass(frozen=True)
    class FilesystemPermission:                   # type: ignore[no-redef]
        operations: List[str]
        paths: List[str]
        mode: str = "allow"


def _own_zone(zone: str) -> List[FilesystemPermission]:
    return [
        FilesystemPermission(operations=["read", "write"], paths=[zone], mode="allow"),
        FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
    ]


# one zone per subagent; the task tells each one which folder inside its zone to use
discovery_permissions = _own_zone("/candidates/**")      # /candidates/<batch>/pool.md
scoring_permissions = _own_zone("/scored/**")            # /scored/<batch>/<TICKER>.md
analysis_permissions = _own_zone("/analysis/**")         # /analysis/<batch>/<TICKER>.md

# the main agent reads every zone, writes none of them; its own report goes to /reports/
main_permissions = [
    FilesystemPermission(operations=["write"], paths=["/candidates/**", "/scored/**", "/analysis/**"],
                         mode="deny"),
]
