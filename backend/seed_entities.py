import os
import json
import psycopg2
import re
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("No DATABASE_URL found.")
    exit(1)

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

# Load the entity registry JSON
try:
    with open("dataset/entity_registry.json", "r", encoding="utf-8") as f:
        registry = json.load(f)
except Exception as e:
    print(f"Error loading registry: {e}")
    exit(1)

inserted = 0
for raw_name, entity_id in registry.items():
    canonical_name = raw_name
    
    # Generate aliases (e.g., lower case, strip honorifics)
    aliases_set = set([canonical_name, canonical_name.lower()])
    
    # Strip honorifics (Dr., Mr., Mrs., Ms., Prof.)
    clean_name = re.sub(r'\b(Dr|Mr|Mrs|Ms|Prof)\.?\s*', '', canonical_name, flags=re.IGNORECASE).strip()
    if clean_name:
        aliases_set.add(clean_name)
        aliases_set.add(clean_name.lower())
    
    aliases = list(aliases_set)
    
    try:
        cur.execute("""
            INSERT INTO entities (entity_id, canonical_name, roles, departments, aliases)
            VALUES (%s, %s, '{}', '{}', %s)
            ON CONFLICT (entity_id) DO UPDATE SET
                canonical_name = EXCLUDED.canonical_name,
                aliases = EXCLUDED.aliases
        """, (entity_id, canonical_name, aliases))
        inserted += 1
    except Exception as e:
        print(f"Failed to insert {entity_id}: {e}")

print(f"Successfully inserted {inserted} entities.")

cur.close()
conn.close()
