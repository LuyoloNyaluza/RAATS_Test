# File: src/data/test_watchlist_manager_simple.py
"""
Simple test script for the watchlist manager core logic.
Tests the fundamental functions without requiring external APIs or heavy dependencies.
"""

import sys
import os

# Add the project root to path so we can import src modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.data.watchlist_manager import (
    aggregate_ticker_sentiment,
    generate_trading_lists,
    update_trading_lists
)


def test_aggregate_ticker_sentiment():
    """Test aggregating sentiment scores."""
    print("Testing aggregate_ticker_sentiment...")
    
    # Mock scored news data
    scored_news = {
        "AAPL": [
            {"sentiment": "positive", "confidence": 0.8},
            {"sentiment": "neutral", "confidence": 0.6},
            {"sentiment": "positive", "confidence": 0.9}
        ],
        "MSFT": [
            {"sentiment": "negative", "confidence": 0.7},
            {"sentiment": "negative", "confidence": 0.8}
        ],
        "GOOGL": [
            {"sentiment": "neutral", "confidence": 0.5}
        ],
        "TSLA": []  # No news
    }
    
    sentiment_scores = aggregate_ticker_sentiment(scored_news)
    
    assert isinstance(sentiment_scores, dict), "Should return a dictionary"
    assert set(sentiment_scores.keys()) == {"AAPL", "MSFT", "GOOGL", "TSLA"}, "Should have all tickers"
    
    # Check AAPL: (0.8*1 + 0.6*0 + 0.9*1) / 3 = (0.8 + 0 + 0.9) / 3 = 1.7/3 = 0.566...
    aapl_score = sentiment_scores["AAPL"]
    assert abs(aapl_score - 0.566) < 0.01, f"AAPL score should be ~0.566, got {aapl_score}"
    
    # Check MSFT: (-0.7*0.7 + -0.8*0.8) / 2 = (-0.49 - 0.64) / 2 = -1.13/2 = -0.565
    msft_score = sentiment_scores["MSFT"]
    assert abs(msft_score - (-0.565)) < 0.01, f"MSFT score should be ~-0.565, got {msft_score}"
    
    # Check GOOGL: (0.5*0) / 1 = 0
    goog_score = sentiment_scores["GOOGL"]
    assert abs(goog_score - 0.0) < 0.01, f"GOOGL score should be 0.0, got {goog_score}"
    
    # Check TSLA: empty list should be 0
    tsla_score = sentiment_scores["TSLA"]
    assert abs(tsla_score - 0.0) < 0.01, f"TSLA score should be 0.0, got {tsla_score}"
    
    print("✓ aggregate_ticker_sentiment test passed")
    return sentiment_scores


def test_generate_trading_lists(sentiment_scores):
    """Test generating trading lists from sentiment scores."""
    print("Testing generate_trading_lists...")
    
    active_list, waitlist = generate_trading_lists(
        sentiment_scores=sentiment_scores,
        top_n=2,
        waitlist_n=2
    )
    
    assert isinstance(active_list, list), "Active list should be a list"
    assert isinstance(waitlist, list), "Waitlist should be a list"
    assert len(active_list) <= 2, "Active list should not exceed top_n"
    assert len(waitlist) <= 2, "Waitlist should not exceed waitlist_n"
    
    # Check that there's no overlap between lists
    active_set = set(active_list)
    waitlist_set = set(waitlist)
    assert len(active_set & waitlist_set) == 0, "Active and waitlist should not overlap"
    
    # With our test data, AAPL (~0.566) and GOOGL (0.0) should be top 2
    # MSFT (~-0.565) and TSLA (0.0) should be next
    # Actually wait - GOOGL and TSLA both have 0.0, so ordering might vary
    # Let's just check that the active list contains the highest scorers
    sorted_by_score = sorted(sentiment_scores.items(), key=lambda x: x[1], reverse=True)
    top_two_tickers = [ticker for ticker, score in sorted_by_score[:2]]
    
    # Both top tickers should be in active list (order might vary)
    for ticker in top_two_tickers:
        assert ticker in active_list, f"Top ticker {ticker} should be in active list"
    
    print("✓ generate_trading_lists test passed")
    return active_list, waitlist


def test_update_trading_lists(active_list, waitlist, sentiment_scores, all_tickers):
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
            all_tickers=all_tickers,
            sentiment_scores=sentiment_scores,
            top_n=len(original_active),
            waitlist_n=len(original_waitlist)
        )
        
        # Check that closed position is removed from active list
        assert closed_positions[0] not in updated_active, "Closed position should be removed from active list"
        # Check that we maintained reasonable list sizes
        assert len(updated_active) >= len(original_active) - 1, "Active list should not lose more than one position"
        assert len(updated_waitlist) >= len(original_waitlist), "Waitlist should not lose positions"
        
        print("✓ update_trading_lists test passed")
    else:
        print("⚠ update_trading_lists test skipped (no active positions)")


def main():
    """Run all tests."""
    print("=" * 60)
    print("WATCHLIST MANAGER SIMPLE LOGIC TESTS")
    print("=" * 60)
    
    try:
        # Test data
        test_tickers = ["AAPL", "MSFT", "GOOGL", "TSLA", "AMZN", "META"]
        
        # Run tests in sequence
        sentiment_scores = test_aggregate_ticker_sentiment()
        active_list, waitlist = test_generate_trading_lists(sentiment_scores)
        test_update_trading_lists(active_list, waitlist, sentiment_scores, test_tickers)
        
        print("\n" + "=" * 60)
        print("ALL TESTS PASSED! ✓")
        print("=" * 60)
        
        # Show sample results
        print(f"\nSample results:")
        print(f"Sentiment scores: { {k: round(v, 3) for k, v in sentiment_scores.items()} }")
        print(f"Active list: {active_list}")
        print(f"Waiting list: {waitlist}")
        
        # Show ranking
        sorted_scores = sorted(sentiment_scores.items(), key=lambda x: x[1], reverse=True)
        print("Ranked by sentiment:")
        for i, (ticker, score) in enumerate(sorted_scores):
            print(f"  {i+1}. {ticker}: {score:.3f}")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())