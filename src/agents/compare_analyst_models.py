"""Compare Ollama models as the ANALYST (src/agents/analyst.py), using the real analyze_market().

  python -m src.agents.compare_analyst_models                         # labelled scenarios, default models
  python -m src.agents.compare_analyst_models llama3 phi3:mini-128k   # your own list (first = reference)
  python -m src.agents.compare_analyst_models --saved                 # saved data: who says INVEST how often
  python -m src.agents.compare_analyst_models --saved --tickers AAPL MSFT --limit 20

SCENARIO mode: 13 made-up situations with one defensible answer each (6 INVEST, 7 HOLD). The analyst
prompt asks for strictness ("avoid unjustified investments"), so HOLD is the default and INVEST
needs clear, consistent, relevant evidence. The costly error is a FALSE INVEST (a HOLD case called
INVEST). Labels are one analyst's judgement; the two marked "hard" are arguable. Edit SCENARIOS.

SAVED mode: no labels. It reads data/processed/indicators/<T>_indicators.csv (last row) and, when
present, data/raw/news/<T>_news_scored.json, runs every model on the SAME inputs and reports each
model's INVEST rate and how often it agrees with the first (reference) model.

Models run one at a time and are unloaded afterwards, so RAM never holds two.
"""
import argparse
import csv
import glob
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

from src.agents import analyst as A

DEFAULT_MODELS = ["llama3", "phi3:mini-128k", "qwen2.5:3b", "gemma3:4b"]
D = "2026-11-19"
OLD = "2026-10-27"


def _n(title, desc="", date=D):
    return {"title": title, "description": desc, "publishedAt": date, "source": {"name": "Financial News"}}


# id, ticker, close, sma_10, rsi, sentiment, news, history (older titles, newest first), expected, hard
SCENARIOS: List[Dict[str, Any]] = [
    dict(id="strong-1", ticker="AAA", close=105, sma=100, rsi=58, sent=0.75, expected="INVEST", hard=False, history=[],
         news=[_n("AAA reports record revenue, raises full-year outlook", "Revenue rose 22% and management lifted guidance."),
               _n("AAA wins $2 billion multi-year contract", "The deal expands its largest business line."),
               _n("Analysts lift AAA earnings estimates after results", "Several brokers raised forecasts.")]),
    dict(id="strong-2", ticker="BBB", close=212, sma=205, rsi=55, sent=0.80, expected="INVEST", hard=False, history=[],
         news=[_n("BBB lead drug wins regulatory approval", "Sales forecasts for the drug were doubled."),
               _n("BBB lifts revenue guidance after approval", "Management expects faster growth next year.")]),
    dict(id="strong-3", ticker="CCC", close=48.5, sma=46, rsi=52, sent=0.70, expected="INVEST", hard=False, history=[],
         news=[_n("CCC signs supply deal with major retailer", "Profit forecast raised."),
               _n("CCC demand surges as orders double", "Backlog reaches a record.")]),
    dict(id="strong-4", ticker="DDD", close=77, sma=74, rsi=61, sent=0.85, expected="INVEST", hard=False, history=[],
         news=[_n("DDD quarterly profit beats estimates by 30%", "A new share buyback was announced."),
               _n("DDD raises guidance for the second time this year", "Demand remains strong.")]),
    dict(id="override-history", ticker="EEE", close=130, sma=120, rsi=60, sent=0.85, expected="INVEST", hard=True,
         history=["EEE shares slip after weak guidance", "EEE misses quarterly estimates"],
         news=[_n("EEE reports record revenue, up 25%", "Outlook raised sharply."),
               _n("EEE wins major new contract", "Largest order in company history.")]),
    dict(id="oversold-positive", ticker="FFF", close=31, sma=36, rsi=28, sent=0.70, expected="INVEST", hard=True, history=[],
         news=[_n("FFF wins turnaround contract worth $800 million", "Forecast lifted after the award."),
               _n("FFF orders recover strongly", "Customers return after last year's problems.")]),
    dict(id="no-news", ticker="GGG", close=100, sma=100.2, rsi=50, sent=0.0, expected="HOLD", hard=False, history=[], news=[]),
    dict(id="unrelated-news", ticker="HHH", close=55, sma=54, rsi=49, sent=0.05, expected="HOLD", hard=False, history=[],
         news=[_n("Oil prices drift as traders await inventory data", "Crude moved within a narrow band."),
               _n("Central bank leaves interest rates unchanged", "No change expected until spring.")]),
    dict(id="stale-duplicates", ticker="III", close=60, sma=58, rsi=56, sent=0.60, expected="HOLD", hard=False, history=[],
         news=[_n("III plans store openings next year", "Expansion planned.", OLD)] * 3),
    dict(id="overbought-weak", ticker="JJJ", close=180, sma=150, rsi=88, sent=0.30, expected="HOLD", hard=False, history=[],
         news=[_n("JJJ gains after analyst reiterates rating", "No change to the price target.")]),
    dict(id="mixed-news", ticker="KKK", close=40, sma=40, rsi=50, sent=0.0, expected="HOLD", hard=False, history=[],
         news=[_n("KKK profit rises but outlook is cut", "Results were mixed."),
               _n("KKK wins small contract, loses larger customer", "Net effect is unclear.")]),
    dict(id="routine-news", ticker="LLL", close=90, sma=89, rsi=51, sent=0.0, expected="HOLD", hard=False, history=[],
         news=[_n("LLL schedules investor day for next month", "Presentations will be webcast."),
               _n("LLL names new regional director", "The appointment is effective next month.")]),
    dict(id="false-starts", ticker="MMM", close=70, sma=69, rsi=52, sent=0.10, expected="HOLD", hard=False,
         history=["MMM rallies on rumours, then reverses", "MMM gains fade after company denial",
                  "MMM jumps on speculation, closes lower"],
         news=[_n("MMM stock steady as market awaits earnings", "Trading was quiet.")]),
]


def _patch_history(titles: List[str]) -> None:
    """Give analyze_market a controlled 'earlier coverage' list instead of the real news memory."""
    try:
        import src.rag.news_memory as NM
        items = [{"date": f"2026-11-{17 - i:02d}", "title": t} for i, t in enumerate(titles)]
        NM.recent_for_ticker = lambda *a, **k: items
    except Exception:
        pass


def _state(ticker, close, sma, rsi, sent, news, ) -> Dict[str, Any]:
    return {"ticker": ticker, "market_data": {"close": close, "sma_10": sma, "rsi": rsi}, "sentiment": sent,
            "discovery_news": {"yfinance_news": [], "google_news": news}}


def _ask(model: str, state: Dict[str, Any]):
    t0 = time.time()
    out = A.analyze_market(state, model_name=model)
    secs = time.time() - t0
    note = str(out.get("llm_analysis", ""))
    invalid = note.startswith("Failed to parse") or note.startswith("Error during analysis")
    try:
        conf = float(out.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    return out.get("signal", "HOLD"), conf, secs, invalid, note


def _unload(model: str) -> None:
    try:
        A.ollama.generate(model=model, prompt="", keep_alive=0)
    except Exception:
        pass


def _loaded_gb(model: str) -> float:
    try:
        for m in A.ollama.ps().get("models", []):
            names = {str(m.get("name")), str(m.get("model"))}
            if model in names or f"{model}:latest" in names:
                return float(m.get("size", 0)) / 1e9
    except Exception:
        pass
    return 0.0


def run_scenarios(models: List[str]) -> None:
    results, rows, answers = [], [], {}
    for m in models:
        print(f"\n--- {m} ({len(SCENARIOS)} scenarios) ---", flush=True)
        try:
            ok = inv_ok = false_inv = invalid = 0
            secs, c_right, c_wrong, got_all = [], [], [], {}
            for sc in SCENARIOS:
                _patch_history(sc["history"])
                sig, conf, s, bad, why = _ask(m, _state(sc["ticker"], sc["close"], sc["sma"], sc["rsi"], sc["sent"], sc["news"]))
                secs.append(s); invalid += bad
                right = sig == sc["expected"]
                ok += right
                inv_ok += right and sc["expected"] == "INVEST"
                false_inv += (sig == "INVEST" and sc["expected"] == "HOLD")
                (c_right if right else c_wrong).append(conf)
                got_all[sc["id"]] = sig
                rows.append([m, sc["id"], sc["expected"], sig, f"{conf:.2f}", int(sc["hard"]), int(bad), why])
                if sig == "INVEST" and sc["expected"] == "HOLD":
                    print(f"  FALSE INVEST {sc['id']}: {why}")
        except Exception as exc:                       # not pulled, out of memory, ...
            print(f"  skipped: {exc}")
            continue
        gb = _loaded_gb(m)
        _unload(m)
        n_inv = sum(1 for s in SCENARIOS if s["expected"] == "INVEST")
        avg = lambda v: sum(v) / len(v) if v else float("nan")
        results.append(dict(model=m, acc=ok / len(SCENARIOS), inv=f"{inv_ok}/{n_inv}", false_inv=false_inv,
                            invalid=invalid, s=avg(secs), gb=gb, cr=avg(c_right), cw=avg(c_wrong)))
        answers[m] = got_all
    print("\n{:<20}{:>7}{:>10}{:>11}{:>9}{:>8}{:>7}{:>9}{:>9}".format(
        "model", "acc", "INVEST ok", "false INV", "invalid", "s/call", "GB", "conf ok", "conf bad"))
    for r in sorted(results, key=lambda r: (r["false_inv"], -r["acc"])):
        print("{:<20}{:>7.0%}{:>10}{:>11}{:>9}{:>8.1f}{:>7.1f}{:>9.2f}{:>9.2f}".format(
            r["model"], r["acc"], r["inv"], r["false_inv"], r["invalid"], r["s"], r["gb"], r["cr"], r["cw"]))
    n_hold = sum(1 for s in SCENARIOS if s["expected"] == "HOLD")
    print(f"\nBaseline: a model that ALWAYS says HOLD scores {n_hold / len(SCENARIOS):.0%} here "
          f"(0 of the {len(SCENARIOS) - n_hold} INVEST cases). A model is only better if it beats that.")
    _agreement(answers)
    with open("analyst_model_comparison.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["model", "scenario", "expected", "got", "confidence", "hard", "invalid", "justification"])
        w.writerows(rows)
    print("\nPer-scenario answers: analyst_model_comparison.csv")


def _agreement(answers: Dict[str, Dict[str, str]]) -> None:
    models = list(answers)
    if len(models) < 2:
        return
    ref = models[0]
    print(f"\nAgreement with {ref} (same inputs):")
    for m in models[1:]:
        ids = [i for i in answers[ref] if i in answers[m]]
        same = sum(answers[ref][i] == answers[m][i] for i in ids)
        inv_ref = sum(answers[ref][i] == "INVEST" for i in ids)
        inv_m = sum(answers[m][i] == "INVEST" for i in ids)
        print(f"  {m:<20} {same}/{len(ids)} same signal | INVEST {inv_m} vs {inv_ref} for {ref}")


# ---------------------------------------------------------------- saved data -----------------------
def _saved_inputs(tickers: Optional[List[str]], limit: int) -> List[Dict[str, Any]]:
    import pandas as pd
    if not tickers:
        files = sorted(glob.glob("data/processed/indicators/*_indicators.csv"))
        tickers = [os.path.basename(f).split("_indicators")[0] for f in files][:limit]
    out = []
    for t in tickers:
        path = f"data/processed/indicators/{t}_indicators.csv"
        if not os.path.exists(path):
            print(f"  {t}: no {path}, skipped")
            continue
        df = pd.read_csv(path, index_col=0)
        row = df.iloc[-1]
        try:
            close, sma, rsi = float(row["Close"]), float(row["SMA_10"]), float(row["RSI_14"])
        except (KeyError, ValueError):
            print(f"  {t}: needs Close, SMA_10, RSI_14 columns, skipped")
            continue
        if any(x != x for x in (close, sma, rsi)):             # NaN
            print(f"  {t}: latest row has NaN values, skipped")
            continue
        news, sent = [], 0.0
        npath = f"data/raw/news/{t}_news_scored.json"
        if os.path.exists(npath):
            try:
                with open(npath, encoding="utf-8") as f:
                    news = json.load(f) or []
                from src.data.score_sentiment import summarize_ticker_sentiment
                sent = float(summarize_ticker_sentiment(news).get("score", 0.0))
            except Exception as exc:
                print(f"  {t}: news file unreadable ({exc})")
        out.append(dict(ticker=t, state=_state(t, close, sma, rsi, sent, news), n_news=len(news)))
    return out


def run_saved(models: List[str], tickers: Optional[List[str]], limit: int) -> None:
    inputs = _saved_inputs(tickers, limit)
    if not inputs:
        sys.exit("No saved indicator files found under data/processed/indicators.")
    print(f"{len(inputs)} tickers: {', '.join(i['ticker'] for i in inputs)}")
    answers: Dict[str, Dict[str, str]] = {}
    for m in models:
        print(f"\n--- {m} ---", flush=True)
        got = {}
        try:
            for item in inputs:
                st = dict(item["state"])
                sig, conf, s, bad, why = _ask(m, st)
                got[item["ticker"]] = sig
                print(f"  {item['ticker']:<8}{sig:<8}{conf:.2f}  ({item['n_news']} articles, {s:.1f}s){'  INVALID' if bad else ''}\n           {why[:110]}")
        except Exception as exc:
            print(f"  skipped: {exc}")
            continue
        _unload(m)
        answers[m] = got
    print("\nINVEST rate:")
    for m, g in answers.items():
        print(f"  {m:<20} {sum(v == 'INVEST' for v in g.values())}/{len(g)}")
    _agreement(answers)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("models", nargs="*", help="first one is the reference model")
    p.add_argument("--saved", action="store_true", help="use saved indicator/news files, no labels")
    p.add_argument("--tickers", nargs="*")
    p.add_argument("--limit", type=int, default=20)
    a = p.parse_args()
    if A.ollama is None:
        sys.exit("pip install ollama")
    models = a.models or DEFAULT_MODELS
    run_saved(models, a.tickers, a.limit) if a.saved else run_scenarios(models)


if __name__ == "__main__":
    main()