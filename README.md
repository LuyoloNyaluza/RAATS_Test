# RAATS - Real-time Adaptive Agentic Trading System

**Project:** MSc Computer Science – University of Fort Hare  
**Student:** Luyolo Nyaluza  
**Email:** luyolon@hotmail.com  

## Overview
RAATS is an agentic AI system for adaptive real‑time trading that combines:
- Local LLMs (via Ollama) for strategy selection and reasoning
- Retrieval‑Augmented Generation (RAG) with vector stores (FAISS/Chroma)
- Financial data collection (yfinance, technical indicators)
- News & sentiment analysis (spaCy, TextBlob/VADER)
- Modular agent orchestration (LangGraph)
- Risk‑managed execution with latency monitoring
- Scalable deployment using Docker Compose

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
└── setup_week1.sh        # Helper script for Week 1 environment setup
```

## Getting Started
1. Clone the repo.
2. Run `./setup_week1.sh` (or follow the manual steps in the script).
3. Activate the virtual environment: `source venv/bin/activate`.
4. Start exploring the notebooks in `notebooks/`.

## License
This project is for academic purposes only. No financial advice is provided.