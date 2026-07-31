import os
import sys
import json
import uuid
import hashlib
import time
import re
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

# Add backend directory to sys.path
WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.append(os.path.join(WORKSPACE_DIR, "backend"))

# Import pipeline configurations and helper functions from process_dataset.py
from process_dataset import (
    extract_typed_entities,
    extract_keywords_from_text,
    get_nvidia_embeddings_batch,
    get_metadata_for_filename,
    NVIDIA_API_KEY,
    QDRANT_URL,
    QDRANT_API_KEY,
    COLLECTION_NAME
)
from pipeline.bm25_index_manager import BM25IndexManager

def main():
    # Force output to UTF-8
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

    master_qa_path = os.path.join(WORKSPACE_DIR, "backend", "dataset_qa", "master_qa.json")
    if not os.path.exists(master_qa_path):
        print(f"[ERROR] Master QA dataset not found at {master_qa_path}. Please run extraction first.")
        sys.exit(1)

    print(f"\n============================================================")
    print(f"  MSAJCE Qdrant Ingestion Pipeline: QA Pairs")
    print(f"  Source file   : {master_qa_path}")
    print(f"  Collection    : {COLLECTION_NAME}")
    print(f"  Qdrant URL    : {QDRANT_URL}")
    print(f"============================================================\n")

    with open(master_qa_path, "r", encoding="utf-8") as f:
        qa_pairs = json.load(f)

    if not qa_pairs:
        print("[ERROR] No QA pairs found in master QA file.")
        sys.exit(1)

    print(f"[INFO] Loaded {len(qa_pairs)} QA pairs. Formatting chunks...")

    formatted_texts = []
    metadata_list = []

    for qa in qa_pairs:
        q = qa.get("question", "").strip()
        a = qa.get("answer", "").strip()
        if not q or not a:
            continue
            
        sec = qa.get("section", "General")
        src_file = qa.get("source_file", "msajce_about.md")
        
        # Map .md filenames to .pdf in metadata to match RAG evaluation citations
        if src_file.endswith(".md"):
            src_file = src_file.replace(".md", ".pdf")
            
        category = qa.get("category", "General — MSAJCE")
        
        # Format chunk content
        qa_text = f"Question: {q}\nAnswer: {a}"
        
        # Retrieve mapped metadata
        file_meta = get_metadata_for_filename(src_file)
        
        formatted_texts.append(qa_text)
        metadata_list.append({
            "question": q,
            "answer": a,
            "section_title": f"FAQ — {sec}",
            "source_file": src_file,
            "category": category,
            "title": f"FAQ: {file_meta['title']}",
            "url": file_meta["url"],
            "department": file_meta["department"],
            "document_type": "faq"
        })

    # Generate Embeddings
    print(f"\n[EMBED] Requesting embeddings for {len(formatted_texts)} QA chunks...")
    embeddings = get_nvidia_embeddings_batch(formatted_texts, batch_size=20)

    # Build Qdrant points
    points = []
    for idx, (text, meta, emb) in enumerate(zip(formatted_texts, metadata_list, embeddings)):
        # Compute deterministic hashes to allow clean upsert/overwrite on subsequent runs
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        chunk_hash = h[:16]
        point_id = int(h[:8], 16)
        parent_id = str(uuid.uuid4())
        
        entities = extract_typed_entities(text)
        entity_ids = list(set(re.findall(r'<!--(ent_\d+)-->', text)))
        keywords = extract_keywords_from_text(text)
        
        points.append(PointStruct(
            id=point_id,
            vector=emb,
            payload={
                "text": text,
                "title": meta["title"],
                "section_title": meta["section_title"],
                "source_file": meta["source_file"],
                "url": meta["url"],
                "category": meta["category"],
                "department": meta["department"],
                "document_type": meta["document_type"],
                "page_number": 1,
                "chunk_index": 1,
                "total_chunks": 1,
                "entities": entities,
                "entity_ids": entity_ids,
                "keywords": keywords,
                "parent_id": f"faq-{parent_id}",
                "chunk_hash": chunk_hash,
                "scraped_at": "2026-07-31T00:00:00Z"
            }
        ))

    # Initialize Qdrant client
    qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=60.0)

    # Batch upsert points
    BATCH = 20
    total_batches = (len(points) - 1) // BATCH + 1
    print(f"\n[QDRANT] Upserting {len(points)} FAQ points into '{COLLECTION_NAME}'...")
    
    for i in range(0, len(points), BATCH):
        batch = points[i:i + BATCH]
        batch_num = i // BATCH + 1
        for attempt in range(4):
            try:
                qdrant_client.upsert(collection_name=COLLECTION_NAME, points=batch)
                print(f"   [Upload] Batch {batch_num}/{total_batches} ({len(batch)} vectors) OK")
                time.sleep(0.15)
                break
            except Exception as e:
                wait = 2 ** attempt
                print(f"   [WARN] Batch {batch_num} attempt {attempt+1} failed: {e}. Retrying in {wait}s...")
                time.sleep(wait)
        else:
            print(f"   [ERROR] Batch {batch_num} permanently failed. Skipping.")

    print("\n[QDRANT] Ingestion successful.")

    # Rebuild BM25 index for sparse hybrid search
    print(f"\n[BM25] Rebuilding keyword index to include {len(formatted_texts)} QA chunks...")
    try:
        bm25_mgr = BM25IndexManager(qdrant_client)
        new_payloads = []
        for point in points:
            payload = point.payload
            new_payloads.append({
                "text": payload["text"],
                "source_file": payload["source_file"],
                "category": payload["category"],
                "section_title": payload["section_title"],
                "page_number": payload["page_number"],
                "parent_id": payload["parent_id"],
                "chunk_hash": payload["chunk_hash"]
            })
            
        bm25_mgr.append_and_rebuild(
            new_texts=formatted_texts,
            new_payloads=new_payloads
        )
        print("[BM25] Hybrid keyword index successfully rebuilt and saved!")
    except Exception as e:
        print(f"[WARN] BM25 keyword index rebuild failed: {e}")

    info = qdrant_client.get_collection(COLLECTION_NAME)
    print(f"\n============================================================")
    print(f"  [SUCCESS] FAQ INTEGRATION COMPLETE")
    print(f"  Total Vectors now in Qdrant: {info.points_count}")
    print(f"============================================================\n")

if __name__ == "__main__":
    main()
