# Week‑2 Setup Instructions – RAATS Project
**Goal:** Experiment with Ollama models, practice prompt engineering for financial sentiment classification, and log results.

---

## Prerequisites (System Tools)
Ensure you have completed Week‑1 setup:
- Docker Desktop installed and running
- Ollama installed with the `llama3` model (or another model of choice)
- Python virtual environment (`venv`) activated and requirements installed
- Basic Ollama‑LangChain demo and vector‑store demo notebooks committed

If any of the above is missing, revisit [WEEK1_SETUP.md](./WEEK1_SETUP.md) and complete those steps.

---

## Daily Activities

### Monday (Full Day)
1. **Activate the virtual environment** (if not already):
   ```bash
   source venv/Scripts/activate
   ```
2. **Explore Ollama models** available locally:
   ```bash
   ollama list
   ```
3. **Pull an additional model** for comparison (e.g., `mistral` or `phi3`):
   ```bash
   ollama pull mistral
   ```
4. **Create a new notebook** for prompt experiments:
   ```bash
   jupyter lab
   ```
   In the browser, create `notebooks/03_prompt_engineering.ipynb`.
5. **Experiment with basic prompts** using both `llama3` and `mistral`:
   - Test simple factual questions.
   - Test financial‑related prompts (e.g., “What does P/E ratio indicate?”).
   - Record responses and latency (you can use `time` command or Python's `time` module).
6. **Commit the notebook**:
   ```bash
   git add notebooks/03_prompt_engineering.ipynb
   git commit -m "Add initial prompt engineering experiments with Llama3 and Mistral"
   git push origin dev
   ```

### Tuesday (Full Day)
1. **Continue in Jupyter** (keep the venv active).
2. **Learn prompt techniques** (zero‑shot, few‑shot, chain‑of‑thought) from the Hugging Face course chapters 3‑4.
3. **Implement few‑shot examples** for sentiment classification:
   - Create a small dataset of financial headlines with labels (positive/negative/neutral).
   - Format prompts with 2‑3 examples before the query.
4. **Test with both models** and compare accuracy on your tiny dataset.
5. **Save results** in the notebook (add markdown cells with observations).
6. **Commit updates**:
   ```bash
   git add notebooks/03_prompt_engineering.ipynb
   git commit -m "Add few‑shot sentiment classification experiments"
   git push origin dev
   ```

### Wednesday (Full Day)
1. **Focus on chain‑of‑thought (CoT) prompting** for more complex financial reasoning (e.g., “Given this news, what might be the short‑term impact on stock price?”).
2. **Write a function** in the notebook that:
   - Takes a headline.
   - Constructs a CoT prompt.
   - Calls the Ollama model (via LangChain or subprocess).
   - Extracts the reasoning and final answer.
3. **Run on a set of 5‑10 headlines** and log the outputs.
4. **Discuss limitations** (hallucinations, inconsistency) in a markdown cell.
5. **Commit**:
   ```bash
   git add notebooks/03_prompt_engineering.ipynb
   git commit -m "Add chain‑of‑thought prompting experiments"
   git push origin dev
   ```

### Thursday (Full Day)
1. **Systematize your experiments**: create a Python script `src/llm/prompt_tester.py` that:
   - Loads a CSV of headlines (you can reuse the fake dataset from week 1 or fetch a few real ones via yfinance/news).
   - Iterates over a list of prompt templates (zero‑shot, few‑shot, CoT).
   - Calls each model and stores results in a structured format (e.g., JSONL).
2. **Run the script** to generate a baseline comparison report.
3. **Create a summary markdown file** `journal/week2_prompt_summary.md` with:
   - Table of models vs. prompt styles.
   - Observed strengths/weaknesses.
   - Ideas for improvement.
4. **Commit script and summary**:
   ```bash
   git add src/llm/prompt_tester.py journal/week2_prompt_summary.md
   git commit -m "Add prompt tester script and week‑2 summary"
   git push origin dev
   ```

### Friday (Work until afternoon)
1. **Review the week’s work** and ensure everything is committed.
2. **Optional**: Re‑run any experiments to verify reproducibility.
3. **Clean up** any temporary files.
4. **Push final changes**:
   ```bash
   git push origin dev
   ```
5. **Break starts late Friday evening** – no further project work until Sunday.

### Saturday
**Full day of rest** – no planned project work.

### Sunday (Evening)
1. **Prepare for the week ahead**:
   - Review the weekly plan for Week 3 (RAG Basics).
   - Sketch out how you will ingest financial news CSVs and build a retrieval pipeline.
2. **Write a brief reflection** in `journal/week2_reflection.md`:
   ```markdown
   # Week‑2 Reflection – Luyolo Nyaluza

   **What went well**
   - Successfully pulled and tested multiple Ollama models.
   - Implemented zero‑shot, few‑shot, and chain‑of‑thought prompting.
   - Created a reusable prompt‑testing script.

   **Challenges / Blockers**
   - Inconsistent responses across runs (temperature effects).
   - Limited GPU memory caused slower inference with larger models.

   **Goals for Week‑3**
   - Set up a document loader for financial news CSVs.
   - Experiment with FAISS and Chroma for retrieval augmentation.
   - Begin integrating retrieved context into LLM prompts.

   **Time spent**: ~16 hours (including learning, coding, and reflection).
   ```
3. **Commit the reflection**:
   ```bash
   git add journal/week2_reflection.md
   git commit -m "Add week‑2 reflection journal"
   git push origin dev
   ```

---

## Directory Layout for Week‑2 Work
(No new folders required; continue using existing structure.)

```
RAATS_Test/
│
├─ .gitignore
├─ README.md
├─ requirements.txt
├─ setup_week1.sh
├─ RAATS_Weekly_Plan.md
├─ WEEK1_SETUP.md
├─ WEEK2_SETUP.md   ← this file
│
├─ notebooks/
│   ├─ 01_ollama_demo.ipynb
│   ├─ 02_vector_store_demo.ipynb
│   └─ 03_prompt_engineering.ipynb
│
├─ src/
│   ├─ data/
│   │   ├─ fetch_prices.py
│   │   └─ fetch_news.py
│   ├─ agents/
│   ├─ llm/
│   │   └─ prompt_tester.py   ← new
│   ├─ rag/
│   ├─ risk/
│   ├─ execution/
│   └─ tests/
│
├─ journal/
│   ├─ week1_reflection.md
│   └─ week2_reflection.md   ← new
│   └─ week2_prompt_summary.md   ← new
│
��─ venv/
```

---

## Quick Checklist (Copy‑Paste into a TODO app)

```
[ ] Activate venv each session
[ ] List and pull additional Ollama models
[ ] Create notebook 03_prompt_engineering.ipynb
[ ] Test zero‑shot prompts with Llama3 and Mistral
[ ] Implement few‑shot sentiment classification
[ ] Experiment with chain‑of‑thought prompting
[ ] Create src/llm/prompt_tester.py
[ ] Generate baseline comparison report
[ ] Write journal/week2_prompt_summary.md
[ ] Write journal/week2_reflection.md
[ ] Commit and push all work
[ ] Let the Discord reminder (Tuesday 09:00) keep you on track
```

---

**You’re now ready to start Week 2 of the RAATS project.**  
Follow the steps in order, commit your work frequently, and let the weekly reminder keep you on schedule. Good luck! ���