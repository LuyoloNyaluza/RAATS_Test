# Week‑1 Setup Instructions – RAATS Project
**Goal:** Get a working development environment (Docker, Ollama, Python venv) and run the first two demo notebooks.

---

## Prerequisites (System Tools)

1. **Install Docker Desktop**
   - Download from https://www.docker.com/products/docker-desktop
   - Run the installer, start Docker, and verify:
     ```bash
     docker version   # should show Client and Server version info
     ```

2. **Install Ollama (local LLM server)**
   - Download the Windows installer from https://ollama.com/download
   - Install with default options.
   - After installation, open a new Git‑Bash/MSYS2 window and test:
     ```bash
     ollama --version               # shows version, e.g. ollama version 0.1.34
     ollama run llama3 "Say hello in one word."   # downloads model and replies
     ```
   - If the command fails, ensure Ollama is on your `PATH` or run it from its install folder.

---

## Repository Setup

```bash
# 1️⃣ Clone your repo (adjust URL if needed)
git clone https://github.com/LuyoloNyaluza/RAATS_Test.git
cd RAATS_Test

# 2️⃣ Create a development branch (optional but recommended)
git checkout -b dev

# 3️⃣ Verify the initial layout
ls -la
# Expected: README.md, requirements.txt, setup_week1.sh, .gitignore, RAATS_Weekly_Plan.md
```

---

## Python Virtual Environment & Dependencies

```bash
# 1️⃣ Create a venv named "venv" inside the project root
python -m venv venv

# 2️⃣ Activate it
source venv/Scripts/activate   # your prompt should now show (venv)

# 3️⃣ Upgrade pip
pip install --upgrade pip

# 4️⃣ Install the Python packages listed in requirements.txt
pip install -r requirements.txt

# 5️⃣ Install the spaCy English model (used for NLP tasks)
python -m spacy download en_core_web_sm
```

> **All subsequent Python work should be done while the venv is activated.**  
> To deactivate later, run `deactivate`.

---

## Verify Core Components

```bash
# Docker sanity check
docker run --rm hello-world   # should print a hello message and exit cleanly

# Ollama sanity check
ollama list                   # should list the llama3 model you pulled
ollama run llama3 "What is the capital of France?"   # short answer expected

# Python package sanity check
python -c "import langchain, chromadb, yfinance, pandas_ta, spacy, textblob; print('All imports OK')"
```

If any command fails, repeat the corresponding installation step.

---

## Directory Layout for Week‑1 Work

```bash
mkdir -p notebooks src/data src/agents src/llm src/rag src/risk src/execution tests
```

Your repo should now contain:

```
RAATS_Test/
│
├─ .gitignore
├─ README.md
├─ requirements.txt
├─ setup_week1.sh
├─ RAATS_Weekly_Plan.md
│
├─ notebooks/               # Jupyter notebooks for exploration
├─ src/
│   ├─ data/                # data‑fetching scripts (prices, news)
│   ├─ agents/              # LangGraph agent definitions
│   ├─ llm/                 # LLM wrapper / prompting utilities
│   ├─ rag/                 # Retrieval‑augmented generation pipelines
│   ├─ risk/                # risk‑check & position‑sizing logic
│   ├─ execution/           # mock/paper‑trade executor
│   └─ tests/               # unit / integration tests
└─ venv/                    # Python virtual environment (git‑ignored)
```

---

## Notebook 1 – Ollama + LangChain Demo (Thursday)

1. Start Jupyter Lab from the activated venv:
   ```bash
   jupyter lab
   ```
2. In the browser, create a new notebook: `notebooks/01_ollama_demo.ipynb`.
3. Paste and run the following cells:

   ```python
   # 01_ollama_demo.ipynb
   import subprocess
   from langchain_community.llms import Ollama

   # Helper to call Ollama via CLI (optional, shows it works)
   def ollama_prompt(prompt):
       result = subprocess.run(
           ["ollama", "run", "llama3", prompt],
           capture_output=True, text=True, check=True
       )
       return result.stdout.strip()

   # Using LangChain wrapper
   llm = Ollama(model="llama3")
   print("LangChain Ollama response:")
   print(llm("What is the sentiment of the word 'bullish'?"))

   # Direct CLI call
   print("\nDirect CLI Ollama response:")
   print(ollama_prompt("Explain a moving average in one sentence."))
   ```

4. Save the notebook.
5. Commit and push:
   ```bash
   git add notebooks/01_ollama_demo.ipynb
   git commit -m "Add Ollama‑LangChain demo notebook"
   git push origin dev
   ```

---

## Notebook 2 – Vector‑Store Basics (FAISS & Chroma) (Friday)

1. Still in Jupyter Lab, create `notebooks/02_vector_store_demo.ipynb`.
2. Paste and run the following cells:

   ```python
   # 02_vector_store_demo.ipynb
   import pandas as pd
   from langchain_community.embeddings import OllamaEmbeddings
   from langchain_community.vectorstores import FAISS, Chroma

   # Tiny fake financial‑news dataset
   data = {
       "headline": [
           "Apple shares rise after new iPhone launch",
           "Oil prices fall as OPEC raises output",
           "Tesla reports record quarterly deliveries",
           "Federal Reserve hints at rate cuts",
           "Google announces new AI breakthrough"
       ],
       "date": ["2024-09-01","2024-09-02","2024-09-03","2024-09-04","2024-09-05"]
   }
   df = pd.DataFrame(data)

   # Embeddings via Ollama (same model as before)
   embed = OllamaEmbeddings(model="llama3")

   # ---- FAISS ----
   faiss_vs = FAISS.from_texts(df["headline"].tolist(), embed, metadatas=df.to_dict("records"))
   print(f"FAISS index built with {faiss_vs.index.ntotal} vectors")
   # Example query
   docs = faiss_vs.similarity_search("What happened with Apple?", k=2)
   for d in docs:
       print("-", d.page_content)

   # ---- Chroma ----
   chroma_vs = Chroma.from_texts(
       texts=df["headline"].tolist(),
       embedding=embed,
       metadatas=df.to_dict("records"),
       persist_directory="./chroma_demo"
   )
   print(f"Chroma collection count: {chroma_vs._collection.count()}")
   results = chroma_vs.similarity_search("oil price", k=2)
   for r in results:
       print("-", r.page_content)
   ```

3. Save, commit, and push:
   ```bash
   git add notebooks/02_vector_store_demo.ipynb
   git commit -m "Add FAISS & Chroma vector‑store demo"
   git push origin dev
   ```

---

## Weekend – Data‑Ingestion Prototypes (Saturday rest, Sunday evening)

### 8.1 Price‑data fetcher (`src/data/fetch_prices.py`)

```python
# src/data/fetch_prices.py
import yfinance as yf
import pandas as pd
import os

def fetch_price_data(tickers, start_date, end_date, out_dir="data/raw/prices"):
    os.makedirs(out_dir, exist_ok=True)
    for ticker in tickers:
        print(f"Downloading {ticker}...")
        df = yf.download(ticker, start=start_date, end=end_date)
        csv_path = os.path.join(out_dir, f"{ticker}.csv")
        df.to_csv(csv_path)
        print(f"Saved {ticker}.csv ({df.shape[0]} rows)")

if __name__ == "__main__":
    watchlist = ["AAPL", "MSFT", "TSLA"]
    fetch_price_data(watchlist, "2024-08-01", "2024-08-31")
```

### 8.2 News‑fetcher (`src/data/fetch_news.py`)

```python
# src/data/fetch_news.py
import feedparser
import pandas as pd
import os
from datetime import datetime

def fetch_rss_feed(url, out_dir="data/raw/news"):
    os.makedirs(out_dir, exist_ok=True)
    print(f"Fetching feed from {url}")
    feed = feedparser.parse(url)
    entries = []
    for entry in feed.entries[:20]:  # limit to latest 20
        entries.append({
            "title": entry.title,
            "link": entry.link,
            "published": getattr(entry, "published", ""),
            "summary": getattr(entry, "summary", "")
        })
    df = pd.DataFrame(entries)
    out_file = os.path.join(out_dir, f"news_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    df.to_csv(out_file, index=False)
    print(f"Saved {len(entries)} articles to {out_file}")

if __name__ == "__main__":
    # Example: Yahoo Finance RSS for a few tickers
    rss_url = "https://finance.yahoo.com/rss/headline?s=AAPL,MSFT,TSLA"
    fetch_rss_feed(rss_url)
```

### 8.3 Run the scripts (Sunday evening)

```bash
# Ensure the venv is active
source venv/Scripts/activate

# Fetch price data
python src/data/fetch_prices.py

# Fetch news
python src/data/fetch_news.py

# Verify the files were created
ls -la data/raw/prices/
ls -la data/raw/news/
```

### 8.4 Weekly Reflection (Sunday night)

Create a short markdown file `journal/week1_reflection.md` (create the `journal` folder first):

```markdown
# Week‑1 Reflection – Luyolo Nyaluza

**What went well**
- Docker and Ollama installed without issues.
- Virtual environment created and all packages installed successfully.
- First two notebooks (Ollama‑LangChain demo and Vector‑store demo) run and committed.

**Challenges / Blockers**
- Initial PATH issue with Ollama; solved by restarting Git‑Bash after installation.
- Slight delay downloading the llama3 model on first run (expected).

**Goals for Week‑2**
- Finish the data‑ingestion scripts and store a week’s worth of price & news data.
- Begin experimenting with prompt engineering for financial sentiment classification.
- Continue reading the Hugging Face LLM course chapters 3‑4.

**Time spent**: ~18 hours (including setup, learning, and coding).
```

Commit the reflection:

```bash
mkdir -p journal
# (create the file as shown above, then:)
git add journal/week1_reflection.md
git commit -m "Add week‑1 reflection journal"
git push origin dev
```

---

## Quick Checklist (Copy‑Paste into a TODO app)

```
[ ] Install Docker Desktop
[ ] Install Ollama (verify with `ollama run llama3 "test"`)
[ ] Clone repo & create dev branch
[ ] Create & activate Python venv
[ ] Upgrade pip & install -r requirements.txt
[ ] Install spaCy model (`python -m spacy download en_core_web_sm`)
[ ] Verify docker, ollama, python imports work
[ ] Create notebooks/01_ollama_demo.ipynb & push
[ ] Create notebooks/02_vector_store_demo.ipynb & push
[ ] Write src/data/fetch_prices.py & src/data/fetch_news.py
[ ] Run the data‑fetch scripts (Sunday evening)
[ ] Write week‑1 reflection journal & push
[ ] Let the Discord reminder (Tuesday 09:00) keep you on track
```

---

**You’re now ready to start Week 1 of the RAATS project.**  
Follow the steps in order, commit your work frequently, and let the weekly reminder keep you on schedule. Good luck! 🚀