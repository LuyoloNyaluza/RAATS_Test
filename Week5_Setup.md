# Week 5 Setup - Technical Indicators & Market Data Collection

**Goal:** Collect historical price data, calculate technical indicators (SMA, EMA, RSI, MACD), and store the results for later use in trading strategies.

## Prerequisites
- Completed Week 4 setup (NLP pipeline, sentiment analysis, visualizations)
- Python virtual environment activated (`source venv/Scripts/activate` or `source RAATS_Test.venv/Scripts/activate`)
- Required packages installed: yfinance, pandas-ta, matplotlib, seaborn (install as needed)
- Ollama with llama3 model running (optional, for any LLM components in later weeks)
- Basic understanding of pandas and Jupyter notebooks

## Daily Activities with Runnable Code Snippets

---

### Monday 31 Aug – Market data acquisition with yfinance
**Goal:** Download OHLCV data for a watchlist and save as CSV.

```bash
# 1. Ensure you are in the RAATS_Test project root
cd /c/Users/Zamuxolo/RAATS_Test
```

```bash
# 2. Activate virtual environment (if not already)
source venv/Scripts/activate
```

```bash
# 3. Install yfinance if needed
pip install yfinance
```

```python
# File: notebooks/09_market_data_download.ipynb
# In[1]: Import libraries
import yfinance as yf
import pandas as pd
import os

# In[2]: Define watchlist and period
watchlist = ['AAPL', 'MSFT', 'TSLA', 'GOOG']
end_date = pd.Timestamp.now()
start_date = end_date - pd.DateOffset(months=6)

# In[3]: Download data for each ticker and save individually
os.makedirs('data/raw/prices', exist_ok=True)
for ticker in watchlist:
    print(f'Downloading {ticker}...')
    data = yf.download(ticker, start=start_date, end=end_date)
    data.to_csv(f'data/raw/prices/{ticker}_ohlcv.csv')
    print(f'Saved {ticker} data to data/raw/prices/{ticker}_ohlcv.csv')
```

```bash
# 4. To run the notebook, execute:
jupyter notebook notebooks/09_market_data_download.ipynb
```

*Output:* CSV files for each ticker in `data/raw/prices/` and a notebook demonstrating download and a quick plot of closing prices.

---

### Tuesday 1 Sep – Technical indicators with pandas-ta
**Goal:** Calculate SMA, EMA, RSI, MACD for each ticker and append as new columns.

```bash
# 1. Install pandas-ta if needed
pip install pandas-ta
```

```python
# File: notebooks/10_technical_indicators.ipynb
# In[1]: Import libraries
import pandas as pd
import os

# In[2]: Load raw price data for a ticker (example AAPL)
ticker = 'AAPL'
df = pd.read_csv(f'data/raw/prices/{ticker}_ohlcv.csv', index_col=0, parse_dates=True)

# In[3]: Calculate technical indicators using pandas-ta
df.ta.sma(length=10, append=True)
df.ta.sma(length=20, append=True)
df.ta.sma(length=50, append=True)
df.ta.ema(length=10, append=True)
df.ta.ema(length=20, append=True)
df.ta.ema(length=50, append=True)
df.ta.rsi(length=14, append=True)
df.ta.macd(fast=12, slow=26, signal=9, append=True)

# In[4]: Save the enriched data
os.makedirs('data/processed/indicators', exist_ok=True)
df.to_csv(f'data/processed/indicators/{ticker}_indicators.csv')
print(f'Saved {ticker} with indicators to data/processed/indicators/{ticker}_indicators.csv')
```

```bash
# 5. To run the notebook, execute:
jupyter notebook notebooks/10_technical_indicators.ipynb
```

*Output:* Notebook showing calculation and plots of price with SMA/EMA and RSI/MACD panels; enriched CSV files in `data/processed/indicators/`.

---

### Wednesday 2 Sep – Storing indicator data
**Goal:** Save enriched DataFrames as CSV (we'll keep CSV for simplicity).

```python
# File: src/data/process_market_data.py
import pandas as pd
import os
import yfinance as yf

def fetch_price_data(tickers, start, end):
    """Download OHLCV data for given tickers and date range."""
    data_dict = {}
    for ticker in tickers:
        print(f'Fetching {ticker}...')
        data = yf.download(ticker, start=start, end=end)
        data_dict[ticker] = data
    return data_dict

def add_technical_indicators(df):
    """Add SMA, EMA, RSI, MACD indicators to DataFrame."""
    df.ta.sma(length=10, append=True)
    df.ta.sma(length=20, append=True)
    df.ta.sma(length=50, append=True)
    df.ta.ema(length=10, append=True)
    df.ta.ema(length=20, append=True)
    df.ta.ema(length=50, append=True)
    df.ta.rsi(length=14, append=True)
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    return df

def save_data(data_dict, base_dir):
    """Save each ticker's DataFrame as CSV in base_dir/prices and base_dir/indicators."""
    prices_dir = os.path.join(base_dir, 'raw', 'prices')
    indicators_dir = os.path.join(base_dir, 'processed', 'indicators')
    os.makedirs(prices_dir, exist_ok=True)
    os.makedirs(indicators_dir, exist_ok=True)
    
    for ticker, df in data_dict.items():
        # Save raw data
        df.to_csv(os.path.join(prices_dir, f'{ticker}_ohlcv.csv'))
        # Add indicators and save processed data
        df_with_indicators = add_technical_indicators(df.copy())
        df_with_indicators.to_csv(os.path.join(indicators_dir, f'{ticker}_indicators.csv'))
        print(f'Saved {ticker} data to {prices_dir} and {indicators_dir}')

if __name__ == '__main__':
    # Example usage
    watchlist = ['AAPL', 'MSFT', 'TSLA', 'GOOG']
    end = pd.Timestamp.now()
    start = end - pd.DateOffset(months=6)
    data = fetch_price_data(watchlist, start, end)
    save_data(data, 'data')
```

```bash
# 6. To run the script:
python src/data/process_market_data.py
```

*Output:* A set of CSV files ready for use: raw OHLCV in `data/raw/prices/` and indicators in `data/processed/indicators/`.

---

### Thursday 3 Sep – Building a reusable data pipeline
**Goal:** Combine download and indicator steps into a single module and write a test.

```python
# File: src/data/market_data.py
import pandas as pd
import yfinance as yf
import os

def fetch_price_data(tickers, start, end):
    """Fetch OHLCV data for tickers."""
    data_dict = {}
    for ticker in tickers:
        data = yf.download(ticker, start=start, end=end)
        data_dict[ticker] = data
    return data_dict

def add_technical_indicators(df):
    """Add technical indicators to DataFrame."""
    df.ta.sma(length=10, append=True)
    df.ta.sma(length=20, append=True)
    df.ta.sma(length=50, append=True)
    df.ta.ema(length=10, append=True)
    df.ta.ema(length=20, append=True)
    df.ta.ema(length=50, append=True)
    df.ta.rsi(length=14, append=True)
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    return df

def save_data(data_dict, base_dir):
    """Save raw and processed data."""
    raw_dir = os.path.join(base_dir, 'raw', 'prices')
    proc_dir = os.path.join(base_dir, 'processed', 'indicators')
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(proc_dir, exist_ok=True)
    
    for ticker, df in data_dict.items():
        df.to_csv(os.path.join(raw_dir, f'{ticker}_ohlcv.csv'))
        df_with_ind = add_technical_indicators(df.copy())
        df_with_ind.to_csv(os.path.join(proc_dir, f'{ticker}_indicators.csv'))
```

```python
# File: notebooks/11_data_pipeline_test.ipynb
# In[1]: Import the module
import sys
sys.path.append('src')
from data.market_data import fetch_price_data, add_technical_indicators, save_data
import pandas as pd

# In[2]: Define parameters
tickers = ['AAPL']
end = pd.Timestamp.now()
start = end - pd.DateOffset(months=1)  # shorter for test

# In[3]: Fetch data
data_dict = fetch_price_data(tickers, start, end)
print(f'Fetched {len(data_dict)} ticker(s)')

# In[4]: Test add_technical_indicators on one ticker
ticker = tickers[0]
df = data_dict[ticker]
df_with_ind = add_technical_indicators(df.copy())
print('Original columns:', df.columns.tolist())
print('With indicators columns:', df_with_ind.columns.tolist())
print('Indicator columns added:', [c for c in df_with_ind.columns if c not in df.columns])

# In[5]: Test save_data (optional, will write to test directory)
test_dir = 'test_pipeline_output'
os.makedirs(test_dir, exist_ok=True)
save_data(data_dict, test_dir)
print(f'Test data saved to {test_dir}')
```

```bash
# 7. To run the notebook, execute:
jupyter notebook notebooks/11_data_pipeline_test.ipynb
```

*Output:* The module `src/data/market_data.py` and a test notebook validating output columns.

---

### Friday 4 Sep – Morning: Strategy prototype (simple moving average crossover)
**Goal:** Implement SMA crossover strategy and calculate returns.

```python
# File: notebooks/12_sma_strategy.ipynb
# In[1]: Import libraries
import pandas as pd
import os
import matplotlib.pyplot as plt

# In[2]: Load processed indicator data for a ticker
ticker = 'AAPL'
df = pd.read_csv(f'data/processed/indicators/{ticker}_indicators.csv', index_col=0, parse_dates=True)

# In[3]: Generate SMA crossover signals (short=10, long=50)
df['signal'] = 0
df['signal'][10:] = (df['SMA_10'][10:] > df['SMA_50'][10:]).astype(int)
df['position'] = df['signal'].diff()

# In[4]: Calculate daily returns
df['returns'] = df['Close'].pct_change()
df['strategy_returns'] = df['position'].shift(1) * df['returns']

# In[5]: Compute cumulative returns
df['cum_returns'] = (1 + df['returns']).cumprod()
df['cum_strategy_returns'] = (1 + df['strategy_returns']).cumprod()

# In[6]: Plot equity curves
plt.figure(figsize=(12,6))
plt.plot(df['cum_returns'], label='Buy and Hold')
plt.plot(df['cum_strategy_returns'], label='SMA Crossover Strategy')
plt.title(f'{ticker} Strategy Equity Curve')
plt.xlabel('Date')
plt.ylabel('Cumulative Returns')
plt.legend()
plt.grid(True)
plt.show()
```

```bash
# 8. To run the notebook, execute:
jupyter notebook notebooks/12_sma_strategy.ipynb
```

*Output:* Notebook showing equity curves for each ticker (you can loop over watchlist).

*Afternoon:* Rest (no work).

---

### Saturday 5 Sep – Rest day
- No planned work.

---

### Sunday 6 Sep – Preparation for Week 6
**Goal:** Review Week 6 plan and sketch architecture.

```bash
# 1. Create journal directory if not exists
mkdir -p journal
```

```markdown
# File: journal/week5_prep_week6.md
## Week 6 Preparation Notes

**Topic:** Agentic AI concepts and LangGraph.

**High-level architecture ideas:**
- Data pipeline (from Week 5) feeds processed data to a storage layer (e.g., PostgreSQL or CSV).
- LLM strategy selector (using Ollama/LangChain) analyzes indicators and news sentiment to generate trading signals.
- Execution agent receives signals and simulates trades (or connects to a brokerage API via paper trading).
- Feedback loop: trade results stored and used to retrain/refine strategy selector.

**Components:**
1. Data ingestion & processing (market_data.py)
2. Feature store (CSV/DB)
3. Strategy selector (LLM + prompt template)
4. Execution agent (simulator or API connector)
5. Performance tracker & journal

**Next steps:** Explore LangGraph documentation and prototype a simple agent loop.
```

```bash
# 2. To create the file, you can use:
cat > journal/week5_prep_week6.md << 'EOF'
# Week 6 Preparation Notes

## Topic: Agentic AI concepts and LangGraph.

## High-level architecture ideas:
- Data pipeline (from Week 5) feeds processed data to a storage layer (e.g., PostgreSQL or CSV).
- LLM strategy selector (using Ollama/LangChain) analyzes indicators and news sentiment to generate trading signals.
- Execution agent receives signals and simulates trades (or connects to a brokerage API via paper trading).
- Feedback loop: trade results stored and used to retrain/refine strategy selector.

## Components:
1. Data ingestion & processing (market_data.py)
2. Feature store (CSV/DB)
3. Strategy selector (LLM + prompt template)
4. Execution agent (simulator or API connector)
5. Performance tracker & journal

## Next steps: Explore LangGraph documentation and prototype a simple agent loop.
EOF
```

```bash
# 3. Commit any notes or small scripts:
git add journal/week5_prep_week6.md
git commit -m "Add Week 6 preparation note"
git push origin dev
```

*Output:* A brief note in journal/week5_prep_week6.md about your ideas.

---

## End of Week 5 Deliverables
- Notebooks: `notebooks/09_market_data_download.ipynb`, `notebooks/10_technical_indicators.ipynb`, `notebooks/11_data_pipeline_test.ipynb`, `notebooks/12_sma_strategy.ipynb`
- Module: `src/data/market_data.py`
- Data: `data/raw/prices/*.csv` (OHLCV), `data/processed/indicators/*_indicators.csv`
- Logs: `journal/week5_log.md` (optional, you can create a daily log), `journal/week5_prep_week6.md`

---
*Created as part of Weekly Setup Instructions. Includes runnable code snippets for direct execution as requested.*