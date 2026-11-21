"""Compare Ollama models on the REAL scoring prompt (src/data/score_sentiment.py).

    python -m src.data.compare_sentiment_models                      # the default candidates
    python -m src.data.compare_sentiment_models qwen2.5:3b gemma3:4b # your own list

Why this exists: 3 clear-cut headlines per ticker cannot separate models (all of them get them
right). This set has 36 labelled headlines, half of them hard on purpose: a beat with a weak
outlook, news about a competitor, negations, procedural news, a headline about another company.

Models run ONE AT A TIME and are unloaded (keep_alive=0) before the next starts, so RAM never
holds two of them. Reported per model: accuracy, hard-case accuracy, invalid answers, seconds
per article, memory Ollama loaded it with, and how confident it was when right vs wrong
(a model that says 0.9 whether it is right or wrong gives you no usable confidence).
Labels are one analyst's judgement: where you disagree, edit CASES.
Flags: --heldout (fresh headlines only), --all (both sets). Models are the non-flag arguments.
"""
import csv
import sys
import time
from typing import Any, Dict, List, Tuple

from src.data import score_sentiment as S

DEFAULT_MODELS = ["qwen2.5:3b", "gemma3:4b", "phi3:mini-128k", "qwen2.5-coder:7b"]

# (ticker, headline, description, expected, hard)
CASES: List[Tuple[str, str, str, str, bool]] = [
    # --- clear
    ("AAPL", "Apple reports record quarterly revenue", "Revenue and iPhone sales rose well above forecasts.", "positive", False),
    ("AAPL", "Apple faces new App Store restrictions", "Regulators move to cut App Store fees, hitting services revenue.", "negative", False),
    ("MSFT", "Microsoft shares trade steadily ahead of earnings", "The stock moves in a narrow range.", "neutral", False),
    ("NVDA", "NVIDIA data centre revenue beats estimates", "AI GPU demand lifts results above analyst expectations.", "positive", False),
    ("NVDA", "NVIDIA warns export limits will cut chip sales", "New restrictions close key markets.", "negative", False),
    ("TSLA", "Tesla recalls 400,000 vehicles over braking fault", "The recall is expected to cost hundreds of millions.", "negative", False),
    ("AMZN", "Amazon raises full-year profit forecast", "Cloud margins improve and retail costs fall.", "positive", False),
    ("META", "Meta to hold annual shareholder meeting on June 4", "Proxy materials were filed with the SEC.", "neutral", False),
    ("JPM", "JPMorgan profit jumps 18% on trading gains", "Results beat consensus.", "positive", False),
    ("XOM", "Exxon cuts dividend after weak oil prices", "The payout falls by a third.", "negative", False),
    ("KO", "Coca-Cola names new regional marketing head", "The appointment takes effect next month.", "neutral", False),
    ("DIS", "Disney streaming subscribers surge past forecasts", "Streaming turns profitable a year early.", "positive", False),
    # --- hard
    ("CSCO", "Cisco beats earnings but cuts next-quarter outlook", "Shares fall in extended trading as guidance disappoints.", "negative", True),
    ("AMD", "Intel loses major data-centre customer to AMD", "The customer will move its servers to AMD chips.", "positive", True),
    ("F", "Ford's quarterly loss is narrower than feared", "Analysts had expected a deeper loss.", "positive", True),
    ("MSFT", "Analyst downgrades NVIDIA on valuation", "Microsoft is mentioned only as a large NVIDIA customer.", "neutral", True),
    ("PFE", "Pfizer drug did not miss its main trial goal", "The trial met its primary endpoint.", "positive", True),
    ("BA", "Boeing delivers fewer planes than expected", "Deliveries fell short of the forecast for a third month.", "negative", True),
    ("INTC", "Intel announces new foundry partnership, no financial terms", "Details were not disclosed.", "neutral", True),
    ("UBER", "Uber stock jumps despite a wider loss", "Revenue growth and bookings beat expectations.", "positive", True),
    ("NFLX", "Netflix raises prices; subscriber growth slows", "Analysts see mixed effects on revenue.", "neutral", True),
    ("GM", "GM recalls trucks; rival Ford shares rise", "The recall affects 120,000 GM trucks.", "negative", True),
    ("WMT", "Walmart not expected to lose market share, says analyst", "The analyst reiterates the current rating.", "neutral", True),
    ("COIN", "Coinbase trading volume plunges 40%", "Lower volumes will pressure fee revenue.", "negative", True),
    ("SBUX", "Starbucks CEO steps down after strong year", "The board thanked him; a successor is being sought.", "neutral", True),
    ("AMD", "AMD says supply is sold out for the quarter", "Strong demand but limited capacity may cap sales.", "positive", True),
    ("TSLA", "Tesla delivers record vehicles but price cuts squeeze margins", "Margins fell to a multi-year low.", "negative", True),
    ("AAPL", "Apple to hold product event next Tuesday", "Invitations were sent to the press.", "neutral", True),
    ("PLTR", "Palantir wins $480 million Army contract", "The multi-year deal expands existing work.", "positive", True),
    ("LCID", "Lucid plans to raise $1 billion by selling new shares", "The offering will dilute existing holders.", "negative", True),
    # --- more clear, to balance the classes
    ("GOOGL", "Alphabet ad revenue grows 15%", "Search and YouTube both beat estimates.", "positive", False),
    ("PYPL", "PayPal hit by data breach affecting millions", "Regulators open an inquiry.", "negative", False),
    ("PEP", "PepsiCo to webcast its earnings call", "The call starts at 8:30am.", "neutral", False),
    ("CRM", "Salesforce wins landmark government deal", "The contract is worth billions over five years.", "positive", False),
    ("SNAP", "Snap shares plunge after missing user targets", "Daily users came in below guidance.", "negative", False),
    ("ORCL", "Oracle completes routine debt refinancing", "Terms were in line with market rates.", "neutral", False),
]


# Fresh headlines, NOT used when the prompt's evaluation rules were written. The rules were shaped
# by the failure types seen on CASES, so CASES alone flatters them; judge a prompt change on this
# set:  python -m src.data.compare_sentiment_models --heldout phi3:mini-128k
HELDOUT: List[Tuple[str, str, str, str, bool]] = [
    ("HD", "Home Depot lifts annual sales outlook", "Strong spring demand and cost savings.", "positive", False),
    ("TGT", "Target posts weaker holiday sales, trims forecast", "Store traffic fell and discounting rose.", "negative", False),
    ("CAT", "Caterpillar to publish results on Thursday", "The company will hold a conference call.", "neutral", False),
    ("QCOM", "Qualcomm signs multi-year chip supply deal with Samsung", "The deal is worth an estimated $3 billion.", "positive", False),
    ("NKE", "Nike to open new store in Madrid", "The flagship opens in spring.", "neutral", True),
    ("INTC", "AMD wins server contract from a major cloud provider", "Intel had been the previous supplier.", "negative", True),
    ("BAC", "Bank of America names new head of consumer lending", "The executive joins from a rival bank.", "neutral", True),
    ("UAL", "United Airlines fuel costs fall 12%", "Lower jet fuel prices boost margins.", "positive", False),
    ("PFE", "Pfizer trial fails to meet primary endpoint", "Shares drop in premarket trading.", "negative", False),
    ("MRK", "Merck raises $2 billion in new share offering", "Proceeds fund acquisitions; existing holders are diluted.", "negative", True),
    ("LOW", "Lowe's earnings beat estimates but guidance falls short", "Investors had hoped for a stronger outlook.", "negative", True),
    ("COST", "Costco comparable sales rise 8%", "Above analyst forecasts.", "positive", False),
    ("V", "Visa and Mastercard both report steady volumes", "No change in guidance for either.", "neutral", True),
    ("AMAT", "Applied Materials loss narrower than analysts feared", "Results came in above low expectations.", "positive", True),
    ("GE", "GE Aerospace wins engine order after rival's grounding", "The airline switches from a competitor's engines to GE's.", "positive", True),
    ("DAL", "Delta schedules investor day for next month", "Presentations will be webcast.", "neutral", False),
    ("BABA", "Alibaba faces new antitrust probe", "Regulators may impose fines.", "negative", False),
    ("SPOT", "Spotify user growth exceeds forecasts", "Paid subscribers rose 14%.", "positive", False),
    ("MCD", "McDonald's completes scheduled bond repayment", "The repayment was made at maturity.", "neutral", True),
    ("RIVN", "Rivian halts production at main plant after fire", "Output is suspended for weeks.", "negative", False),
    ("ADBE", "Adobe stock steady after analyst reiterates rating", "No change to the price target.", "neutral", False),
    ("ZM", "Zoom revenue did not decline as feared", "Sales were flat, beating forecasts of a drop.", "positive", True),
    ("NOK", "Ericsson wins deal that Nokia had bid for", "Nokia lost the contract.", "negative", True),
    ("LLY", "Eli Lilly obesity drug approved in Europe", "Regulators clear sales across the EU.", "positive", False),
]


def _unload(model: str) -> None:
    try:
        S.ollama.generate(model=model, prompt="", keep_alive=0)
    except Exception:
        pass


def _loaded_gb(model: str) -> float:
    try:
        for m in S.ollama.ps().get("models", []):
            name = m.get("name") or m.get("model")
            if name and name.startswith(model.split(":")[0]) and model in (name, m.get("model")):
                return float(m.get("size", 0)) / 1e9
    except Exception:
        pass
    return 0.0


def run_model(model: str, cases=None) -> Dict[str, Any]:
    cases = cases or CASES
    rows, ok, hard_ok, hard_n, invalid = [], 0, 0, 0, 0
    conf_right, conf_wrong, seconds = [], [], []
    for ticker, title, desc, expected, hard in cases:
        art = {"title": title, "description": desc, "source": {"name": "Financial News"}}
        t0 = time.time()
        res = S.score_article(ticker, art, model_name=model, use_memory=False)
        seconds.append(time.time() - t0)
        if res.get("confidence", 0.0) == 0.0:          # no usable answer (empty / unparsable / error)
            invalid += 1
        right = res["sentiment"] == expected
        ok += right
        if hard:
            hard_n += 1
            hard_ok += right
        (conf_right if right else conf_wrong).append(res["confidence"])
        rows.append([model, ticker, title, expected, res["sentiment"], f"{res['confidence']:.2f}", int(hard)])
    gb = _loaded_gb(model)
    _unload(model)
    avg = lambda v: sum(v) / len(v) if v else float("nan")
    return {"model": model, "accuracy": ok / len(cases), "hard_accuracy": hard_ok / max(hard_n, 1),
            "invalid": invalid, "sec_per_article": avg(seconds), "loaded_gb": gb,
            "conf_when_right": avg(conf_right), "conf_when_wrong": avg(conf_wrong), "_rows": rows}


def main(argv: List[str]) -> None:
    if S.ollama is None:
        sys.exit("pip install ollama")
    flags = [a for a in argv if a.startswith("--")]
    cases = HELDOUT if "--heldout" in flags else CASES + HELDOUT if "--all" in flags else CASES
    models = [a for a in argv if not a.startswith("--")] or DEFAULT_MODELS
    results, all_rows = [], []
    for m in models:
        print(f"\n--- {m} ({len(cases)} articles) ---", flush=True)
        try:
            r = run_model(m, cases)
        except Exception as exc:                      # not pulled, out of memory, ...
            print(f"  skipped: {exc}")
            continue
        all_rows += r.pop("_rows")
        results.append(r)
    print("\n{:<20}{:>7}{:>7}{:>9}{:>8}{:>8}{:>9}{:>9}".format(
        "model", "acc", "hard", "invalid", "s/art", "GB", "conf ok", "conf bad"))
    for r in sorted(results, key=lambda r: -r["accuracy"]):
        print("{:<20}{:>7.0%}{:>7.0%}{:>9}{:>8.1f}{:>8.1f}{:>9.2f}{:>9.2f}".format(
            r["model"], r["accuracy"], r["hard_accuracy"], r["invalid"], r["sec_per_article"],
            r["loaded_gb"], r["conf_when_right"], r["conf_when_wrong"]))
    with open("sentiment_model_comparison.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["model", "ticker", "headline", "expected", "got", "confidence", "hard"])
        w.writerows(all_rows)
    print("\nPer-article answers: sentiment_model_comparison.csv")


if __name__ == "__main__":
    main(sys.argv[1:])