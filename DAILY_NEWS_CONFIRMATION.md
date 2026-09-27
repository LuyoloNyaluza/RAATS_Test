## Confirmation: Daily News Loading

### ✅ **YES, NEWS ARE LOADED FRESH EACH DAY**

The dynamic watchlist system **loads new news every time it runs**, ensuring you get today's news for your ticker array.

### **How It Works:**

1. **`fetch_universe_news()` function** (lines 21-55 in `watchlist_manager.py`):
   - Called every time `get_top_tickers_by_sentiment()` is invoked
   - Makes fresh HTTP requests to Google News RSS for each ticker
   - No caching - gets current news each execution

2. **Underlying news fetch** (`src/data/fetch_news.py`):
   - `fetch_financial_news()` constructs real-time Google News RSS URLs
   - `feedparser.parse(url)` fetches live data from Google
   - Returns current day's news headlines

3. **Typical Usage Pattern**:
   ```python
   # Pre-market call - gets TODAY'S news
   active_list, waitlist, scores = get_top_tickers_by_sentiment(
       tickers=your_50_100_ticker_universe,
       top_n=10,
       waitlist_n=10
   )
   
   # Throughout trading day - when positions close:
   active_list, waitlist = update_trading_lists(
       closed_positions=[closed_ticker],
       current_active=active_list,
       current_waitlist=waitlist,
       all_tickers=your_50_100_ticker_universe,
       sentiment_scores=scores,  # Reuse same day's scores or refresh as needed
       top_n=10,
       waitlist_n=10
   )
   ```

### **Key Points:**
- **Fresh data every call**: Each execution gets current news from Google News
- **No stale data**: System doesn't cache or reuse old news
- **Daily reset**: For true daily refresh, call `get_top_tickers_by_sentiment()` each morning
- **Intraday updates**: You can refresh sentiment scores during day by re-running the fetch/score cycle

### **Verification:**
The `fetch_financial_news()` function in `src/data/fetch_news.py`:
- Makes real HTTP requests to: `https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en`
- Parses the live RSS response
- Returns current articles with `publishedAt` timestamps
- Has no caching mechanism - fresh data every call

**Conclusion**: Yes, the system loads new news for the day each time the watchlist generation function is called, providing you with current market sentiment for your ticker array.