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

## Suggested Learning Resources
To build and extend RAATS, consider studying the following topics and resources:

### Core Concepts
- **Agentic AI & LangGraph** – https://langchain-ai.github.io/langgraph/
- **Retrieval‑Augmented Generation (RAG)** – https://python.langchain.com/docs/modules/data_connection/retrievers/
- **Large Language Models (LLMs) with Ollama** – https://ollama.com/
- **Vector Stores (FAISS, Chroma)** – https://faiss.ai/, https://www.trychroma.com/
- **Financial Data & Technical Indicators** – https://pypi.org/project/yfinance/, https://github.com/twopirllc/pandas-ta
- **NLP for Finance (spaCy, TextBlob, VADER)** – https://spacy.io/, https://www.nltk.org/, https://github.com/cjhutto/vaderSentiment
- **Risk Management & Position Sizing** – https://www.investopedia.com/terms/r/riskmanagement.asp
- **Docker & Docker Compose** – https://docs.docker.com/get-started/

### Tutorials & Courses
- "Building LLM‑Powered Applications" – Coursera / DeepLearning.AI
- "Algorithmic Trading with Python" – QuantInsti / Udemy
- "LangChain for LLM Applications" – free YouTube series (LangChain channel)
- "Docker for Data Science" – DataCamp

### Books
- *Advances in Financial Machine Learning* – Marcos López de Prado
* *Designing Data‑Intensive Applications* – Martin Kleppmann
* *LangChain in Action* – Manning (forthcoming)

### Community & Forums
- LangChain Discord: https://discord.gg/langchain
- Ollama Community: https://discord.gg/ollama
- QuantConnect Forum: https://www.quantconnect.com/forum
- r/algotrading (Reddit)

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
└── verify.txt
```

## Getting Started
1. Clone the repo.
2. Run `./setup_week1.sh` (or follow the manual steps in the script).
3. Activate the virtual environment: `source venv/bin/activate`.
4. Start exploring the notebooks in `notebooks/`.

## License
This project is for academic purposes only. No financial advice is provided.