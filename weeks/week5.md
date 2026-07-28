# Week 5: Technical Indicators & Market Data Collection
**Goal:** Collect historical price data, calculate technical indicators (SMA, EMA, RSI, MACD), and store the results in a PostgreSQL database for later use.

## Monday 31 Aug – Setting up PostgreSQL with Docker
- Pull the PostgreSQL Docker image: `docker pull postgres`
- Run a container with a known password and port:  
  ```
  docker run --name pgdb -e POSTGRES_PASSWORD=postgres -p 5432:5432 -d postgres
  ```
- Wait a few seconds, then connect to verify:  
  ```
  docker exec -it pgdb psql -U postgres -c "SELECT version();"
  ```
- Create a database for the project:  
  ```
  docker exec -it pgdb psql -U postgres -c "CREATE DATABASE raats;"
  ```
- Exit the psql shell (`\q`).

## Tuesday 1 Sep – Installing Python libraries and basic data fetch
- Ensure yfinance and pandas-ta are installed (they are in requirements).  
- Write a script `src/data/fetch_price_data.py` that downloads OHLCV data for a watchlist (e.g., AAPL, MSFT, TSLA, GOOGL, AMZN) for the last 6 months using yfinance.  
- Save the raw data as CSV files in `data/raw/prices/`.  
- Test the script for one ticker and confirm the CSV has columns: Open, High, Low, Close, Adj Close, Volume.

## Wednesday 2 Sep – Calculating technical indicators with pandas-ta
- In a notebook `notebooks/08_technical_indicators.ipynb`, load one of the CSV files (e.g., AAPL).  
- Use pandas-ta to calculate:  
  - SMA (20, 50)  
  - EMA (20, 50)  
  - RSI (14)  
  - MACD (12,26,9)  
- Plot the close price along with SMA and EMA using matplotlib.  
- Add the indicators as new columns to the DataFrame.

## Thursday 3 Sep – Storing data in PostgreSQL
- Install psycopg2-binary if not already present (add to requirements if needed).  
- Write a script `src/data/store_price_data.py` that:  
  1. Reads each CSV from `data/raw/prices/`.  
  2. Adds the technical indicator columns (using pandas-ta).  
  3. Connects to the PostgreSQL database (host=localhost, port=5432, dbname=raats, user=postgres, password=postgres).  
  4. Creates a table per ticker (if not exists) with columns: date, open, high, low, close, adj_close, volume, sma_20, sma_50, ema_20, ema_50, rsi_14, macd, macd_signal, macd_hist.  
  5. Inserts the rows (use `to_sql` with `if_exists='append'`).  
- Test the script for one ticker and verify the rows appear in the database via a quick query.

## Friday 4 Sep – Morning: Automating the pipeline
- Combine the fetch and store steps into a single script `src/data/update_market_data.py` that:  
  - Downloads fresh data (or updates existing).  
  - Calculates indicators.  
  - Upserts into PostgreSQL (you can use `ON CONFLICT DO UPDATE` for simplicity, or just truncate and reload for this exercise).  
- Run the script for the full watchlist and log the number of rows inserted.  
- Afternoon: Rest (no work).

## Saturday 5 Sep – Rest day
- No planned work.

## Sunday 6 Sep – Preparation for Week 6
- Review the basics of LangGraph (Agentic AI) from the week 6 plan.  
- Install any missing packages (langgraph).  
- Write a brief note in `journal/week5_prep_week6.md` about what you plan to build: a simple agent graph that fetches data, analyzes sentiment, and makes a trading decision.  
- Commit any notes or scripts.

---
**End of Week 5 Deliverables:**
- Docker PostgreSQL container running with database `raats`.
- Scripts: `src/data/fetch_price_data.py`, `src/data/store_price_data.py`, `src/data/update_market_data.py`.
- Notebook: `notebooks/08_technical_indicators.ipynb`.
- Data: Raw price CSVs in `data/raw/prices/`, processed data stored in PostgreSQL.
- Logs: `journal/week5_log.md`, `journal/week5_prep_week6.md`.