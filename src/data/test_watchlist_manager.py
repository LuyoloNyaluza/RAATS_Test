# File: src/data/test_watchlist_manager.py
"""
Test script for the watchlist manager module.
"""

import sys
import os

# Add src to path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.data.watchlist_manager import (
    fetch_universe_news,
    score_universe_sentiment,
    aggregate_ticker_sentiment,
    generate_trading_lists,
    update_trading_lists,
    get_top_tickers_by_sentiment
)


def test_fetch_universe_news():
    """Test fetching news for a small universe."""
    print("Testing fetch_universe_news...")
    test_tickers = ["AAPL", "MSFT"]  # Small set for quick test
    news_data = fetch_universe_news(
        tickers=test_tickers,
        max_articles_per_ticker=2,
        pause=1.0
    )
    
    assert isinstance(news_data, dict), "Should return a dictionary"
    assert len(news_data) == len(test_tickers), "Should have data for each ticker"
    for ticker in test_tickers:
        assert ticker in news_data, f"Should have data for {ticker}"
        assert isinstance(news_data[ticker], list), f"News for {ticker} should be a list"
    
    print("✓ fetch_universe_news test passed")
    return news_data


def test_score_universe_sentiment(news_data):
    """Test scoring sentiment for news data."""
    print("Testing score_universe_sentiment...")
    scored_data = score_universe_sentiment(
        news_data=news_data,
        model_name="mistral"  # Make sure this model is available
    )
    
    assert isinstance(scored_data, dict), "Should return a dictionary"
    assert set(scored_data.keys()) == set(news_data.keys()), "Should have same tickers"
    
    print("✓ score_universe_sentiment test passed")
    return scored_data


def test_aggregate_ticker_sentiment(scored_data):
    """Test aggregating sentiment scores."""
    print("Testing aggregate_ticker_sentiment...")
    sentiment_scores = aggregate_ticker_sentiment(scored_data)
    
    assert isinstance(sentiment_scores, dict), "Should return a dictionary"
    assert set(sentiment_scores.keys()) == set(scored_data.keys()), "Should have same tickers"
    for score in sentiment_scores.values():
        assert isinstance(score, (int, float)), "Score should be numeric"
        assert -1.0 <= score <= 1.0, "Score should be between -1 and 1"
    
    print("✓ aggregate_ticker_sentiment test passed")
    return sentiment_scores


def test_generate_trading_lists(sentiment_scores):
    """Test generating trading lists from sentiment scores."""
    print("Testing generate_trading_lists...")
    active_list, waitlist = generate_trading_lists(
        sentiment_scores=sentiment_scores,
        top_n=3,
        waitlist_n=3
    )
    
    assert isinstance(active_list, list), "Active list should be a list"
    assert isinstance(waitlist, list), "Waitlist should be a list"
    assert len(active_list) <= 3, "Active list should not exceed top_n"
    assert len(waitlist) <= 3, "Waitlist should not exceed waitlist_n"
    
    # Check that there's no overlap between lists
    active_set = set(active_list)
    waitlist_set = set(waitlist)
    assert len(active_set & waitlist_set) == 0, "Active and waitlist should not overlap"
    
    print("✓ generate_trading_lists test passed")
    return active_list, waitlist


def test_update_trading_lists(active_list, waitlist, sentiment_scores, test_tickers):
    """Test updating trading lists when positions close."""
    print("Testing update_trading_lists...")
    
    # Simulate closing the first position in active list
    if active_list:
        closed_positions = [active_list[0]]
        original_active = active_list.copy()
        original_waitlist = waitlist.copy()
        
        updated_active, updated_waitlist = update_trading_lists(
            closed_positions=closed_positions,
            current_active=active_list,
            current_waitlist=waitlist,
            all_tickers=test_tickers,
            sentiment_scores=sentiment_scores,
            top_n=len(original_active),
            waitlist_n=len(original_waitlist)
        )
        
        # Check that closed position is removed from active list
        assert closed_positions[0] not in updated_active, "Closed position should be removed from active list"
        # Check that active list size is maintained (if possible)
        assert len(updated_active) == len(original_active) - 1 or len(updated_active) == len(original_active), \
            "Active list size should decrease by 1 or stay same if waitlist fills it"
        
        print("✓ update_trading_lists test passed")
    else:
        print("⚠ update_trading_lists test skipped (no active positions)")


def main():
    """Run all tests."""
    print("=" * 60)
    print("WATCHLIST MANAGER MODULE TESTS")
    print("=" * 60)
    
    try:
        # Run tests in sequence
        test_tickers = ["AAPL", "MSFT", "GOOGL", "TSLA", "META"]  # Small test set
        
        news_data = test_fetch_universe_news()
        scored_data = test_score_universe_sentiment(news_data)
        sentiment_scores = test_aggregate_ticker_sentiment(scored_data)
        active_list, waitlist = test_generate_trading_lists(sentiment_scores)
        test_update_trading_lists(active_list, waitlist, sentiment_scores, test_tickers)
        
        print("\n" + "=" * 60)
        print("ALL TESTS PASSED! ✓")
        print("=" * 60)
        
        # Show sample results
        print(f"\nSample results for {len(test_tickers)} tickers:")
        print(f"Active list: {active_list}")
        print(f"Waiting list: {waitlist}")
        
        # Show top 3 scores
        sorted_scores = sorted(sentiment_scores.items(), key=lambda x: x[1], reverse=True)
        print("Top 3 sentiment scores:")
        for ticker, score in sorted_scores[:3]:
            print(f"  {ticker}: {score:.3f}")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())