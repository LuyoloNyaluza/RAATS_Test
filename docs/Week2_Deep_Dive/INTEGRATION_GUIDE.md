# Integration Guide — RAATS Week 2 Package

This guide walks you through copying every file in this package into your local
`RAATS_Test` repository (e.g. `/c/Users/Zamuxolo/RAATS_Test`).

## 1. Target Folder Structure

```
RAATS_Test/
├── docs/
│   └── Week2_Deep_Dive/
│       ├── Claude_Suggestions_Week2.md
│       ├── INTEGRATION_GUIDE.md
│       └── INTEGRATION_SUMMARY.txt
├── src/
│   ├── llm/
│   │   └── strategist.py              ← src_llm_strategist_REVISED.py
│   └── execution/
│       └── paper_trader.py            ← src_execution_paper_trader_REVISED.py
└── notebooks/
    ├── prompts_tester.py              ← notebooks_prompts_tester.py
    ├── model_comparison.py            ← notebooks_model_comparison.py
    └── vector_store_chroma.py         ← notebooks_vector_store_chroma.py
```

## 2. Step-by-Step (Windows / Git Bash)

```bash
cd /c/Users/Zamuxolo/RAATS_Test

# 1. Create the docs folder
mkdir -p docs/Week2_Deep_Dive

# 2. Copy documentation
cp /path/to/extracted/README.md docs/Week2_Deep_Dive/
cp /path/to/extracted/Claude_Suggestions_Week2.md docs/Week2_Deep_Dive/
cp /path/to/extracted/INTEGRATION_GUIDE.md docs/Week2_Deep_Dive/
cp /path/to/extracted/INTEGRATION_SUMMARY.txt docs/Week2_Deep_Dive/

# 3. Replace source files (back up originals first!)
cp src/llm/strategist.py src/llm/strategist.py.bak
cp src/execution/paper_trader.py src/execution/paper_trader.py.bak

cp /path/to/extracted/src_llm_strategist_REVISED.py src/llm/strategist.py
cp /path/to/extracted/src_execution_paper_trader_REVISED.py src/execution/paper_trader.py

# 4. Copy testing scripts into notebooks/
cp /path/to/extracted/notebooks_prompts_tester.py notebooks/prompts_tester.py
cp /path/to/extracted/notebooks_model_comparison.py notebooks/model_comparison.py
cp /path/to/extracted/notebooks_vector_store_chroma.py notebooks/vector_store_chroma.py
```

## 3. Step-by-Step (Mac/Linux)

Same as above — `cp` works identically. If you extracted the tar.gz with
`tar -xzf RAATS_Week2_Integration.tar.gz`, the files will already be sitting in
your current directory, so just adjust the source paths.

## 4. Install / Verify Dependencies

```bash
pip install langchain langchain-community chromadb ollama faiss-cpu --break-system-packages
```

Make sure Ollama is running locally and you've pulled at least one model:

```bash
ollama pull mistral
ollama pull llama3
```

## 5. Sanity-Check the Integration

```bash
python notebooks/prompts_tester.py
python notebooks/model_comparison.py
python notebooks/vector_store_chroma.py
```

Each script prints its own pass/fail summary at the end. If `strategist.py` or
`paper_trader.py` fail to import, double check that your `requirements.txt`
includes `langchain-community` (the vector store + Ollama wrappers moved there
in recent LangChain versions).

## 6. Git Workflow (Recommended)

```bash
git checkout -b week2-llm-foundations
git add docs/ src/llm/strategist.py src/execution/paper_trader.py notebooks/
git commit -m "Week 2: prompt engineering, model comparison, Chroma vector store, revised strategist/paper trader"
git push origin week2-llm-foundations
```

Then open a PR against `main` so you have a clean record of what changed for
Week 2, separate from your Week 1 setup commit.

## 7. Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: langchain_community` | Old LangChain install | `pip install -U langchain langchain-community` |
| `ollama.ResponseError: model not found` | Model not pulled | `ollama pull <model_name>` |
| Chroma persistence directory empty | Script run from wrong cwd | Run scripts from repo root, or pass an absolute `persist_directory` |
| `strategist.py` import error on `__init__` | Old stub still referenced elsewhere | Search repo for `LLMStrategist(` calls and confirm signature matches revised class |
