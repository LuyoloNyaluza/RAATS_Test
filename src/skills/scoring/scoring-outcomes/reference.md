# Scoring outcomes

| Tool result | Meaning | Say |
|---|---|---|
| error "discovery has not run yet" | The coordinator called scoring too early. | "Scoring refused: discovery has not run." |
| blocked = true | Discovery was blocked by a macro window; there is nothing to score. | "Nothing to score: discovery was blocked." |
| exhausted = true | Discovery found no unused tickers; nothing to score. | "Nothing to score: sources exhausted." |
| ok = false | The news or sentiment step failed, or an earlier stage failed and the failure was passed along. | Quote the error text exactly. |

The next stage still runs and passes the result along.
