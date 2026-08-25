import spacy

# Load English model
nlp = spacy.load("en_core_web_sm")

# Sample financial headlines
headlines = [
    "Apple Inc. (AAPL) shares rise after strong iPhone sales",
    "Federal Reserve hints at possible interest rate cuts",
    "Crude oil prices drop 3% on oversupply concerns",
    "Tesla delivers record vehicles in Q3, stock up 5%"
]

print("spaCy Basic Pipeline Test:")
print("=" * 50)
for i, headline in enumerate(headlines, 1):
    doc = nlp(headline)
    
    print(f"\n{i}. Headline: {headline}")
    print("   Tokens:", [token.text for token in doc[:5]], "..." if len(doc) > 5 else "")
    print("   POS Tags:", [(token.text, token.pos_) for token in doc[:5]])
    print("   Entities:", [(ent.text, ent.label_) for ent in doc.ents])