# Week 5: Technical Indicators & Market Data Collection
**Goal:** Collect historical price data, calculate technical indicators (SMA, EMA, RSI, MACD), and store the results for later use in trading strategies.

## Monday 31 Aug – Market data acquisition with yfinance
- Review yfinance documentation: https://pypi.org/project/yfinance/
- Write a script that downloads OHLCV data for a watchlist (e.g., AAPL, MSFT, TSLA, GOOG) for the last 6 months.
- Save each ticker's data as a CSV in data/raw/prices/ (or a single combined file with a ticker column).
- Output: Notebook 09_market_data_download.ipynb demonstrating the download and a quick plot of closing prices.

## Tuesday 1 Sep – Technical indicators with pandas-ta
- Review pandas-ta documentation: https://github.com/twopirllc/pandas-ta
- For each ticker's DataFrame, calculate:
  - Simple Moving Average (SMA) for windows 10, 20, 50
  - Exponential Moving Average (EMA) for windows 10, 20, 50
  - Relative Strength Index (RSI) length 14
  - Moving Average Convergence Divergence (MACD) (default fast=12, slow=26, signal=9)
- Append these indicators as new columns.
- Output: Notebook 10_technical_indicators.ipynb showing the calculation and a plot of price with SMA/EMA and RSI/MACD panels.

## Wednesday 2 Sep – Storing indicator data
- Decide on a storage format: either keep the enriched DataFrames as CSV (with all indicator columns) or move to a relational database (PostgreSQL via Docker) for more complex queries.
- For simplicity, we'll store as CSV in data/processed/indicators/ with filename like AAPL_indicators.csv.
- Write a function that loads the raw price data, adds indicators, and saves the processed file.
- Process all tickers in the watchlist.
- Output: A set of CSV files ready for use in later weeks.

## Thursday 3 Sep – Building a reusable data pipeline
- Combine the download and indicator steps into a single module: src/data/market_data.py.
- Provide functions:
    - fetch_price_data(tickers, start, end) -> dict of DataFrames
    - add_technical_indicators(df) -> DataFrame with indicators
    - save_data(data_dict, base_dir)
- Write a small test script that runs the pipeline for a single ticker and validates the output columns.
- Output: The module and a test notebook 11_data_pipeline_test.ipynb.

## Friday 4 Sep – Morning: Strategy prototype (simple moving average crossover)
- Using the processed data, implement a basic trading signal: when short SMA crosses above long SMA -> buy, cross below -> sell.
- Generate signals for each ticker and calculate simple returns (assuming daily rebalancing).
- Output: Notebook 12_sma_strategy.ipynb showing equity curves for each ticker.
- Afternoon: Rest (no work) – enjoy the break.

## Saturday 5 Sep – Rest day
- No planned work.

## Sunday 6 Sep – Preparation for Week 6
- Review the plan for week6: Agentic AI concepts and LangGraph.
- Sketch a high-level architecture of how the data pipeline, LLM strategy selector, and execution agent will interact.
- Write a brief note in journal/week5_prep_week6.md about your ideas.
- Commit any notes or small scripts.

---
**End of Week 5 Deliverables:**
- Notebooks: 09_market_data_download.ipynb, 10_technical_indicators.ipynb, 11_data_pipeline_test.ipynb, 12_sma_strategy.ipynb
- Module: src/data/market_data.py
- Data: data/raw/prices/*.csv (OHLCV), data/processed/indicators/*_indicators.csv
- Logs: journal/week5_log.md, journal/week5_prep_week6.md