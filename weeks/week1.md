# Week 1: Project Kick‑off & Environment Setup
**Goal:** Install system tools (Docker, Ollama), create a Python virtual environment, install dependencies, and run the first two demo notebooks (Ollama‑LangChain and Vector‑store basics).

---

## Monday 3 Aug – Project kickoff & repo setup
1. Create a private GitHub repo named **RAATS** (or use the existing RAATS_Test).
2. Clone it locally:
   ```bash
   git clone https://github.com/<your‑username>/RAATS.git
   cd RAATS
   ```
3. Add a basic `README.md` and `.gitignore` (Python) if not already present.
4. Open the folder in VS Code and install the recommended extensions: Python, Docker, GitLens.
5. **Output:** Repo initialized, README in place, VS Code ready.

---

## Tuesday 4 Aug – Install core tools
1. Install **Docker Desktop** (https://www.docker.com/products/docker-desktop) if not already installed.
2. Verify Docker:
   ```bash
   docker version   # should show Client and Server version
   ```
3. Download & install **Ollama** from https://ollama.com/download (Windows installer).
4. Test Ollama:
   ```bash
   ollama --version
   ollama run llama3 "Say hello in one word."
   ```
5. **Output:** Docker daemon running, Ollama installed and able to run the llama3 model.

---

## Wednesday 5 Aug – Python environment & dependencies
1. Open Git‑Bash in the repo root.
2. Create a virtual environment:
   ```bash
   python -m venv venv
   ```
3. Activate it:
   ```bash
   source venv/Scripts/activate   # you should see (venv) prefixed
   ```
4. Upgrade pip:
   ```bash
   pip install --upgrade pip
   ```
5. Install the packages listed in `requirements.txt`:
   ```bash
   pip install -r requirements.txt
   ```
6. Install the spaCy English model:
   ```bash
   python -m spacy download en_core_web_sm
   ```
7. **Output:** Virtual environment active, all Week‑1 packages installed, spaCy model ready.

---

## Thursday 6 Aug – Ollama + LangChain basics
1. Launch Jupyter Lab from the activated venv:
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
6. **Output:** Working Ollama‑LangChain demo notebook committed.

---

## Friday 7 Aug – Vector‑store basics (FAISS & Chroma)
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
4. **Output:** Vector‑store demo (FAISS & Chroma) working and committed.

---

## Saturday 8 Aug – Rest day
- No planned project work. Use this day to recharge or do light reading if you wish.

---

## Sunday 9 Aug – Data‑ingestion prototype & weekly reflection
### Part A: Price‑data fetcher (`src/data/fetch_prices.py`)
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

### Part B: News‑fetcher (`src/data/fetch_news.py`)
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

### Part C: Run the scripts (Sunday evening)
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

### Part D: Weekly reflection (Sunday night)
Create a markdown file `journal/week1_reflection.md` (create the `journal` folder first):

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

### End of Week 1
You have now:
- A working development environment (Docker, Ollama, Python venv).
- Two demo notebooks showing Ollama‑LangChain integration and vector‑store basics.
- Preliminary data‑ingestion scripts for price and news data.
- A reflective journal entry documenting progress and blockers.

Proceed to Week 2 when ready.