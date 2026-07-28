# Week 2: LLM Foundations & Prompt Engineering
**Goal:** Experiment with Ollama LLMs, practice prompt engineering for financial sentiment, and log results.

---

## Monday 10 Aug – LLM basics & model exploration
1. Activate your venv if not already: `source venv/Scripts/activate`
2. List available Ollama models: `ollama list`
3. Pull a second model (e.g., mistral) for comparison:
   ```bash
   ollama pull mistral
   ```
4. Create a notebook `notebooks/02_llm_exploration.ipynb` and test basic generation with both models:
   ```python
   from langchain_community.llms import Ollama
   llama = Ollama(model="llama3")
   mistral = Ollama(model="mistral")
   prompt = "Explain what a moving average is in one sentence."
   print("Llama3:", llama(prompt))
   print("Mistral:", mistral(prompt))
   ```
5. Commit: `git add notebooks/02_llm_exploration.ipynb && git commit -m "Add LLM model exploration notebook" && git push origin dev`

## Tuesday 11 Aug – Prompt engineering fundamentals
1. Read the Hugging Face Course chapters 3‑4 (LLM internals, prompting) and skim the Prompt Engineering Guide (https://www.promptingguide.ai/).
2. Create a markdown file `docs/prompt_engineering_notes.md` summarizing key techniques: zero‑shot, few‑shot, chain‑of‑thought, role prompting.
3. In a new notebook `notebooks/03_prompt_engineering.ipynb`, test a few prompt variations for sentiment classification:
   ```python
   from langchain_community.llms import Ollama
   llm = Ollama(model="llama3")
   def classify_sentiment(text, prompt_template):
       prompt = prompt_template.format(text=text)
       return llm(prompt)
   news = ["Apple shares surged after beating earnings estimates.",
           "Oil prices dropped sharply due to oversupply concerns."]
   templates = {
       "Zero‑shot": "Is the following news positive, negative, or neutral? {text}",
       "Few‑shot": """Examples:
       Positive: “Apple shares surged after beating earnings estimates.”
       Negative: “Oil prices dropped sharply due to oversupply concerns.”
       Now classify: {text}
       Answer with Positive, Negative, or Neutral."""
   }
   for name, tmpl in templates.items():
       print(f"=== {name} ===")
       for n in news:
           print(f"{n} -> {classify_sentiment(n, tmpl).strip()}")
   ```
4. Commit the notebook and notes.

## Wednesday 12 Aug – Financial sentiment practice
1. Gather a small set of financial headlines (you can reuse the RSS feed from Week 1 or fetch fresh ones).
2. In `notebooks/04_financial_sentiment.ipynb`, apply the best‑performing prompt from Tuesday to a list of 10‑15 headlines.
3. Record the model’s output and manually verify a few for accuracy (optional: compute simple accuracy if you have labels).
4. Export the results to a CSV: `data/processed/week2_sentiment_predictions.csv`.
5. Write a brief report `reports/week2_prompt_report.md` summarizing which prompt style worked best and any observations.
6. Commit notebook, CSV, and report.

## Thursday 13 Aug – Advanced prompting & chaining
1. Experiment with chain‑of‑thought prompting: ask the model to explain its reasoning before giving the sentiment label.
2. Example prompt:
   ```
   Think step by step: first identify any positive or negative words, then decide overall sentiment.
   News: "{text}"
   ```
3. Test this on the same headline set and compare to zero‑shot.
4. Update the CSV with a new column for chain‑of‑thought results.
5. Commit updates.

## Friday 14 Aug (morning) – Wrap‑up & documentation
1. Spend the morning finalizing the week’s work:
   - Ensure all notebooks are saved and executed.
   - Update the README if needed with a “Week 2” section.
   - Write a short summary in `journal/week2_log.md`:
     ```
     # Week 2 Log – 2026‑08‑10 to 2026‑08‑14
     - Explored Llama3 and Mistral models.
     - Tested zero‑shot, few‑shot, and chain‑of‑thought prompts for financial sentiment.
     - Best results: [brief note].
     - Produced sentiment predictions for 15 headlines.
     - Next week: start RAG with FAISS/Chroma.
     ```
2. Commit the log and any final changes.
3. **Afternoon:** Rest (no work) – enjoy the break.

## Saturday 15 Aug – Rest day
- No planned work.

## Sunday 16 Aug – Preparation for Week 3
1. In the evening, skim the LangChain RAG tutorial (https://python.langchain.com/docs/modules/data_connection/).
2. Install the required packages if not already in `requirements.txt`:
   ```
   pip install faiss-cpu chromadb
   ```
3. Verify installation: `python -c "import faiss, chromadb; print('OK')"`.
4. Optionally, download a small financial news CSV to use Monday.
5. Commit any updates to `requirements.txt`.
6. Write a quick note in `journal/week2_prep_week3.md` about what you’ll do Monday.

---
**End of Week 2 Deliverables:**
- Notebooks: `02_llm_exploration.ipynb`, `03_prompt_engineering.ipynb`, `04_financial_sentiment.ipynb`
- Data: `data/processed/week2_sentiment_predictions.csv`
- Reports: `reports/week2_prompt_report.md`
- Logs: `journal/week2_log.md`, `journal/week2_prep_week3.md`
- Updated `requirements.txt` (if needed)