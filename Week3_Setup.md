# Week‑3 Setup Instructions – RAATS Project
**Goal:** Understand and implement a basic RAG pipeline using financial news data, vector stores (FAISS/Chroma), and LLMs for question answering.

---

## Prerequisites (System Tools)
Ensure you have completed Week‑1 and Week‑2 setup:
- Docker Desktop installed and running
- Ollama installed with the `llama3` model (or another model of choice)
- Python virtual environment (`venv`) activated and requirements installed
- Basic Ollama‑LangChain demo and vector‑store demo notebooks committed
- Prompt engineering experiments and scripts from Week 2 committed

If any of the above is missing, revisit [WEEK1_SETUP.md](./WEEK1_SETUP.md) and [WEEK2_SETUP.md](./WEEK2_SETUP.md) and complete those steps.

---

## Daily Activities

### Monday 17 Aug – RAG theory and setup
1. **Activate the virtual environment** (if not already):
   ```bash
   source venv/Scripts/activate
   ```
2. **Read LangChain RAG tutorial**: https://python.langchain.com/docs/modules/data_connection/
3. **Review FAISS and Chroma documentation links** from week 2.
4. **Install any missing packages** (if not already in requirements): `pip install faiss-cpu chromadb`
5. **Verify installation**: `python -c "import faiss, chromadb; print('OK')"`
6. **Create a small test script** to load a sample text, embed with OllamaEmbeddings, and store in FAISS.
   ```python
   # test_rag_setup.py
   from langchain_community.embeddings import OllamaEmbeddings
   from langchain_community.vectorstores import FAISS
   
   # Sample financial news text
   sample_texts = [
       "Apple shares rose 5% after announcing record iPhone sales",
       "Federal Reserve hints at possible interest rate cuts next quarter",
       "Oil prices decline as OPEC increases production output",
       "Tesla delivers record number of vehicles in Q3",
       "Microsoft reports strong cloud growth driving stock gains"
   ]
   
   # Initialize Ollama embeddings
   embeddings = OllamaEmbeddings(model="llama3")
   
   # Create FAISS vector store from texts
   vectorstore = FAISS.from_texts(sample_texts, embeddings)
   
   # Save the vector store locally
   vectorstore.save_local("faiss_test_index")
   
   # Test retrieval
   query = "What happened with Apple stock?"
   docs = vectorstore.similarity_search(query, k=2)
   
   print(f"Query: {query}")
   print("\nTop 2 relevant documents:")
   for i, doc in enumerate(docs, 1):
       print(f"{i}. {doc.page_content}")
   ```
7. **Output**: A working RAG prototype notebook (`notebooks/03_rag_basics.ipynb`) that answers a simple question about a hardcoded paragraph.
   ```python
   # Example cell content for 03_rag_basics.ipynb
   # In[1]: Import libraries
   from langchain_community.embeddings import OllamaEmbeddings
   from langchain_community.vectorstores import FAISS
   from langchain_community.llms import Ollama
   from langchain.chains import RetrievalQA
   
   # In[2]: Load sample data and create vector store
   financial_news = [
       "Apple beats earnings expectations with strong services growth",
       "Google announces breakthrough in quantum computing research",
       "Amazon faces regulatory scrutiny in EU markets",
       "Netflix subscriber growth slows in saturated markets",
       "Meta invests heavily in metaverse development despite losses"
   ]
   
   embed = OllamaEmbeddings(model="llama3")
   vectorstore = FAISS.from_texts(financial_news, embed)
   
   # In[3]: Set up Ollama LLM
   llm = Ollama(model="llama3")
   
   # In[4]: Create RetrievalQA chain
   qa_chain = RetrievalQA.from_chain_type(
       llm=llm,
       chain_type="stuff",
       retriever=vectorstore.as_retriever(search_kwargs={"k": 2})
   )
   
   # In[5]: Test with a question
   question = "Which company announced a breakthrough in quantum computing?"
   answer = qa_chain.run(question)
   print(f"Q: {question}")
   print(f"A: {answer}")
   ```
8. **Commit the notebook**:
   ```bash
   git add notebooks/03_rag_basics.ipynb
   git commit -m "Add RAG basics notebook"
   git push origin dev
   ```

### Tuesday 18 Aug – Ingest financial news into vector store
1. **Use the news data collected in week 1** (`data/raw/news/`) or fetch a fresh sample.
2. **Write a script** to read all news CSV files, combine headlines and summaries, and clean text.
   ```python
   # src/data/process_news.py
   import pandas as pd
   import os
   import re
   from glob import glob
   
   def load_and_clean_news(data_dir="data/raw/news"):
       """Load all CSV news files and clean the text"""
       all_files = glob(os.path.join(data_dir, "*.csv"))
       df_list = []
       
       for file in all_files:
           df = pd.read_csv(file)
           # Combine headline and summary if both exist
           if 'headline' in df.columns and 'summary' in df.columns:
               df['text'] = df['headline'] + ". " + df['summary']
           elif 'headline' in df.columns:
               df['text'] = df['headline']
           elif 'title' in df.columns:  # Alternative column name
               df['text'] = df['title']
           else:
               # Use first text-like column
               text_cols = [col for col in df.columns if df[col].dtype == 'object']
               df['text'] = df[text_cols[0]] if text_cols else ""
           
           # Clean text: remove extra whitespace, special chars
           df['text'] = df['text'].str.strip()
           df['text'] = df['text'].str.replace(r'\s+', ' ', regex=True)
           df_list.append(df[['text']])  # Keep only cleaned text
       
       combined_df = pd.concat(df_list, ignore_index=True)
       combined_df = combined_df.dropna()  # Remove empty entries
       combined_df = combined_df[combined_df['text'].str.len() > 10]  # Remove too short
       
       return combined_df
   
   if __name__ == "__main__":
       news_df = load_and_clean_news()
       print(f"Loaded and cleaned {len(news_df)} news articles")
       print("\nSample articles:")
       print(news_df.head(3))
       
       # Save processed data
       os.makedirs("data/processed", exist_ok=True)
       news_df.to_csv("data/processed/combined_news.csv", index=False)
       print("\nSaved processed news to data/processed/combined_news.csv")
   ```
3. **Generate embeddings** using OllamaEmbeddings (model: llama3) for each document.
   ```python
   # Continuing from process_news.py or in a separate script
   from langchain_community.embeddings import OllamaEmbeddings
   
   # Load processed news
   news_df = pd.read_csv("data/processed/combined_news.csv")
   texts = news_df['text'].tolist()
   
   # Generate embeddings
   print(f"Generating embeddings for {len(texts)} documents...")
   embeddings = OllamaEmbeddings(model="llama3")
   embedded_texts = embeddings.embed_documents(texts)
   
   print(f"Generated {len(embedded_texts)} embeddings of dimension {len(embedded_texts[0])}")
   ```
4. **Store the embedded documents** in both FAISS and Chroma vector stores.
   ```python
   # Store in FAISS
   from langchain_community.vectorstores import FAISS
   
   # Create FAISS vector store
   faiss_vectorstore = FAISS.from_texts(texts, embeddings)
   faiss_vectorstore.save_local("data/vector_stores/faiss_news")
   print(f"FAISS vector store saved with {faiss_vectorstore.index.ntotal} vectors")
   
   # Store in Chroma
   from langchain_community.vectorstores import Chroma
   
   chroma_vectorstore = Chroma.from_texts(
       texts=texts,
       embedding=embeddings,
       persist_directory="data/vector_stores/chroma_news"
   )
   print(f"Chroma vector store saved with {chroma_vectorstore._collection.count()} vectors")
   ```
5. **Persist the stores** to disk (e.g., `data/vector_stores/faiss_news` and `data/vector_stores/chroma_news`).
   *(Shown in code snippets above)*
6. **Output**: Two vector stores ready for querying.
7. **Commit the script and vector stores** (or at least the script; vector stores can be large, consider adding to .gitignore but commit a small sample or README):
   ```bash
   git add src/data/process_news.py src/data/update_vector_store.py
   git commit -m "Add news processing and vector store creation scripts"
   git push origin dev
   ```

### Wednesday 19 Aug – Build a RAG chain for sentiment queries
1. **Create a LangChain RetrievalQA chain** that uses the FAISS vector store as retriever and Ollama as LLM.
   ```python
   # src/rag/financial_sentiment_rag.py
   from langchain_community.vectorstores import FAISS
   from langchain_community.embeddings import OllamaEmbeddings
   from langchain_community.llms import Ollama
   from langchain.chains import RetrievalQA
   from langchain.prompts import PromptTemplate
   
   def create_financial_rag_chain(vectorstore_path="data/vector_stores/faiss_news"):
       # Load vector store
       embeddings = OllamaEmbeddings(model="llama3")
       vectorstore = FAISS.load_local(vectorstore_path, embeddings)
       
       # Set up LLM
       llm = Ollama(model="llama3")
       
       # Create RetrievalQA chain
       qa_chain = RetrievalQA.from_chain_type(
           llm=llm,
           chain_type="stuff",
           retriever=vectorstore.as_retriever(search_kwargs={"k": 4})
       )
       
       return qa_chain
   ```
2. **Define a prompt template** for financial sentiment analysis (e.g., "Based on the following news headlines, what is the overall sentiment for [stock]?").
   ```python
   # Continuing from above or in a separate prompt definition
   financial_prompt_template = """Based on the following financial news headlines and summaries, 
   provide a concise analysis of the overall sentiment for {stock}. 
   Consider both positive and negative indicators, and conclude with 
   whether the sentiment is predominantly POSITIVE, NEGATIVE, or NEUTRAL.
   
   News Context:
   {context}
   
   Question: What is the overall sentiment for {stock}?
   
   Answer:"""
   
   FINANCIAL_PROMPT = PromptTemplate(
       template=financial_prompt_template,
       input_variables=["stock", "context"]
   )
   ```
3. **Test the chain** with a few sample questions (e.g., "What is the sentiment for Apple based on recent news?").
   ```python
   # Example usage in notebook 04_rag_sentiment.ipynb
   # In[1]: Create RAG chain with custom prompt
   from src.rag.financial_sentiment_rag import create_financial_rag_chain, FINANCIAL_PROMPT
   from langchain.chains import RetrievalQA
   
   qa_chain = create_financial_rag_chain()
   
   # Customize chain with financial prompt
   financial_qa_chain = RetrievalQA.from_chain_type(
       llm=qa_chain.combine_documents_chain.llm,
       chain_type="stuff",
       retriever=qa_chain.retriever,
       chain_type_kwargs={"prompt": FINANCIAL_PROMPT}
   )
   
   # In[2]: Test with sample questions
   test_questions = [
       "What is the sentiment for Apple based on recent news?",
       "How is Microsoft performing according to latest financial headlines?",
       "What does the news suggest about Tesla's market position?",
       "Is the sentiment for Google positive or negative in recent articles?",
       "What is the overall outlook for Amazon based on current news?"
   ]
   
   print("Financial Sentiment Analysis Results:")
   print("=" * 50)
   for question in test_questions:
       # Extract stock name from question for prompt formatting
       import re
       stock_match = re.search(r'for\s+(\w+)', question)
       stock = stock_match.group(1) if stock_match else "the market"
       
       # Run the chain
       answer = financial_qa_chain.run({"query": question, "stock": stock})
       
       print(f"\nQ: {question}")
       print(f"A: {answer.strip()}")
   ```
4. **Output**: Notebook `notebooks/04_rag_sentiment.ipynb` demonstrating the RAG pipeline.
5. **Commit the notebook**:
   ```bash
   git add notebooks/04_rag_sentiment.ipynb
   git commit -m "Add RAG sentiment notebook"
   git push origin dev
   ```

### Thursday 20 Aug – Evaluate and refine the RAG system
1. **Run a set of 5-10 predefined questions** about different stocks (AAPL, MSFT, TSLA, etc.).
2. **Record the answers** and note any hallucinations or irrelevant responses.
3. **Experiment with different retrieval parameters** (k=2 vs k=4) and different LLMs (if you have multiple models in Ollama).
   ```python
   # Example evaluation script snippet
   def evaluate_rag_parameters(questions, vectorstore_path="data/vector_stores/faiss_news"):
       from langchain_community.vectorstores import FAISS
       from langchain_community.embeddings import OllamaEmbeddings
       from langchain_community.llms import Ollama
       from langchain.chains import RetrievalQA
       
       embeddings = OllamaEmbeddings(model="llama3")
       vectorstore = FAISS.load_local(vectorstore_path, embeddings)
       llm = Ollama(model="llama3")
       
       results = {}
       
       # Test different k values
       for k in [2, 4, 6]:
           print(f"\nTesting with k={k}...")
           qa_chain = RetrievalQA.from_chain_type(
               llm=llm,
               chain_type="stuff",
               retriever=vectorstore.as_retriever(search_kwargs={"k": k})
           )
           
           k_results = []
           for question in questions:
               answer = qa_chain.run(question)
               k_results.append({
                   "question": question,
                   "answer": answer,
                   "length": len(answer)
               })
           results[f"k_{k}"] = k_results
       
       # Test different LLMs if available
       try:
           llm_mistral = Ollama(model="mistral")
           print("\nTesting with mistral model...")
           mistral_results = []
           for question in questions:
               qa_chain_mistral = RetrievalQA.from_chain_type(
                   llm=llm_mistral,
                   chain_type="stuff",
                   retriever=vectorstore.as_retriever(search_kwargs={"k": 4})
               )
               answer = qa_chain_mistral.run(question)
               mistral_results.append({
                   "question": question,
                   "answer": answer,
                   "length": len(answer)
               })
           results["mistral"] = mistral_results
       except Exception as e:
           print(f"Could not test mistral: {e}")
       
       return results
   ```
4. **Optionally, try using a different embedding model** (if available) to see if quality improves.
5. **Output**: A brief evaluation note in `docs/rag_evaluation.md`.
6. **Commit the evaluation note**:
   ```bash
   git add docs/rag_evaluation.md
   git commit -m "Add RAG evaluation note"
   git push origin dev
   ```

### Friday 21 Aug – Morning: RAG integration with data pipeline
1. **Connect the news fetching script from week 1** (`src/data/fetch_news.py`) to automatically update the vector store daily.
2. **Create a simple scheduler** (or just a script) that runs the fetch, embed, and store process (e.g., `src/data/update_vector_store.py` that calls fetch_news then embeds and stores).
   ```python
   # src/data/update_vector_store.py
   """
   Automated script to update financial news vector stores.
   Fetches latest news, processes it, and updates FAISS/Chroma vector stores.
   """
   import subprocess
   import sys
   import os
   from pathlib import Path
   
   def run_news_fetch():
       """Run the news fetching script"""
       print("Step 1: Fetching latest financial news...")
       try:
           result = subprocess.run(
               [sys.executable, "src/data/fetch_news.py"],
               capture_output=True, text=True, check=True
           )
           print(result.stdout)
           if result.stderr:
               print("Warnings:", result.stderr)
       except subprocess.CalledProcessError as e:
           print(f"Error fetching news: {e}")
           print(e.stdout)
           print(e.stderr)
           return False
       return True
   
   def process_and_store_news():
       """Process news and update vector stores"""
       print("\nStep 2: Processing news and updating vector stores...")
       try:
           # Run the processing script we created earlier
           result = subprocess.run(
               [sys.executable, "src/data/process_news.py"],
               capture_output=True, text=True, check=True
           )
           print(result.stdout)
           if result.stderr:
               print("Warnings:", result.stderr)
       except subprocess.CalledProcessError as e:
           print(f"Error processing news: {e}")
           print(e.stdout)
           print(e.stderr)
           return False
       return True
   
   def main():
       """Main update pipeline"""
       print("Starting vector store update process...")
       print("=" * 50)
       
       success = True
       success = run_news_fetch() and success
       success = process_and_store_news() and success
       
       if success:
           print("\n" + "=" * 50)
           print("Vector store update completed successfully!")
           print("Updated stores available in:")
           print("- data/vector_stores/faiss_news/")
           print("- data/vector_stores/chroma_news/")
       else:
           print("\n" + "=" * 50)
           print("Vector store update failed. Check logs above.")
           sys.exit(1)
   
   if __name__ == "__main__":
       main()
   ```
3. **Afternoon: Rest** (no work) – enjoy the break.
4. **Commit any updates**:
   ```bash
   git add src/data/update_vector_store.py
   git commit -m "Update vector store integration script"
   git push origin dev
   ```

### Saturday 22 Aug – Rest day
- No planned work.

### Sunday 23 Aug – Preparation for Week 4
1. **Read about spaCy NER and financial entity extraction** (links from week 2 plan).
2. **Think about how to extract tickers and company names** from news to improve RAG filtering.
3. **Optionally, test spaCy on a few headlines** to see what entities it recognizes.
   ```python
   # Example spaCy NER test for financial entities
   import spacy
   
   # Load English model
   nlp = spacy.load("en_core_web_sm")
   
   # Sample financial headlines
   headlines = [
       "Apple Inc. (AAPL) shares rise after strong iPhone sales",
       "Microsoft Corporation (MSFT) announces Azure growth acceleration",
       "Tesla, Inc. (TSLA) delivers record vehicles in Q3",
       "Amazon.com, Inc. (AMZN) faces antitrust investigation in EU",
       "Alphabet Inc. (GOOGL) reports strong ad revenue growth"
   ]
   
   print("Financial Entity Recognition with spaCy:")
   print("=" * 60)
   for headline in headlines:
       doc = nlp(headline)
       entities = [(ent.text, ent.label_) for ent in doc.ents]
       
       print(f"\nHeadline: {headline}")
       print("Entities found:")
       if entities:
           for text, label in entities:
               print(f"  - {text} ({label})")
       else:
           print("  No named entities detected")
   ```
4. **Write a quick note** in `journal/week3_prep_week4.md` about ideas for week 4.
5. **Commit any notes or small scripts**:
   ```bash
   git add journal/week3_prep_week4.md
   git commit -m "Add week 4 preparation note"
   git push origin dev
   ```

---

## End of Week 3 Deliverables
- Notebooks: `notebooks/03_rag_basics.ipynb`, `notebooks/04_rag_sentiment.ipynb`
- Scripts: `src/data/update_vector_store.py` (or similar)
- Vector stores: `data/vector_stores/faiss_news`, `data/vector_stores/chroma_news`
- Evaluation: `docs/rag_evaluation.md`
- Logs: `journal/week3_log.md`, `journal/week3_prep_week4.md`

---

## Directory Layout for Week‑3 Work
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
├─ WEEK2_SETUP.md
├─ Week3_Setup.md   ← this file
│
├─ notebooks/
│   ├─ 01_ollama_demo.ipynb
│   ├─ 02_vector_store_demo.ipynb
│   ├─ 03_rag_basics.ipynb      ← new
│   └─ 04_rag_sentiment.ipynb   ← new
│
├─ src/
│   ├─ data/
│   │   ├─ fetch_prices.py
│   │   ├─ fetch_news.py
│   │   ├─ process_news.py      ← new
│   │   └─ update_vector_store.py   ← new/updated
│   ├─ agents/
│   ├─ llm/
│   │   └─ prompt_tester.py
│   ├─ rag/
│   │   └─ financial_sentiment_rag.py ← new
│   ├─ risk/
│   ├─ execution/
│   └─ tests/
│
├─ journal/
│   ├─ week1_reflection.md
│   ├─ week2_reflection.md
│   ├─ week2_prompt_summary.md
│   ├─ week3_log.md               ← new
│   └─ week3_prep_week4.md        ← new
│
├─ docs/
│   └─ rag_evaluation.md          ← new
│
├─ data/
│   ├─ raw/
│   │   ├─ prices/
│   │   └─ news/
│   ├─ processed/
│   │   └─ combined_news.csv    ← new/updated
│   └─ vector_stores/
│       ├─ faiss_news/
│       └─ chroma_news/
│
└─ venv/
```

---

## Quick Checklist (Copy‑Paste into a TODO app)
```
[ ] Activate venv each session
[ ] Install missing packages: pip install faiss-cpu chromadb
[ ] Verify installation: python -c "import faiss, chromadb; print('OK')"
[ ] Create and run test_rag_setup.py (Monday)
[ ] Create notebook 03_rag_basics.ipynb and push
[ ] Create and run src/data/process_news.py (Tuesday)
[ ] Create and run src/data/update_vector_store.py (Tuesday/Friday)
[ ] Create notebook 04_rag_sentiment.ipynb and push
[ ] Create src/rag/financial_sentiment_rag.py (Wednesday)
[ ] Run evaluation experiments and write docs/rag_evaluation.md (Thursday)
[ ] Test spaCy NER for financial entities (Sunday)
[ ] Write journal/week3_log.md and journal/week3_prep_week4.md
[ ] Commit and push all work
[ ] Let the Discord reminder (Tuesday 09:00) keep you on track
```

---

**You’re now ready to start Week 3 of the RAATS project.**  
Follow the steps in order, commit your work frequently, and let the weekly reminder keep you on schedule. Good luck! 🚀