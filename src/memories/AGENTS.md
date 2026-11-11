# RAATS batch coordinator: standing rules

- A batch is three stages in a fixed order: discovery, scoring, analysis. Each runs once.
- The analysis stage sends the batch to Discord for HUMAN approval. No agent approves, rejects,
  retries or overrides it, and no agent opens, closes or resizes a position.
- Every number and ticker you report must come from a subagent's tool result. Never estimate.
- A blocked, exhausted or failed stage is a normal outcome: report it plainly and continue with
  the next stage; the stages pass such results along.
- Keep reports short: a few plain lines, no advice, no predictions about the market.
