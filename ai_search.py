import pandas as pd
from sentence_transformers import SentenceTransformer, util
import warnings

warnings.filterwarnings('ignore')

df = pd.read_csv('nlp_dataset.csv', sep=';')

df = df.dropna(subset=['bio'])
df = df.reset_index(drop=True)
print(f" В базе {len(df)} профилей с заполненным описанием.")

print("\nЗагрука ии модели")
model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')

corpus_embeddings = model.encode(df['bio'].astype(str).tolist(), convert_to_tensor=True)

print("\n AI готов")
print("="*50)

while True:
    query = input("\nзапрос: ")
    if query.lower() == 'exit':
        break
        
    if not query.strip():
        continue

    query_embedding = model.encode(query, convert_to_tensor=True)

    hits = util.semantic_search(query_embedding, corpus_embeddings, top_k=5)[0]

    print("\n--- РЕЗУЛЬТАТЫ ПОИСКА ---")
    for hit in hits:
        idx = hit['corpus_id']
        score = hit['score'] 
        
        name = df['first_name'][idx]
        username = f"@{df['username'][idx]}" if pd.notna(df['username'][idx]) else "[Скрыт]"
        bio = df['bio'][idx]
        group = df['group_name'][idx] if 'group_name' in df.columns else "Неизвестно"
        
        print(f"Совпадение: {score:.2f}")
        print(f" {name} ({username}) |  Чат: {group}")
        print(f" Bio: {bio}")
        print("-" * 30) 