# Week 2 Log – 2026-08-10 to 2026-08-14

- Configured and updated the Python/LLM environment for the Week 2 experiments, including the Ollama and LangChain setup.
- Explored Llama3 and Mistral models.
- Tested zero-shot, few-shot, chain-of-thought, and role prompting for financial sentiment classification.
- Best results: Chain-of-thought prompting.
  - Initially tested the four prompting approaches on 2 headlines.
  - Re-tested them on 12 headlines to obtain a more reliable comparison.
  - Chain-of-thought produced the best results on the 12-headline evaluation.
- Produced sentiment predictions for 12 financial headlines.
- Exported the sentiment predictions to `data/processed/week2_sentiment_predictions.csv`.
- Documented the prompt-engineering findings in `reports/week2_prompt_report.md`.