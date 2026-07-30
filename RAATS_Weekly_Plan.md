# RAATS Project Weekly Plan (Starting 3 August 2026)

**Goal:** Develop an Agentic AI System for Adaptive Real-Time Trading (RAATS)

## Weekly Breakdown

### Week 1 (Aug 3 – Aug 9)
- Set up development environment (Python, Ollama, FAISS/Chroma, Docker)
- Initialize GitHub repo with initial structure (README, .gitignore, requirements)
- Implement basic market data collection using yfinance and store in `data/`
- Create a simple LangGraph agent that outputs a static trading signal (hold)
- Write unit tests for data ingestion module
- Document setup steps in `setup_week1.sh` and `WEEK1_SETUP.md`

### Week 2 (Aug 10 – Aug 16)
- Integrate Ollama with LangGraph for LLM‑based strategy reasoning
- Build a Retrieval‑Augmented Generation (RAG) pipeline:
  - Ingest financial news (via NewsAPI or RSS) into a vector store
  - Query the store for recent sentiment before each trading decision
- Design a simple strategy: if sentiment > threshold → buy, else → hold
- Implement paper‑trading simulation using historical data
- Add integration tests for the RAG‑enhanced agent

### Week 3 (Aug 17 – Aug 23)
- Develop risk‑management module:
  - Position sizing based on volatility (ATR)
  - Stop‑loss and take‑profit logic
  - Max drawdown and leverage limits
- Integrate risk checks into the agent workflow (pre‑execution)
- Create a backtesting framework (walk‑forward) to evaluate strategy performance
- Generate performance reports (Sharpe ratio, max drawdown, win rate)
- Write unit and integration tests for risk and backtesting modules

### Week 4 (Aug 24 – Aug 30)
- Implement execution adapters:
  - Paper trading connector (simulated exchange with realistic latency)
  - Placeholder for live exchange (CCXT) – stubbed for safety
- Add latency monitoring and logging (end‑to‑end latency from signal to order)
- Conduct end‑to‑end integration tests: data → sentiment → strategy → risk → execution
- Prepare interim report and demo notebook showcasing the full pipeline
- Update documentation (`docs/`) and reflect lessons learned in `README.md`

## Milestones
- **End of Week 1:** Functional data pipeline + basic agent
- **End of Week 2:** RAG‑enhanced strategy with paper‑trading simulation
- **End of Week 3:** Risk‑managed backtesting framework with performance metrics
- **End of Week 4:** Full end‑to‑end agentic trading system ready for live‑paper testing

## Notes
- Adjust weekly goals based on progress and feedback from supervisors.
- All code to be placed under `src/` with corresponding tests in `tests/`.
- Keep `requirements.txt` updated with new dependencies.
- Use GitHub Projects or a Kanban board to track tasks.
