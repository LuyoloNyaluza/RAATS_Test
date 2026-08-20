"""
src/rag/evaluate_rag.py

RAG parameter evaluation script for Week 3 Thursday activities.
Tests different retrieval k values and LLMs to optimize the RAG system.
"""


def evaluate_rag_parameters(questions, vectorstore_path="data/vector_stores/faiss_news"):
    """
    Evaluate RAG parameters including retrieval k values and different LLMs.
    
    Args:
        questions: List of questions to test
        vectorstore_path: Path to the FAISS vector store
        
    Returns:
        Dictionary with evaluation results
    """
    from langchain_community.vectorstores import FAISS
    from langchain_ollama import OllamaEmbeddings, OllamaLLM
    from langchain_classic.chains import create_retrieval_chain
    from langchain_classic.chains.combine_documents import create_stuff_documents_chain
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    # Load shared components
    embeddings = OllamaEmbeddings(model="nomic-embed-text")
    vectorstore = FAISS.load_local(
        vectorstore_path,
        embeddings,
        allow_dangerous_deserialization=True
    )
    llm = OllamaLLM(model="llama3", temperature=0.0)
    retriever = vectorstore.as_retriever(search_kwargs={"k": 4})  # default

    # Create base QA chain template
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

    results = {}

    # Test different k values
    for k in [2, 4, 6]:
        print(f"\nTesting with k={k}...")
        
        # Create retriever with specific k
        test_retriever = vectorstore.as_retriever(search_kwargs={"k": k})
        
        # Create QA chain
        question_answer_chain = create_stuff_documents_chain(llm, prompt)
        qa_chain = create_retrieval_chain(test_retriever, question_answer_chain)
        
        k_results = []
        for question in questions:
            response = qa_chain.invoke({"input": question})
            answer = response.get("answer", "") if isinstance(response, dict) else str(response)
            k_results.append({
                "question": question,
                "answer": answer.strip(),
                "length": len(answer.strip())
            })
        results[f"k_{k}"] = k_results

    # Test different LLMs if available
    try:
        llm_mistral = OllamaLLM(model="mistral", temperature=0.0)
        print("\nTesting with mistral model...")
        mistral_results = []
        
        # Use k=4 for mistral testing (standard)
        mistral_retriever = vectorstore.as_retriever(search_kwargs={"k": 4})
        question_answer_chain_mistral = create_stuff_documents_chain(llm_mistral, prompt)
        qa_chain_mistral = create_retrieval_chain(mistral_retriever, question_answer_chain_mistral)
        
        for question in questions:
            response = qa_chain_mistral.invoke({"input": question})
            answer = response.get("answer", "") if isinstance(response, dict) else str(response)
            mistral_results.append({
                "question": question,
                "answer": answer.strip(),
                "length": len(answer.strip())
            })
        results["mistral"] = mistral_results
    except Exception as e:
        print(f"Could not test mistral: {e}")

    return results


if __name__ == "__main__":
    questions = [
        "What happened with Apple stock?",
        "How is Microsoft performing according to latest financial headlines?",
        "What does the news suggest about Tesla's market position?",
        "Is the sentiment for Google positive or negative in recent articles?",
        "What is the overall outlook for Amazon based on current news?"
    ]
    
    print("Running RAG parameter evaluation...")
    print("=" * 50)
    
    results = evaluate_rag_parameters(questions)
    
    print("\n" + "=" * 50)
    print("EVALUATION RESULTS")
    print("=" * 50)
    
    for key, value in results.items():
        print(f"\n{key}:")
        print("-" * 30)
        for res in value:
            print(f"Question: {res['question']}")
            print(f"Answer: {res['answer']}")
            print(f"Length: {res['length']} characters")
            print()