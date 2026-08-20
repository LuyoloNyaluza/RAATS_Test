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
├── data/
│   ├── fetch_news.py
│   └── fetch_prices.py
├── docs/
│   # Documentation, weekly plans, reports (see weeks/ and RAATS_Weekly_Plan.md)
├── notebooks/
│   ├── 01_ollama_demo.ipynb
│   └── 02_vector_store_demo.ipynb
├── src/
│   ├── agents/
│   │   └── ... (LangGraph agent definitions)
│   ├── data/
│   │   └── ... (Data ingestion modules)
│   ├── llm/
│   │   ├── strategist.py
│   │   └── ... (LLM wrappers & prompting utilities)
│   ├── rag/
│   │   └── ... (Retrieval & generation pipelines)
│   ├── risk/
│   │   └── ... (Risk‑check & position‑sizing logic)
│   ├── execution/
│   │   └── ... (Trade execution (paper/live) adapters)
│   ├── strategist/
│   │   ├── __init__.py
│   │   ├── rgr_calculator.py
│   │   └── rgr_calculator.py.backup
│   ├── __init__.py
│   ├── indicators.py
│   ├── position_sizer.py
│   ├── stability_filter.py
│   ├── trade_engine.py
│   └── utils.py
├── tests/
│   ├── test_rgr_calculator.py
│   ├── test_risk_manager.py
│   ├── test_stability_filter.py
│   └── test_trade_engine.py
├── docker/
│   # Docker‑compose, Dockerfiles (to be added)
├── requirements.txt
├── setup_week1.sh
├── RAATS_Weekly_Plan.md
├── README.md
├── verify.txt
├── WEEK1_SETUP.md
├── journal/
│   # (optional: journal entries)
└── weeks/
    ├── week1.md
    ├── week2.md
    ├── week3.md
    ├── week4.md
    └── week5.md
```

---

## Getting Started
1. **Clone the repo** (if you haven’t already)  
2. Run the setup script: `./setup_week1.sh` (or follow the manual steps inside the script)  
3. Activate the virtual environment: `source venv/Scripts/activate`  
4. Test Ollama: `ollama run llama3 "What is the sentiment of the word 'bullish'?"`  
5. Explore the notebooks in `notebooks/` to begin experimentation.

---

## License
This project is for academic purposes only. No financial advice is provided.

---
*Last updated: 30 July 2026*
