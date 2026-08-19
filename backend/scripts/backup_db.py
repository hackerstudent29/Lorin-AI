import os
import psycopg2
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
from dotenv import load_dotenv

# Load env variables
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(dotenv_path)

DB_URL = os.getenv("DATABASE_URL")
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

print("Starting backups...")

# 1. Qdrant Backup
print("Connecting to Qdrant...")
q_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=60.0)
source_col = "college_knowledgebase"
backup_col = f"{source_col}_backup"

if q_client.collection_exists(backup_col):
    print(f"Deleting existing Qdrant backup collection '{backup_col}'...")
    q_client.delete_collection(backup_col)

print(f"Fetching config for '{source_col}'...")
col_info = q_client.get_collection(source_col)
vectors_config = col_info.config.params.vectors

print(f"Creating backup collection '{backup_col}'...")
q_client.create_collection(
    collection_name=backup_col,
    vectors_config=vectors_config
)

print(f"Copying points from '{source_col}' to '{backup_col}'...")
offset = None
total_points = 0
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
    
    points = [
        PointStruct(id=r.id, vector=r.vector, payload=r.payload)
        for r in records
    ]
    
    q_client.upsert(
        collection_name=backup_col,
        points=points
    )
    total_points += len(points)
    print(f"  Copied {total_points} points so far...")
    if offset is None:
        break
print(f"Qdrant backup completed. Total points copied: {total_points}")

# 2. PostgreSQL Backup
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

for table in tables:
    backup_table = f"{table}_backup"
    print(f"Backing up table '{table}' to '{backup_table}'...")
    cur.execute(f"DROP TABLE IF EXISTS {backup_table};")
    cur.execute(f"CREATE TABLE {backup_table} AS SELECT * FROM {table};")

conn.commit()
cur.close()
conn.close()
print("PostgreSQL backup completed.")
