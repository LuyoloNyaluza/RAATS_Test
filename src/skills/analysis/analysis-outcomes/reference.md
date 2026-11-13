# Analysis outcomes

| Tool result | Meaning | Say |
|---|---|---|
| final_invest non-empty, approval_response = "APPROVE" | The human approved the batch. | "Approved: <tickers as returned>." |
| session_blocked = true and approval_response is anything other than APPROVE | The batch was not approved (the loop treats any other response as not approved). | "Batch not approved (<approval_response>); nothing was added." |
| session_blocked = true, no non-APPROVE response | Blocked before approval: a macro event window or an insufficient balance. | "Batch blocked before approval; no trades." |
| final_invest empty, not blocked | Analysis finished but no ticker passed. | "No tickers passed analysis." |
| exhausted = true | Nothing to analyse; discovery sources ran out. | "Nothing to analyse: sources exhausted." |
| ok = false | A stage failed (analysis, or an earlier one passed along). | Quote the error text exactly. |

Never add, remove or reorder tickers.
