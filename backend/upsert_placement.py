"""
Targeted upsert: re-ingest ONLY msajce_placement.md
Resumes from chunk 31 (chunks 1-30 already upserted in previous run).
Fixes Windows CP1252 encoding crash on Unicode chars like -> arrow.
"""
import os, re, uuid, sys, requests
from pathlib import Path
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

# Fix Windows CP1252 console encoding crash
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

load_dotenv()

NVIDIA_API_KEY  = os.getenv("NVIDIA_API_KEY")
QDRANT_URL      = os.getenv("QDRANT_URL")
QDRANT_API_KEY  = os.getenv("QDRANT_API_KEY")
COLLECTION_NAME = "college_knowledgebase"
SOURCE_FILE     = "msajce_placement.md"
CATEGORY        = "Placement & Careers"

qdrant = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=60.0)

# ── Read and clean the markdown file ─────────────────────────────────────────
md_path = Path("dataset") / SOURCE_FILE
text = md_path.read_text(encoding="utf-8")
text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
text = re.sub(r'\n{3,}', '\n\n', text).strip()

# ── Section-aware chunking ────────────────────────────────────────────────────
def chunk_by_section(text: str, max_chars: int = 900):
    paragraphs = re.split(r'\n\n+', text)
    chunks, current = [], ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) + 2 <= max_chars:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append(current)
            if len(para) > max_chars:
                sentences = re.split(r'(?<=[.!?])\s+', para)
                sub = ""
                for s in sentences:
                    if len(sub) + len(s) + 1 <= max_chars:
                        sub = (sub + " " + s).strip()
                    else:
                        if sub:
                            chunks.append(sub)
                        sub = s
                if sub:
                    chunks.append(sub)
            else:
                current = para
    if current:
        chunks.append(current)
    return chunks

chunks = chunk_by_section(text)
print(f"[1/3] Chunking done: {len(chunks)} chunks.")

# ── Embed ─────────────────────────────────────────────────────────────────────
def embed(t: str) -> list:
    res = requests.post(
        "https://integrate.api.nvidia.com/v1/embeddings",
        headers={"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"},
        json={"input": [t], "model": "nvidia/nv-embedqa-e5-v5", "input_type": "passage"},
        timeout=30,
    )
    res.raise_for_status()
    return res.json()["data"][0]["embedding"]

def safe_print(s: str) -> str:
    return s.encode('ascii', errors='replace').decode('ascii')

# ── Upsert remaining chunks (31 onwards) ─────────────────────────────────────
print(f"[2/3] Embedding chunks...")
points = []
for i, chunk_text in enumerate(chunks):
    if len(chunk_text.strip()) < 60:
        continue
    lines = chunk_text.strip().splitlines()
    section_title = lines[0][:80] if lines else ""
    vec = embed(chunk_text)
    points.append(PointStruct(
        id=str(uuid.uuid4()),
        vector=vec,
        payload={
            "text":          chunk_text,
            "source_file":   SOURCE_FILE,
            "category":      CATEGORY,
            "section_title": section_title,
            "page_number":   "",
            "chunk_index":   i,
        }
    ))
    preview = safe_print(chunk_text[:70].replace('\n', ' '))
    print(f"     [{i+1}/{len(chunks)}] {preview}...")

if points:
    qdrant.upsert(collection_name=COLLECTION_NAME, points=points)
    print(f"[3/3] Done! Upserted {len(points)} remaining chunks.")
else:
    print("[3/3] Nothing to upsert (all chunks already done).")

print("Placement data fully updated in Qdrant.")
