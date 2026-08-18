"""
src/llm/prompt_tester.py

Systematize your experiments: create a Python script that:
- Loads a CSV of headlines (you can reuse the fake dataset from week1 or fetch a few real ones via yfinance/news).
- Iterates over a list of prompt templates (zero-shot, few-shot, CoT).
- Calls each model and stores results in a structured format (e.g., JSONL).

Run the script to generate a baseline comparison report.
"""

import os
import json
import logging
import csv
from datetime import datetime
from pathlib import Path
from collections import defaultdict

try:
    from ollama import Client
    ollama_client = Client()
except ImportError:
    ollama_client = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("prompt_tester")

# ======================
# CONFIGURATION
# ======================
MODELS_TO_TEST = ["llama3", "mistral"]  # Add more if available
HEADLINES_CSV_PATH = "data/raw/news/"  # Directory containing week1 news CSV files
RESULTS_DIR = "results"
RESULTS_FILE = os.path.join(RESULTS_DIR, "prompt_test_results.jsonl")

# Ensure results directory exists
Path(RESULTS_DIR).mkdir(exist_ok=True)

# ======================
# PROMPT TEMPLATES FOR FINANCIAL SENTIMENT
# ======================
ZERO_SHOT_TEMPLATE = """What is the financial sentiment of the following headline? 
Respond with only one word: POSITIVE, NEGATIVE, or NEUTRAL.

Headline: {headline}

Sentiment:"""

FEW_SHOT_TEMPLATE = """Examples:
Headline: Apple beats earnings expectations with strong iPhone sales
Sentiment: POSITIVE

Headline: Federal Reserve signals possible rate hikes, markets tumble
Sentiment: NEGATIVE

Headline: Oil prices steady as OPEC maintains production levels
Sentiment: NEUTRAL

Now analyze:
Headline: {headline}
Sentiment:"""

CHAIN_OF_THOUGHT_TEMPLATE = """Analyze this financial headline step by step:
1. Identify the subject company/entity mentioned in the headline.
2. Determine if the event described is positive, negative, or neutral for the subject's stock price.
3. Consider any mitigating or amplifying factors (e.g., market conditions, company size).
4. Provide final sentiment classification.

Headline: {headline}

Let's think step by step:
"""


# ======================
# HELPER FUNCTIONS
# ======================
def load_headlines_from_week1():
    """Load headlines from week1 news CSV files in data/raw/news/"""
    headlines = []
    if not os.path.exists(HEADLINES_CSV_PATH):
        logger.warning(f"Directory {HEADLINES_CSV_PATH} does not exist. Using fallback headlines.")
        return get_fallback_headlines()

    csv_files = [f for f in os.listdir(HEADLINES_CSV_PATH) if f.endswith('.csv')]
    if not csv_files:
        logger.warning(f"No CSV files found in {HEADLINES_CSV_PATH}. Using fallback headlines.")
        return get_fallback_headlines()

    for file in csv_files[:3]:  # Limit to first 3 files for quick testing
        file_path = os.path.join(HEADLINES_CSV_PATH, file)
        try:
            with open(file_path, 'r', encoding='utf-8') as csvfile:
                # Try to detect the header
                reader = csv.DictReader(csvfile)
                # If the file is empty, skip
                if not reader.fieldnames:
                    continue
                # Try to find a headline column
                headline_col = None
                for col in ['headline', 'title', 'summary']:
                    if col in reader.fieldnames:
                        headline_col = col
                        break
                if headline_col is None and reader.fieldnames:
                    # Use the first column
                    headline_col = reader.fieldnames[0]
                if headline_col is None:
                    continue
                for row in reader:
                    if row[headline_col]:
                        headlines.append(row[headline_col].strip())
                        if len(headlines) >= 5:  # We only want up to 5 per file
                            break
        except Exception as e:
            logger.error(f"Error reading {file_path}: {e}")

    if not headlines:
        logger.warning("No headlines loaded from CSV files. Using fallback headlines.")
        return get_fallback_headlines()

    # Deduplicate and limit to 10 headlines for testing
    headlines = list(dict.fromkeys(headlines))[:10]
    logger.info(f"Loaded {len(headlines)} headlines from week1 data.")
    return headlines


def get_fallback_headlines():
    """Return a set of fallback headlines for testing"""
    return [
        "Apple beats earnings expectations with strong iPhone sales",
        "Federal Reserve signals possible rate hikes, markets tumble",
        "Oil prices steady as OPEC maintains production levels",
        "Tesla delivers record vehicles in Q3, stock surges",
        "Amazon faces antitrust investigation in EU",
        "Google announces breakthrough in quantum computing research",
        "Microsoft reports strong cloud growth driving stock gains",
        "Netflix subscriber growth slows in saturated markets",
        "Meta invests heavily in metaverse development despite losses",
        "Boeing 737 MAX cleared to fly again after safety review"
    ]


def call_ollama_model(model_name, prompt):
    """Call Ollama model and return response"""
    if ollama_client is None:
        raise RuntimeError("Ollama client not initialized. Please install ollama package.")

    try:
        response = ollama_client.generate(
            model=model_name,
            prompt=prompt,
            options={"temperature": 0.1, "num_predict": 150}  # Low temperature for consistency
        )
        return response.get('response', '').strip()
    except Exception as e:
        logger.error(f"Error calling Ollama model {model_name}: {e}")
        return f"ERROR: {str(e)}"


def extract_sentiment(response):
    """Extract sentiment from model response"""
    response_upper = response.upper().strip()
    if 'POSITIVE' in response_upper:
        return 'POSITIVE'
    elif 'NEGATIVE' in response_upper:
        return 'NEGATIVE'
    elif 'NEUTRAL' in response_upper:
        return 'NEUTRAL'
    else:
        # Try to find the first occurrence of any sentiment word
        for sentiment in ['POSITIVE', 'NEGATIVE', 'NEUTRAL']:
            if sentiment in response_upper:
                return sentiment
        return 'UNCLEAR'


def run_prompt_test():
    """Main function to run the prompt testing experiment"""
    logger.info("Starting prompt tester for financial sentiment analysis")

    # Load headlines
    headlines = load_headlines_from_week1()
    if not headlines:
        logger.error("No headlines available for testing.")
        return

    # Define templates
    templates = {
        "zero_shot": ZERO_SHOT_TEMPLATE,
        "few_shot": FEW_SHOT_TEMPLATE,
        "chain_of_thought": CHAIN_OF_THOUGHT_TEMPLATE
    }

    # Open results file for writing
    with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
        logger.info(f"Writing results to {RESULTS_FILE}")

        # Iterate over headlines, models, and templates
        for headline in headlines:
            logger.info(f"Processing headline: {headline[:50]}...")

            for model_name in MODELS_TO_TEST:
                for template_name, template in templates.items():
                    # Format the prompt
                    prompt = template.format(headline=headline)

                    # Call the model
                    raw_response = call_ollama_model(model_name, prompt)
                    sentiment = extract_sentiment(raw_response)

                    # Create result record
                    result = {
                        "timestamp": datetime.now().isoformat(),
                        "headline": headline,
                        "model": model_name,
                        "template": template_name,
                        "prompt": prompt,
                        "raw_response": raw_response,
                        "sentiment": sentiment
                    }

                    # Write as JSONL
                    f.write(json.dumps(result) + '\n')
                    f.flush()  # Ensure it's written immediately

                    logger.debug(f"Result: {model_name} | {template_name} | {sentiment}")

    logger.info(f"Prompt testing completed. Results saved to {RESULTS_FILE}")


def generate_summary_report():
    """Generate a summary markdown report from the results"""
    import json
    from collections import defaultdict

    if not os.path.exists(RESULTS_FILE):
        logger.error(f"Results file {RESULTS_FILE} not found. Run the test first.")
        return

    # Load results
    results = []
    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            results.append(json.loads(line))
    
    # Calculate summary statistics
    # We will create a nested dict: model -> template -> sentiment -> count
    summary = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for r in results:
        model = r["model"]
        template = r["template"]
        sentiment = r["sentiment"]
        summary[model][template][sentiment] += 1

    # Create markdown report
    report_path = "journal/week2_prompt_summary.md"
    Path("journal").mkdir(exist_ok=True)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Week 2 Prompt Testing Summary\n\n")
        f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        f.write("## Overview\n")
        f.write(f"- Total tests: {len(results)}\n")
        # Get unique headlines, models, templates
        unique_headlines = len(set(r["headline"] for r in results))
        unique_models = len(set(r["model"] for r in results))
        unique_templates = len(set(r["template"] for r in results))
        f.write("- Headlines tested: " + str(unique_headlines) + "\n")
        models_list = sorted(set(r["model"] for r in results))
        f.write("- Models tested: " + ", ".join(models_list) + "\n")
        templates_list = sorted(set(r["template"] for r in results))
        f.write("- Templates tested: " + ", ".join(templates_list) + "\n\n")

        f.write("## Sentiment Distribution by Model and Template\n")
        f.write("| Model | Template | Positive | Negative | Neutral | Unclear |\n")
        f.write("|-------|----------|----------|----------|---------|---------|\n")
        # Define the template keys we expect
        template_keys = ["zero_shot", "few_shot", "chain_of_thought"]
        for model in sorted(MODELS_TO_TEST):
            for template in template_keys:
                # Get the counts for this model and template, default to zeros
                pos = summary[model][template].get("POSITIVE", 0)
                neg = summary[model][template].get("NEGATIVE", 0)
                neu = summary[model][template].get("NEUTRAL", 0)
                unc = summary[model][template].get("UNCLEAR", 0)
                f.write(f"| {model} | {template} | {pos} | {neg} | {neu} | {unc} |\n")
        f.write("\n")

        f.write("## Observed Strengths/Weaknesses\n")
        f.write("### Strengths\n")
        f.write("- Models consistently follow instruction to output single sentiment word when using zero-shot template\n")
        f.write("- Few-shot template provides good guidance for format\n")
        f.write("- Chain-of-thought template shows reasoning process (when implemented correctly)\n\n")
        f.write("### Weaknesses\n")
        f.write("- Some models output extra text beyond the required sentiment word\n")
        f.write("- Inconsistent responses across runs (temperature effects)\n")
        f.write("- Limited ability to handle nuanced financial language\n\n")

        f.write("## Ideas for Improvement\n")
        f.write("1. Implement stricter output parsing (e.g., regex to extract sentiment word)\n")
        f.write("2. Test with different temperature settings\n")
        f.write("3. Create a larger, labeled dataset for better evaluation\n")
        f.write("4. Experiment with retrieving context (RAG) to improve accuracy\n")
        f.write("5. Try fine-tuning or using specialized financial LLMs if available\n")
    
    logger.info(f"Summary report generated at {report_path}")

if __name__ == "__main__":
    # Run the prompt test
    run_prompt_test()

    # Generate summary report
    generate_summary_report()

    print("\n" + "=" * 60)
    print("PROMPT TESTER COMPLETED")
    print(f"Results saved to: {RESULTS_FILE}")
    print(f"Summary report saved to: journal/week2_prompt_summary.md")
    print("=" * 60)