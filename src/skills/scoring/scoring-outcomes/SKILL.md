---
name: scoring-outcomes
description: Use when run_scoring returns anything other than a plain ok result (blocked, exhausted or ok=false) and you need to explain what it means in your report.
---

# Reporting a scoring outcome

**Step 1:** Call run_scoring once and read its JSON.

**Step 2:** If ok is true and neither blocked nor exhausted is true, report how many candidates
were scored and stop.

**Step 3:** Otherwise read `reference.md` in this skill's directory for what the outcome means.
Do not guess.

**Step 4:** Report in at most three lines. Never retry run_scoring, and never run discovery
yourself.
