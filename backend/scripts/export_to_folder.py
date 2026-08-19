import os
import json
import psycopg2
import datetime
from decimal import Decimal
from qdrant_client import QdrantClient
from dotenv import load_dotenv

# Load env variables
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path)

DB_URL = os.getenv("DATABASE_URL")
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

BACKUP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'backup'))
os.makedirs(BACKUP_DIR, exist_ok=True)

print(f"Starting local file backup to {BACKUP_DIR}...")

# 1. Qdrant Export
print("Connecting to Qdrant...")
q_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=60.0)
source_col = "college_knowledgebase"

qdrant_backup_file = os.path.join(BACKUP_DIR, f"{source_col}_backup.json")
print(f"Exporting Qdrant collection to {qdrant_backup_file}...")

offset = None
total_points = 0

with open(qdrant_backup_file, "w", encoding="utf-8") as f:
    f.write("[\n")
    first = True
    while True:
        records, offset = q_client.scroll(
            collection_name=source_col,
            offset=offset,
            limit=50,
            with_payload=True,
            with_vectors=True
        )
        if not records:
            break
        
        for r in records:
            if not first:
                f.write(",\n")
            first = False
            item = {
                "id": r.id,
                "vector": r.vector,
                "payload": r.payload
            }
            json.dump(item, f)
            total_points += 1
            
        print(f"  Exported {total_points} points so far...")
        if offset is None:
            break
    f.write("\n]\n")

print(f"Qdrant export completed. Total points: {total_points}")

# 2. PostgreSQL Export
print("\nConnecting to PostgreSQL...")
conn = psycopg2.connect(DB_URL)
cur = conn.cursor()

tables = [
    'scraped_documents', 
    'chat_sessions', 
    'chat_messages', 
    'query_cache', 
    'message_feedback', 
    'entities'
]

class CustomEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        if hasattr(obj, '__str__'):
            return str(obj)
        return super().default(obj)

for table in tables:
    postgres_backup_file = os.path.join(BACKUP_DIR, f"{table}_backup.json")
    print(f"Exporting table '{table}' to '{postgres_backup_file}'...")
    
    cur.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}';")
    columns = [row[0] for row in cur.fetchall()]
    
    if not columns:
        print(f"  Table {table} not found or empty columns, skipping.")
        continue
        
    cur.execute(f"SELECT * FROM {table};")
    rows = cur.fetchall()
    
    data = []
    for row in rows:
        data.append(dict(zip(columns, row)))
        
    with open(postgres_backup_file, "w", encoding="utf-8") as f:
        json.dump(data, f, cls=CustomEncoder, indent=2)
        
    print(f"  Exported {len(rows)} rows.")

conn.close()
print(f"\nAll backups successfully saved to folder: {BACKUP_DIR}")
