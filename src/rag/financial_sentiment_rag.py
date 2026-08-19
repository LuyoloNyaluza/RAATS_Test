"""
src/rag/financial_sentiment_rag.py

Two RAG chains over the same FAISS news index:
1. create_financial_rag_chain()  -> general Q&A over the news corpus
2. create_sentiment_chain()      -> stock-specific sentiment analysis
"""

from langchain_community.vectorstores import FAISS
from langchain_ollama import OllamaEmbeddings, OllamaLLM
from langchain_classic.chains import create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.output_parsers import StrOutputParser

VECTORSTORE_PATH = "data/vector_stores/faiss_news"


def _load_vectorstore(vectorstore_path: str = VECTORSTORE_PATH):
    """Shared helper: load the FAISS index with the embeddings model."""
    embeddings = OllamaEmbeddings(model="nomic-embed-text")
    return FAISS.load_local(
        vectorstore_path,
        embeddings,
        allow_dangerous_deserialization=True
    )


def create_financial_rag_chain(vectorstore_path: str = VECTORSTORE_PATH):
    """General-purpose Q&A chain over the news corpus."""
    vectorstore = _load_vectorstore(vectorstore_path)
    llm = OllamaLLM(model="llama3", temperature=0.0)
    retriever = vectorstore.as_retriever(search_kwargs={"k": 4})

    system_prompt = (
        "Use the given context to answer the question. "
        "If the context contains conflicting information, note the "
        "conflict rather than blending it into one narrative. "
        "If you don't know the answer, say you don't know. "
        "Use three sentences maximum and keep the answer concise.\n\n"
        "Context: {context}"
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{input}"),
    ])

    question_answer_chain = create_stuff_documents_chain(llm, prompt)
    qa_chain = create_retrieval_chain(retriever, question_answer_chain)

    return qa_chain


def create_sentiment_chain(vectorstore_path: str = VECTORSTORE_PATH):
    """
    Returns a function get_sentiment(stock) that retrieves relevant
    headlines for `stock` and asks the LLM for a POSITIVE/NEGATIVE/NEUTRAL
    sentiment analysis grounded in that context.
    """
    vectorstore = _load_vectorstore(vectorstore_path)
    llm = OllamaLLM(model="llama3", temperature=0.0)
    retriever = vectorstore.as_retriever(search_kwargs={"k": 4})

    financial_prompt_template = """Based on the following financial news headlines and summaries,
provide a concise analysis of the overall sentiment for {stock}.
Consider both positive and negative indicators, and conclude with
whether the sentiment is predominantly POSITIVE, NEGATIVE, or NEUTRAL.

News Context:
{context}

Question: What is the overall sentiment for {stock}?

Answer:"""

    financial_prompt = PromptTemplate(
        template=financial_prompt_template,
        input_variables=["stock", "context"]
    )

    chain = financial_prompt | llm | StrOutputParser()

    def get_sentiment(stock: str) -> str:
        docs = retriever.invoke(stock)
        context = "\n".join(doc.page_content for doc in docs)
        return chain.invoke({"stock": stock, "context": context})

    return get_sentiment


def extract_stock_name(question: str, llm: OllamaLLM | None = None) -> str:
    """
    Use the LLM to pull the company/stock name out of a natural-language
    question. This generalizes to any company mentioned in the question
    (no hardcoded list to maintain), unlike regex-based extraction which
    only catches specific sentence phrasings.

    Falls back to "the market" if no company is mentioned.
    """
    llm = llm or OllamaLLM(model="llama3", temperature=0.0)

    extraction_prompt = (
        "Extract only the company or stock name mentioned in the question "
        "below. Reply with just the company name and nothing else -- no "
        "punctuation, no explanation. If no company is mentioned, reply "
        "exactly: the market\n\n"
        f"Question: {question}\n"
        "Company:"
    )
    result = llm.invoke(extraction_prompt).strip()

    # Light cleanup in case the model adds stray punctuation/quotes
    result = result.strip('."\' \n')

    return result if result else "the market"


if __name__ == "__main__":
    # --- General Q&A ---
    qa_chain = create_financial_rag_chain()
    response = qa_chain.invoke({"input": "What happened with oil prices?"})
    print("=== General Q&A ===")
    print(response["answer"])
    print("\nRetrieved context:")
    for i, doc in enumerate(response["context"], 1):
        print(f"{i}. {doc.page_content}")

    # --- Stock-specific sentiment, with LLM-based entity extraction ---
    print("\n=== Sentiment Analysis ===")
    sentiment_fn = create_sentiment_chain()
    extractor_llm = OllamaLLM(model="llama3", temperature=0.0)

    test_questions = [
        "What is the sentiment for Apple based on recent news?",
        "How is Microsoft performing according to latest financial headlines?",
        "What does the news suggest about Tesla's market position?",
    ]

    for question in test_questions:
        stock = extract_stock_name(question, llm=extractor_llm)
        answer = sentiment_fn(stock)
        print(f"\nQ: {question}")
        print(f"(extracted stock: {stock})")
        print(f"A: {answer.strip()}")
