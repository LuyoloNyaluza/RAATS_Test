import pandas as pd
import os
import re
from glob import glob
from langchain_ollama import OllamaEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_chroma import Chroma


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

    # Load processed news
    news_df = pd.read_csv("data/processed/combined_news.csv")
    texts = news_df['text'].tolist()

    # Generate embeddings
    print(f"Generating embeddings for {len(texts)} documents...")
    embeddings = OllamaEmbeddings(model="nomic-embed-text")
    embedded_texts = embeddings.embed_documents(texts)

    print(f"Generated {len(embedded_texts)} embeddings of dimension {len(embedded_texts[0])}")

    # Create FAISS vector store
    faiss_vectorstore = FAISS.from_texts(texts, embeddings)
    faiss_vectorstore.save_local("data/vector_stores/faiss_news")
    print(f"FAISS vector store saved with {faiss_vectorstore.index.ntotal} vectors")

    # Create Chroma vector store
    chroma_vectorstore = Chroma.from_texts(
        texts=texts,
        embedding=embeddings,
        persist_directory="data/vector_stores/chroma_news"
    )
    print(f"Chroma vector store saved with {chroma_vectorstore._collection.count()} vectors")