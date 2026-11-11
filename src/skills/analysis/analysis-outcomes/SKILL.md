---
name: analysis-outcomes
description: Use when run_analysis has returned and you must report the batch result (approved tickers, a rejection, an empty result, a block or a failure).
---

# Reporting an analysis outcome

**Step 1:** Call run_analysis once and wait for it; it can take a long time because a human decides
on Discord. Never call it again while it runs.

**Step 2:** Read its JSON. If final_invest is non-empty and approval_response is APPROVE, report
those tickers exactly as returned, and stop.

**Step 3:** Otherwise read `reference.md` in this skill's directory for what the outcome means and
the wording to use. Do not guess, and never present a rejected or blocked batch as approved.

**Step 4:** Report in at most four lines. You cannot approve, reject, retry or trade.
