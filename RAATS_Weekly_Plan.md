# RAATS Project Weekly Plan (Starting 3 August 2026)

**Goal:** Develop an Agentic AI System for Adaptive Real-Time Trading (RAATS) using LLM-guided strategy selection and Python-based execution.

**Student:** Luyolo Nyaluza (MSc Computer Science, University of Fort Hare)  
**Email:** luyolon@hotmail.com  

---

## Overview
- **Duration:** 12 weeks (3 Aug 2026 – 25 Oct 2026)
- **Weekly Commitment:** ~15‑20 hours (adjust as needed)
- **Deliverables per week:** Learning objectives, hands‑on tasks, milestones, and a brief reflection note.
- **Reminder Setup:** You can create a recurring calendar reminder (e.g., every Monday 09:00) to review the plan and log progress.

---

## Weekly Work Schedule
- **Monday–Thursday:** Full working sessions (morning + afternoon/evening)
- **Friday:** Work until late afternoon; break starts late Friday (evening)
- **Saturday:** Full day of rest (no planned project work)
- **Sunday:** Resume work late in the evening (afternoon/evening) to prepare for the week ahead

---

## Week‑by‑Week Plan

| Week | Dates (2026) | Focus | Learning Resources | Hands‑On Tasks | Milestone / Deliverable |
|------|--------------|-------|--------------------|----------------|-------------------------|
| 1 | Aug 3 – Aug 9 | Project Kick‑off & Environment Setup | Hugging Face LLM Course (Modules 1‑2), Ollama docs, Docker basics, VS Code setup | Install Ollama & Docker, set up VS Code, create GitHub repo, test Ollama model, create venv, install requirements, basic Ollama‑LangChain demo | Repo created, environment ready, initial Ollama test notebook |
| 2 | Aug 10 – Aug 16 | LLM Foundations & Prompt Engineering | Hugging Face Course Chapters 3‑4, Prompting Guide | Experiment with Ollama models, write sentiment prompts, log results | Notebook with 5 prompt experiments + report |
| 3 | Aug 17 – Aug 23 | Retrieval‑Augmented Generation (RAG) Basics | LangChain RAG tutorial, FAISS & Chroma docs | Ingest financial news CSV, build RAG chain for sentiment queries | Working RAG pipeline + stored index |
| 4 | Aug 24 – Aug 30 | Natural Language Processing for Financial Text | spaCy 101, financial NLP survey | Tokenize headlines, extract entities, compute sentiment with TextBlob/VADER | Processed corpus + sentiment CSV |
| 5 | Aug 31 – Sep 6 | Technical Indicators & Market Data Collection | yfinance, pandas‑ta, Investopedia TA guide | Pull OHLCV for watchlist, calculate SMA/EMA/RSI/MACD, store in PostgreSQL Docker | Data collection script + DB schema |
| 6 | Sep 7 – Sep 13 | Agentic AI & LangGraph | LangGraph docs, “Building Agentic Systems” blog | Design agent graph: Data Collector → Analyst (LLM) → Executor (mock trade), implement paper‑trading loop | Runnable LangGraph agent (no real broker) |
| 7 | Sep 14 – Sep 20 | Risk Management & Execution Latency | Risk‑based position sizing articles, QuantStart latency | Add risk‑check module, time execution with perf_counter, log latency | Risk module + latency log (target <200 ms) |
| 8 | Sep 21 – Sep 27 | Integration: End‑to‑End Paper Trading | Review prior weeks, Alpaca paper API (optional) | Connect data, RAG, LLM strategist, risk, mock executor; run 1‑day historical simulation; produce performance report | End‑to‑end paper‑trading notebook + metrics |
| 9 | Sep 28 – Oct 4 | System Scalability & Resource Utilization | Docker‑Compose scaling, Prometheus + Grafana intro | Docker‑compose for Ollama, PostgreSQL, Vector DB, Agent API; add health checks; simulate load, monitor CPU/Memory | Docker‑compose + basic Grafana dashboard screenshot |
|10 | Oct 5 – Oct 11 | Evaluation Framework | Define metrics, backtesting libs (zipline, backtrader) | Write evaluation script across historical windows, compute Sharpe, max DD, compare baseline vs LLM‑guided | Evaluation report (PDF/MD) |
|11 | Oct 12 – Oct 18 | Documentation & Presentation Prep | Academic writing guides, slide design tips | Write project report, build slide deck, record 5‑min demo video | Draft report + slide deck + video |
|12 | Oct 19 – Oct 25 | Final Review, Refinement & Submission | Self‑review, peer feedback (optional) | Incorporate feedback, fix bugs, finalize code cleanup, ensure README, requirements, Dockerfile | Final repo, report, slides, video submitted |

---

## Suggested Learning Resources (Free / Low‑Cost)

| Topic | Resource | Link |
|-------|----------|------|
| LLMs & Prompting | Hugging Face Course (you’re enrolled) | https://huggingface.co/learn/nlp-course/chapter1 |
| Ollama | Official Docs | https://ollama.com/docs |
| Docker | Get Started | https://docs.docker.com/get-started/ |
| LangChain / LangGraph | Documentation | https://python.langchain.com/docs/ |
| Vector Stores | FAISS Github | https://github.com/facebookresearch/faiss |
| | Chroma Docs | https://docs.trychroma.com/ |
| Financial Data | yfinance | https://pypi.org/project/yfinance/ |
| Technical Indicators | pandas‑ta | https://github.com/twopirllc/pandas-ta |
| NLP | spaCy 101 | https://spacy.io/usage/spacy-101 |
| Sentiment | TextBlob / VADER | https://textblob.readthedocs.io/en/dev/ |
| Risk Management | QuantStart Articles | https://www.quantstart.com/articles/ |
| Backtesting | Backtrader | https://www.backtrader.com/ |
| Monitoring | Prometheus + Grafana Intro | https://prometheus.io/docs/introduction/overview/ |
| Academic Writing | University of Fort Hare Library Guides | (check internal) |

---

## How to Set Up Weekly Reminders (Optional)

You can create a simple recurring calendar event (e.g., Google Calendar, Outlook) titled **“RAATS Weekly Review”** every Monday at 09:00 with the description:

> Review the week’s plan, log completed tasks, note blockers, and adjust next week’s goals.

If you prefer a terminal‑based reminder, you could use a cron job (Linux/WSL) or Windows Task Scheduler to pop up a message. Example cron line (runs every Monday 09:00):

```
0 9 * * 1 echo "RAATS Weekly Review: Check plan and log progress" >> ~/raats_reminder.log
```

---

## Next Steps (Immediate)

1. **Create the GitHub repository** for RAATS (private or public as you prefer).
2. **Clone it locally** and set up a `dev` branch.
3. **Install Ollama** and test a model (`ollama run llama3`).
4. **Begin Week 1 tasks** (environment setup) and log your progress in a `journal.md` file inside the repo.

---

*Wishing you a productive and insightful project journey!*  
*Generated on 28 July 2026.*