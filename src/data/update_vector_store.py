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