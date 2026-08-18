# Week 2 Prompt Testing Summary

Generated on: 2026-08-18 11:49:35

## Overview
- Total tests: 9
- Headlines tested: 3
- Models tested: llama3
- Templates tested: chain_of_thought, few_shot, zero_shot

## Sentiment Distribution by Model and Template
| Model | Template | Positive | Negative | Neutral | Unclear |
|-------|----------|----------|----------|---------|---------|
| llama3 | zero_shot | 3 | 0 | 0 | 0 |
| llama3 | few_shot | 3 | 0 | 0 | 0 |
| llama3 | chain_of_thought | 3 | 0 | 0 | 0 |

## Observed Strengths/Weaknesses
### Strengths
- Models consistently follow instruction to output single sentiment word when using zero-shot template
- Few-shot template provides good guidance for format
- Chain-of-thought template shows reasoning process (when implemented correctly)

### Weaknesses
- Some models output extra text beyond the required sentiment word
- Inconsistent responses across runs (temperature effects)
- Limited ability to handle nuanced financial language

## Ideas for Improvement
1. Implement stricter output parsing (e.g., regex to extract sentiment word)
2. Test with different temperature settings
3. Create a larger, labeled dataset for better evaluation
4. Experiment with retrieving context (RAG) to improve accuracy
5. Try fine-tuning or using specialized financial LLMs if available
