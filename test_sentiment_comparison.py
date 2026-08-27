from textblob import TextBlob
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# Initialize analyzers
vader = SentimentIntensityAnalyzer()

# Sample financial headlines
headlines = [
    "Apple shares surge after record iPhone sales",
    "Stock market crashes amid recession fears",
    "Tesla reports quarterly loss, stock down 8%",
    "Federal Reserve keeps interest rates unchanged",
    "Amazon beats earnings expectations"
]

print("Sentiment Analysis Comparison (VADER vs TextBlob):")
print("=" * 60)
for headline in headlines:
    vader_scores = vader.polarity_scores(headline)
    vader_compound = vader_scores['compound']
    vader_label = "POSITIVE" if vader_compound >= 0.05 else "NEGATIVE" if vader_compound <= -0.05 else "NEUTRAL"

    blob = TextBlob(headline)
    tb_polarity = blob.sentiment.polarity  # type: ignore[reportAttributeAccessIssue]
    tb_label = "POSITIVE" if tb_polarity > 0 else "NEGATIVE" if tb_polarity < 0 else "NEUTRAL"

    print(f"\nHeadline: {headline}")
    print(f"  VADER:   compound={vader_compound:+.3f} ({vader_label})")
    print(f"  TextBlob: polarity={tb_polarity:+.3f} ({tb_label})")