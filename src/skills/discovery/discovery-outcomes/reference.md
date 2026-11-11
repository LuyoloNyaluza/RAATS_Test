# Discovery outcomes

| Tool result | Meaning | Say |
|---|---|---|
| blocked = true | A macro event window is active; discovery returned empty arrays on purpose. | "Discovery blocked by a macro event window; no candidates this batch." |
| exhausted = true | No unused equities were left across Yahoo gainers and most-active for this batch. | "Discovery sources exhausted; no new candidates." |
| ok = false, error mentions "Expected 50 instruments" | The universe was short of 50 after gainers, most-active and (batch 1) the emergency list. | "Universe incomplete: <error>." |
| ok = false, error mentions "No valid market pricing data" or DNS / "Could not resolve host" | Yahoo was unreachable (network problem). | "Yahoo unreachable: <error>." |
| ok = false, any other error | An unexpected failure. | Quote the error text exactly. |

In every case the next stage still runs and passes the result along. Do not suggest fixes that
involve trading.
