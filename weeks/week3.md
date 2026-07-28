# Week 3: Retrieval-Augmented Generation (RAG) Basics
**Goal:** Understand and implement a basic RAG pipeline using financial news data, vector stores (FAISS/Chroma), and LLMs for question answering.

## Monday 17 Aug – RAG theory and setup
- Read LangChain RAG tutorial: https://python.langchain.com/docs/modules/data_connection/
- Review FAISS and Chroma documentation links from week 2.
- Install any missing packages (if not already in requirements): `pip install faiss-cpu chromadb`
- Verify installation: `python -c "import faiss, chromadb; print('OK')"`
- Create a small test script to load a sample text, embed with OllamaEmbeddings, and store in FAISS.
- Output: A working RAG prototype notebook (03_rag_basics.ipynb) that answers a simple question about a hardcoded paragraph.

## Tuesday 18 Aug – Ingest financial news into vector store
- Use the news data collected in week 1 (data/raw/news/) or fetch a fresh sample.
- Write a script to read all news CSV files, combine headlines and summaries, and clean text.
- Generate embeddings using OllamaEmbeddings (model: llama3) for each document.
- Store the embedded documents in both FAISS and Chroma vector stores.
- Persist the stores to disk (e.g., data/vector_stores/faiss_news and data/vector_stores/chroma_news).
- Output: Two vector stores ready for querying.

## Wednesday 19 Aug – Build a RAG chain for sentiment queries
- Create a LangChain RetrievalQA chain that uses the FAISS vector store as retriever and Ollama as LLM.
- Define a prompt template for financial sentiment analysis (e.g., "Based on the following news headlines, what is the overall sentiment for [stock]?").
- Test the chain with a few sample questions (e.g., "What is the sentiment for Apple based on recent news?").
- Output: Notebook 04_rag_sentiment.ipynb demonstrating the RAG pipeline.

## Thursday 20 Aug – Evaluate and refine the RAG system
- Run a set of 5-10 predefined questions about different stocks (AAPL, MSFT, TSLA, etc.).
- Record the answers and note any hallucinations or irrelevant responses.
- Experiment with different retrieval parameters (k=2 vs k=4) and different LLMs (if you have multiple models in Ollama).
- Optionally, try using a different embedding model (if available) to see if quality improves.
- Output: A brief evaluation note in docs/rag_evaluation.md.

## Friday 21 Aug – Morning: RAG integration with data pipeline
- Connect the news fetching script from week 1 to automatically update the vector store daily.
- Create a simple scheduler (or just a script) that runs the fetch, embed, and store process.
- Afternoon: Rest (no work) – enjoy the break.

## Saturday 22 Aug – Rest day
- No planned work.

## Sunday 23 Aug – Preparation for Week 4
- Read about spaCy NER and financial entity extraction (links from week 2 plan).
- Think about how to extract tickers and company names from news to improve RAG filtering.
- Optionally, test spaCy on a few headlines to see what entities it recognizes.
- Write a quick note in journal/week3_prep_week4.md about ideas for week 4.
- Commit any notes or small scripts.

---
**End of Week 3 Deliverables:**
- Notebooks: 03_rag_basics.ipynb, 04_rag_sentiment.ipynb
- Scripts: src/data/update_vector_store.py (or similar)
- Vector stores: data/vector_stores/faiss_news, data/vector_stores/chroma_news
- Evaluation: docs/rag_evaluation.md
- Logs: journal/week3_log.md, journal/week3_prep_week4.md