import ast
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from collections import Counter
 
# Load enriched data from Thursday's pipeline
df = pd.read_csv("data/processed/news_enriched_week4.csv")
 
# Set style
plt.style.use('seaborn-v0_8')
sns.set_palette("husl")
 
# 1. Sentiment distribution (VADER)
plt.figure(figsize=(10, 5))
plt.subplot(1, 2, 1)
vader_counts = df['vader.label'].value_counts()
sns.barplot(x=vader_counts.index, y=vader_counts.values, hue=vader_counts.index, legend=False)
plt.title('VADER Sentiment Distribution')
plt.ylabel('Count')
 
plt.subplot(1, 2, 2)
tb_counts = df['textblob.label'].value_counts()
sns.barplot(x=tb_counts.index, y=tb_counts.values, hue=tb_counts.index, legend=False)
plt.title('TextBlob Sentiment Distribution')
plt.ylabel('Count')
plt.tight_layout()
plt.savefig('sentiment_distribution.png')
plt.show()
 
# 2. Top 10 most mentioned organizations (ORG entities)
all_entities = []
for entities_str in df['entities']:
    try:
        entities_list = ast.literal_eval(entities_str) if isinstance(entities_str, str) else entities_str
        all_entities.extend([text for text, label in entities_list if label == 'ORG'])
    except (ValueError, SyntaxError):
        pass  # Skip rows where the entities column can't be parsed
 
entity_counts = Counter(all_entities)
top_10 = entity_counts.most_common(10)
 
plt.figure(figsize=(10, 6))
entities, counts = zip(*top_10) if top_10 else ([], [])
sns.barplot(x=list(counts), y=list(entities), hue=list(entities), legend=False)
plt.title('Top 10 Organizations Mentioned (ORG entities only)')
plt.xlabel('Frequency')
plt.tight_layout()
plt.savefig('top_entities.png')
plt.show()
 
print("Visualizations saved as sentiment_distribution.png and top_entities.png")