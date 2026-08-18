from langchain_ollama import OllamaEmbeddings
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
embeddings = OllamaEmbeddings(model="nomic-embed-text")
   
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