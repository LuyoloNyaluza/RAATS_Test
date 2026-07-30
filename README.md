# RAATS - Real-time Adaptive Agentic Trading System

**Project:** MSc Computer Science – University of Fort Hare  
**Student:** Luyolo Nyaluza  
**Email:** luyolon@hotmail.com  

---

## Overview
RAATS (Real-time Adaptive Agentic Trading System) is an agentic AI system designed for adaptive real‑time trading. It combines:

- **Local LLMs** (via Ollama) for strategy selection and reasoning  
- **Retrieval‑Augmented Generation (RAG)** with vector stores (FAISS/Chroma)  
- **Financial data collection** (yfinance, technical indicators)  
- **News & sentiment analysis** (spaCy, TextBlob/VADER)  
- **Modular agent orchestration** (LangGraph)  
- **Risk‑managed execution** with latency monitoring  
- **Scalable deployment** using Docker Compose  

The project is structured to support a 12‑week MSc research plan, with weekly learning objectives, hands‑on tasks, and deliverables.

---

## Repository Structure
```
RAATS/
│
├── data/                 # Raw & processed market data, news corpora
├── docs/                 # Documentation, weekly plans, reports
├── notebooks/            # Jupyter/Colab experiments
├── src/                  # Python source code
│   ├── agents/           # LangGraph agent definitions
│   ├── data/             # Data ingestion modules
│   ├── llm/              # LLM wrappers & prompting utilities
│   ├── rag/              # Retrieval & generation pipelines
│   ├── risk/             # Risk‑check & position‑sizing logic
│   └── execution/        # Trade execution (paper/live) adapters
│
├── tests/                # Unit & integration tests
├── docker/               # Docker‑compose, Dockerfiles
├── requirements.txt      # Python dependencies
├── setup_week1.sh        # Helper script for Week 1 environment setup
├── RAATS_Weekly_Plan.md  # Detailed 12‑week plan with learning resources
└── verify.txt
```

## Getting Started
1. **Clone the repo** (if you haven’t already)  
2. Run the setup script: `./setup_week1.sh` (or follow the manual steps inside the script)  
3. Activate the virtual environment: `source venv/Scripts/activate`  
4. Test Ollama: `ollama run llama3 "What is the sentiment of the word 'bullish'?"`  
5. Explore the notebooks in `notebooks/` to begin experimentation.

## License
This project is for academic purposes only. No financial advice is provided.

---
*Last updated: 30 July 2026*