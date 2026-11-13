---
name: discovery-outcomes
description: Use when run_discovery returns anything other than a plain ok result (blocked, exhausted or ok=false) and you need to explain what it means in your report.
---

# Reporting a discovery outcome

**Step 1:** Call run_discovery once and read its JSON.

**Step 2:** If ok is true, blocked is false and exhausted is false, report the counts and stop.
You do not need anything else.

**Step 3:** Otherwise read `reference.md` in this skill's directory for what each outcome means and
the exact wording to use. Do not guess the meaning.

**Step 4:** Report in at most three lines: the outcome, the counts the tool gave, and the meaning
from reference.md. Never retry run_discovery.
