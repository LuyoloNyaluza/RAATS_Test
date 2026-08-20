# Week 3 RAG Evaluation Results
# Generated from running src/rag/evaluate_rag.py on Thursday 20 Aug

## Evaluation Summary
This document records the results of evaluating different RAG system parameters including:
- Different retrieval k values (2, 4, 6)
- Different LLMs (llama3, mistral if available)

## Detailed Results

==================================================
EVALUATION RESULTS
==================================================

k_2:
------------------------------
Question: What happened with Apple stock?
Answer: Apple shares rose after the new iPhone launch.
Length: 46 characters

Question: How is Microsoft performing according to latest financial headlines?
Answer: According to the context, there is no specific information about Microsoft's performance. The context only mentions global equities and technology stocks gaining, but does not provide any details about Microsoft's financial performance.
Length: 236 characters

Question: What does the news suggest about Tesla's market position?
Answer: I don't know. The context only mentions technology stocks and global equities gaining, but it doesn't provide specific information about Tesla's market position.
Length: 161 characters

Question: Is the sentiment for Google positive or negative in recent articles?
Answer: The sentiment for Google is positive in recent articles, as they have announced a new AI breakthrough, which has been met with enthusiasm and optimism in the technology sector.
Length: 176 characters

Question: What is the overall outlook for Amazon based on current news?
Answer: Based on current news, the overall outlook for Amazon appears positive, as technology stocks, including Amazon, are gaining due to investors' continued assessment of the outlook for artificial intelligence investment. However, it's worth noting that the broader market is also influenced by weaker economic data and changing Federal Reserve policy expectations, which could impact Amazon's performance.
Length: 402 characters


k_4:
------------------------------
Question: What happened with Apple stock?
Answer: Apple shares rose after the new iPhone launch.
Length: 46 characters

Question: How is Microsoft performing according to latest financial headlines?
Answer: I don't know. The context only mentions technology stocks gaining, but it doesn't specifically mention Microsoft.
Length: 113 characters

Question: What does the news suggest about Tesla's market position?
Answer: The news suggests that Tesla's market position is strong, as it reports record quarterly deliveries.
Length: 100 characters

Question: Is the sentiment for Google positive or negative in recent articles?
Answer: The sentiment for Google is positive in recent articles, as it has announced a new AI breakthrough.
Length: 99 characters

Question: What is the overall outlook for Amazon based on current news?
Answer: Based on current news, the overall outlook for Amazon appears positive, as technology stocks, including Amazon, are gaining as investors assess the outlook for artificial intelligence investment. However, there is no specific news or data mentioned that would indicate a significant impact on Amazon's outlook.
Length: 310 characters


k_6:
------------------------------
Question: What happened with Apple stock?
Answer: Apple shares rose after the new iPhone launch.
Length: 46 characters

Question: How is Microsoft performing according to latest financial headlines?
Answer: I don't know. The context only mentions technology stocks gaining as investors assess the outlook for artificial intelligence investment, but it doesn't specifically mention Microsoft.
Length: 184 characters

Question: What does the news suggest about Tesla's market position?
Answer: The news suggests that Tesla's market position is strong, as it reports record quarterly deliveries.
Length: 100 characters

Question: Is the sentiment for Google positive or negative in recent articles?
Answer: The sentiment for Google is positive in recent articles, as it is mentioned as having announced a new AI breakthrough.
Length: 118 characters

Question: What is the overall outlook for Amazon based on current news?
Answer: I don't know. The context only mentions technology stocks and Google's AI breakthrough, but not specifically about Amazon's outlook.
Length: 132 characters


mistral:
------------------------------
Question: What happened with Apple stock?
Answer: Apple shares rose after the new iPhone launch. However, the context also mentions that technology stocks in general are gaining, suggesting a broader trend in the tech sector.
Length: 175 characters

Question: How is Microsoft performing according to latest financial headlines?
Answer: The context does not provide specific information about Microsoft's performance. However, it suggests that global equities, including technology stocks, are gaining, which could potentially be positive for companies like Microsoft. Additionally, the dollar is slipping due to softer US economic data, which might impact multinational corporations like Microsoft with significant operations in the US.
Length: 400 characters

Question: What does the news suggest about Tesla's market position?
Answer: The news suggests that Tesla's market position remains strong, as indicated by the company reporting record quarterly deliveries.
Length: 129 characters

Question: Is the sentiment for Google positive or negative in recent articles?
Answer: The sentiment for Google in recent articles is positive, as they have announced a new AI breakthrough.
Length: 102 characters

Question: What is the overall outlook for Amazon based on current news?
Answer: The overall outlook for Amazon, based on the provided context, seems to be positive as technology stocks are gaining, and global equities are also increasing. However, the specific impact of weaker economic data and changing Federal Reserve policy expectations on Amazon is not explicitly stated in the context.
Length: 311 characters

## Observations & Recommendations

### Observations:
1. **Retrieval depth (k) impact**: 
   - k=2: Often provides longer answers but sometimes lacks specificity (e.g., Microsoft query) or defaults to "I don't know" when context is insufficient.
   - k=4: Produces the most balanced responses - concise, specific, and grounded in retrieved context (e.g., Tesla's strong market position with record deliveries).
   - k=6: Increased retrieval sometimes leads to "I don't know" responses (Amazon, Microsoft), suggesting that retrieving too many documents can dilute relevant context or introduce noise that confuses the model.

2. **LLM comparison**:
   - llama3 (base model): Provides direct, concise answers when information is present in context; appropriately responds with "I don't know" when information is absent.
   - mistral: Tends to elaborate more, adding contextual information not explicitly in retrieved snippets (e.g., mentioning broader market trends, dollar fluctuations). This can be useful for providing additional perspective but risks introducing speculative content not grounded in the source data.

3. **Query-specific behaviors**:
   - Apple stock: Consistently answered across all configurations (iPhone launch impact).
   - Microsoft performance: Varied significantly - from "no specific information" (k=2) to "I don't know" (k=4,6) to speculative positive impact (mistral).
   - Tesla market position: k=2 failed to retrieve relevant info; k=4 and k=6 correctly identified strong position from record deliveries.
   - Google sentiment: Consistently positive across all configs due to clear AI breakthrough announcement.
   - Amazon outlook: Mixed responses - k=2 and mistral saw positive outlook from tech trends; k=4 noted positive but lack of specific news; k=6 couldn't determine outlook.

### Recommendations:
1. **Default retrieval setting**: Use k=4 as it provides the best balance of specificity and conciseness while minimizing "I don't know" responses for answerable questions.

2. **Model selection**: 
   - Use llama3 for fact-based, grounded responses where sticking closely to source material is important.
   - Consider mistral for exploratory analysis where broader contextual interpretation is desired, but implement fact-checking to prevent over-speculation.

3. **Prompt refinement**: 
   - The current prompts work well for clear positive signals but could be enhanced to better handle "information not present" cases.
   - Consider adding explicit instructions for the model to say "I don't know" when context lacks sufficient information (which it already does reasonably well).

4. **Next steps for optimization**:
   - Test hybrid approaches (e.g., k=4 with mistral for elaboration, then validate against source).
   - Consider implementing a confidence scoring mechanism to flag when answers are based on thin context.
   - Evaluate if domain-specific fine-tuning or specialized financial prompts improve consistency for ambiguous queries.

## Next Steps
- Standardize on k=4 as the default retrieval setting for balanced specificity and conciseness
- Use llama3 for fact-based Q&A where grounded responses are required
- Consider mistral for exploratory analysis but implement fact-checking against source documents to prevent over-speculation
- Implement a simple confidence scoring mechanism (e.g., based on retrieval scores or answer length consistency) to flag low-confidence responses
- Test hybrid approaches: use k=4 with mistral for initial elaboration, then validate key claims against retrieved source documents
- Evaluate domain-specific financial prompts that explicitly instruct the model to say "I don't know" when context lacks sufficient information
- Consider fine-tuning or specialized embedding models if financial domain performance needs further improvement