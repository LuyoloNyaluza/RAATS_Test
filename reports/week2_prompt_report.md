# Week 2 Prompt Engineering Report

## Objective

The objective of this experiment was to apply the best-performing
prompt from the prompt engineering experiment to a larger set of
financial headlines and evaluate the resulting sentiment predictions.

## Prompt Selection

Four prompt styles were evaluated: zero-shot, few-shot,
chain-of-thought, and role prompting.

Based on the 12-headline comparison, chain-of-thought prompting
performed best, achieving the highest manually assessed accuracy.
It was therefore selected for the Week 2 financial sentiment
experiment.

## Sentiment Analysis

The selected chain-of-thought prompt was applied to 12 financial
headlines covering equities, commodities, currencies, interest
rates, and broader economic developments.

The model's complete responses were recorded in the results rather
than storing only the final sentiment label. This allows the model's
reasoning and final classifications to be manually inspected.

## Manual Verification

A sample of the predictions was manually reviewed to assess whether
the model's classifications were reasonable in the context of the
financial headlines.

The selected examples showed that the model was generally able to
identify positive and negative market signals. Chain-of-thought
prompting was particularly useful when a headline required some
interpretation of its potential impact on financial markets.

## Observations

Chain-of-thought prompting produced more detailed responses than
the other prompt styles. Although the additional explanations
increase the amount of generated text, they made the predictions
easier to inspect and understand.

The experiment also showed that financial sentiment can sometimes
depend on perspective. For example, falling oil prices may benefit
consumers but negatively affect oil producers. Therefore, the
financial-market context used for classification is important.

## Output

The sentiment predictions were exported to:

`data/processed/week2_sentiment_predictions.csv`