import os
import json
import time
import asyncio
import aiohttp
from typing import List, Dict, Any
from pathlib import Path
from dotenv import load_dotenv

# Load environmental variables
load_dotenv(Path(__file__).parent.parent / ".env")

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
if not NVIDIA_API_KEY:
    print("Warning: NVIDIA_API_KEY not set. Generation will fail.")

DATASET_DIR = Path(__file__).parent.parent / "dataset"
QA_OUT_DIR = Path(__file__).parent.parent / "qa_datasets"
QA_OUT_DIR.mkdir(exist_ok=True)

# Global semaphore to control Nvidia API rate limits (40 RPM limit)
SEMAPHORE = asyncio.Semaphore(2)

CATEGORIES = {
    "qa_departments": [
        "msajce_cse.md", "msajce_it.md", "msajce_ece.md", "msajce_ece_vlsi.md", 
        "msajce_ece-act.md", "msajce_mech.md", "msajce_civil.md", "msajce_eee.md", 
        "msajce_aids.md", "msajce_aiml.md", "msajce_csbs.md", "msajce_cyber.md", 
        "msajce_science_and_humanities.md"
    ],
    "qa_admissions_facilities": [
        "msajce_admission.md", "msajce_hostel.md", "msajce_transport.md", "msajce_library.md"
    ],
    "qa_placements_alumni": [
        "msajce_placement.md", "msajce_alumni.md"
    ],
    "qa_research_incubation": [
        "msajce_research.md", "msajce_incubation.md", "msajce_technologycentre.md", "msajce_edc.md"
    ],
    "qa_committees_cells": [
        "msajce_iqac.md", "msajce_grievanceredressalcommittee.md", "msajce_scstcell.md", 
        "msajce_minoritycell.md", "msajce_womensempowermentcell.md", "msajce_obccell.md", 
        "msajce_internalcomplaintcommittee.md", "msajce_antiragging.md"
    ],
    "qa_college_overview": [
        "msajce_about.md", "msajce_ourhistory.md", "msajce_principal.md", 
        "msajce_visionmission.md", "msajce_msajcepolicy.md", "msajce_naac.md", 
        "msajce_nirf.md", "msajce_governingcouncil.md", "msajce_planningmonitoringboard.md", 
        "msajce_developer_ramanathan.md"
    ],
    "qa_student_life": [
        "msajce_sports.md", "msajce_clubssocieties.md", "msajce_professional_societies.md", 
        "msajce_socialservices.md", "msajce_ebsb.md", "msajce_karma.md"
    ]
}

def chunk_text(text: str, max_chars: int = 15000) -> List[str]:
    """Split text into chunks of approx max_chars, trying to split on newlines."""
    chunks = []
    while len(text) > max_chars:
        split_idx = text.rfind('\n', 0, max_chars)
        if split_idx == -1:
            split_idx = max_chars
        chunks.append(text[:split_idx])
        text = text[split_idx:].strip()
    if text:
        chunks.append(text)
    return chunks

async def generate_qa_for_chunk(session: aiohttp.ClientSession, chunk: str, source_file: str) -> List[Dict]:
    system_prompt = f"""You are a dataset generator. Given the following markdown text from the file '{source_file}', generate exhaustive Question and Answer pairs based ONLY on the facts provided in the text.
Requirements:
1. Generate as many distinct, highly-specific Q&A pairs as possible (aim for 20-30 per chunk if content allows, no upper limit).
2. The questions should be phrased as a user might ask them.
3. The answers must be self-contained, detailed, and directly answer the question using the facts.
4. Output strictly as a JSON array of objects, with each object having exactly two keys: "question" and "answer". Do not wrap the JSON in markdown blocks like ```json.
"""
    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "meta/llama-3.1-70b-instruct",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": chunk}
        ],
        "temperature": 0.2,
        "max_tokens": 4096
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with SEMAPHORE:
                async with session.post("https://integrate.api.nvidia.com/v1/chat/completions", headers=headers, json=payload, timeout=90) as res:
                    res.raise_for_status()
                    data = await res.json()
            
            content = data["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                import re
                content = re.sub(r"^```(?:json)?\n?|```$", "", content, flags=re.MULTILINE).strip()
            
            try:
                qa_pairs = json.loads(content)
                if isinstance(qa_pairs, list):
                    for qa in qa_pairs:
                        qa["source_file"] = source_file
                    return qa_pairs
            except json.JSONDecodeError:
                print(f"Warning: Failed to parse JSON from output of {source_file} (Attempt {attempt+1})")
        except Exception as e:
            print(f"Error on API request for {source_file} (Attempt {attempt+1}): {e}")
        
        await asyncio.sleep(5 * (attempt + 1)) 
    
    print(f"Failed to generate Q&A for chunk of {source_file} after {max_retries} attempts.")
    return []

async def process_category(session: aiohttp.ClientSession, category: str, files: List[str]):
    print(f"Processing category: {category} ({len(files)} files)")
    all_qa_pairs = []
    
    for filename in files:
        filepath = DATASET_DIR / filename
        if not filepath.exists():
            print(f"File not found: {filepath}")
            continue
            
        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read()
            
        chunks = chunk_text(text)
        tasks = [generate_qa_for_chunk(session, chunk, filename) for chunk in chunks]
        results = await asyncio.gather(*tasks)
        for res in results:
            all_qa_pairs.extend(res)
            
    out_file = QA_OUT_DIR / f"{category}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(all_qa_pairs, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(all_qa_pairs)} Q&A pairs for {category} to {out_file}")

async def get_embeddings(session: aiohttp.ClientSession, texts: List[str]) -> List[List[float]]:
    if not texts: return []
    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json"
    }
    batch_size = 50
    all_embeddings = []
    
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        payload = {
            "input": batch,
            "model": "nvidia/nv-embedqa-e5-v5",
            "input_type": "query"
        }
        for attempt in range(3):
            try:
                async with SEMAPHORE:
                    async with session.post("https://integrate.api.nvidia.com/v1/embeddings", headers=headers, json=payload, timeout=60) as res:
                        res.raise_for_status()
                        data = await res.json()
                sorted_data = sorted(data["data"], key=lambda x: x["index"])
                all_embeddings.extend([item["embedding"] for item in sorted_data])
                break
            except Exception as e:
                print(f"Embedding error (Attempt {attempt+1}): {e}")
                await asyncio.sleep(5)
    return all_embeddings

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    dot = sum(x*y for x, y in zip(v1, v2))
    mag1 = sum(x*x for x in v1) ** 0.5
    mag2 = sum(x*x for x in v2) ** 0.5
    if mag1 == 0 or mag2 == 0: return 0.0
    return dot / (mag1 * mag2)

async def cross_link_qa_pairs(session: aiohttp.ClientSession):
    print("Starting cross-linking phase...")
    all_qa = []
    
    idx_counter = 0
    for cat_name in CATEGORIES.keys():
        path = QA_OUT_DIR / f"{cat_name}.json"
        if not path.exists(): continue
        with open(path, "r", encoding="utf-8") as f:
            pairs = json.load(f)
        for i, pair in enumerate(pairs):
            pair["id"] = f"qa_{idx_counter}"
            pair["category_file"] = f"{cat_name}.json"
            pair["related_ids"] = []
            all_qa.append(pair)
            idx_counter += 1

    if not all_qa:
        print("No Q&A pairs found to cross-link.")
        return

    print(f"Embedding {len(all_qa)} questions for cross-linking...")
    questions = [q["question"] for q in all_qa]
    embeddings = await get_embeddings(session, questions)
    
    if len(embeddings) != len(all_qa):
        print("Embedding count mismatch. Skipping cross-linking.")
        return
        
    print("Computing similarities and linking related Q&A pairs...")
    SIMILARITY_THRESHOLD = 0.85
    
    for i in range(len(all_qa)):
        for j in range(i+1, len(all_qa)):
            sim = cosine_similarity(embeddings[i], embeddings[j])
            if sim >= SIMILARITY_THRESHOLD:
                all_qa[i]["related_ids"].append(all_qa[j]["id"])
                all_qa[j]["related_ids"].append(all_qa[i]["id"])
                
    print("Saving cross-linked files...")
    grouped = {}
    for qa in all_qa:
        cat_file = qa.pop("category_file")
        if cat_file not in grouped:
            grouped[cat_file] = []
        grouped[cat_file].append(qa)
        
    for cat_file, pairs in grouped.items():
        with open(QA_OUT_DIR / cat_file, "w", encoding="utf-8") as f:
            json.dump(pairs, f, indent=2, ensure_ascii=False)
    print("Cross-linking complete.")

async def main():
    async with aiohttp.ClientSession() as session:
        tasks = []
        for cat, files in CATEGORIES.items():
            tasks.append(process_category(session, cat, files))
        await asyncio.gather(*tasks)
        await cross_link_qa_pairs(session)
        
if __name__ == "__main__":
    start_time = time.time()
    asyncio.run(main())
    print(f"Total time elapsed: {time.time() - start_time:.2f} seconds.")
