 # Example spaCy NER test for financial entities
import spacy
   
   # Load English model
nlp = spacy.load("en_core_web_sm")
   
   # Sample financial headlines
headlines = [
       "Apple Inc. (AAPL) shares rise after strong iPhone sales",
       "Microsoft Corporation (MSFT) announces Azure growth acceleration",
       "Tesla, Inc. (TSLA) delivers record vehicles in Q3",
       "Amazon.com, Inc. (AMZN) faces antitrust investigation in EU",
       "Alphabet Inc. (GOOGL) reports strong ad revenue growth"
   ]
   
print("Financial Entity Recognition with spaCy:")
print("=" * 60)
for headline in headlines:
       doc = nlp(headline)
       entities = [(ent.text, ent.label_) for ent in doc.ents]
       
       print(f"\nHeadline: {headline}")
       print("Entities found:")
       if entities:
           for text, label in entities:
               print(f"  - {text} ({label})")
       else:
           print("  No named entities detected")