"""
MSAJCE High-Speed Synthetic RAG Testset Generator

Direct LLM-powered testset generation implementing RAG evaluation principles:
- Single-Hop Queries (Specific & Abstract)
- Multi-Hop Queries (Specific & Abstract)
- Categorization, source file mapping, and exact identifier flag

Bypasses heavy framework overhead for maximum speed, stability, and zero rate-limit issues.
"""

import os
import sys
import json
import random
import re
import argparse
import time
from typing import List, Dict, Any
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")

CATEGORY_MAPPING = {
    "msajce_cse": "Department — Computer Science & Engineering",
    "msajce_csbs": "Department — CS & Business Systems",
    "msajce_cyber": "Department — CS & Cyber Security",
    "msajce_aids": "Department — AI & Data Science",
    "msajce_aiml": "Department — AI & Machine Learning",
    "msajce_information_technology": "Department — Information Technology",
    "msajce_ece": "Department — Electronics & Communication",
    "msajce_eee": "Department — Electrical & Electronics",
    "msajce_mech": "Department — Mechanical Engineering",
    "msajce_civil": "Department — Civil Engineering",
    "msajce_bs": "Department — Science & Humanities",
    "msajce_science_and_humanities": "Department — Science & Humanities",
    "msajce_alumni": "Alumni Association",
    "msajce_placement": "Placement & Careers",
    "msajce_admission": "Admission & Fees",
    "msajce_hostel": "Hostel & Accommodation",
    "msajce_transport": "Transport & Bus Routes",
    "msajce_research": "Research & Publications",
    "msajce_incubation": "Incubation Centre",
    "msajce_library": "Library",
    "msajce_iqac": "IQAC & Accreditation",
    "msajce_nirf": "NIRF Ranking",
    "msajce_sports": "Sports & Athletics",
    "msajce_about": "About MSAJCE",
}

def get_category(filename: str) -> str:
    base = os.path.splitext(os.path.basename(filename.lower()))[0]
    return CATEGORY_MAPPING.get(base, "General — MSAJCE")

def check_has_exact_identifier(text: str) -> bool:
    q_lower = text.lower()
    if re.search(r'\b(cutoff|cut-off|code|number|capacity|tnea|fee|rupees|rs\.?|\d+)\b', q_lower):
        return True
    return False

PROMPT_SINGLE_HOP = """You are an expert evaluator for RAG (Retrieval-Augmented Generation) systems.
Given the following context excerpt from Mohamed Sathak A.J. College of Engineering (MSAJCE) documentation, generate synthetic ground-truth question and answer pairs.

Context Source File: {source_file}
Context Category: {category}
Context Content:
---
{content}
---

Generate exactly {num_pairs} QA items based STRICTLY on the content above.
Include a mix of:
1. Specific Queries (fact-based, looking for exact numbers, rules, facilities, or names).
2. Abstract Queries (higher-level, summary or explanation-seeking).

Return a JSON array of objects with the following keys:
- "question": string
- "expected_answer": string (accurate, comprehensive answer based only on the context)
- "query_type": string ("single_hop_specific" or "single_hop_abstract")

Return ONLY valid JSON matching this schema:
[
  {{
    "question": "...",
    "expected_answer": "...",
    "query_type": "single_hop_specific"
  }}
]
"""

PROMPT_MULTI_HOP = """You are an expert evaluator for RAG systems.
Given two distinct document context excerpts from Mohamed Sathak A.J. College of Engineering (MSAJCE), generate multi-hop queries that REQUIRE synthesising information from BOTH contexts to answer correctly.

Context 1 ({source_file_1}):
---
{content_1}
---

Context 2 ({source_file_2}):
---
{content_2}
---

Generate exactly {num_pairs} multi-hop QA items.
Include:
1. Multi-Hop Specific Query (requires exact figures/facts from both documents).
2. Multi-Hop Abstract Query (requires comparing or summarizing across both documents).

Return a JSON array of objects with keys:
- "question": string
- "expected_answer": string (synthesized answer from both contexts)
- "query_type": string ("multi_hop_specific" or "multi_hop_abstract")

Return ONLY valid JSON matching this schema:
[
  {{
    "question": "...",
    "expected_answer": "...",
    "query_type": "multi_hop_specific"
  }}
]
"""

def generate_samples(client: OpenAI, prompt: str, max_retries: int = 3) -> List[Dict[str, Any]]:
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="meta/llama-3.1-70b-instruct",
                messages=[
                    {"role": "system", "content": "You are a precise JSON-only generator for RAG dataset evaluation. Respond ONLY with valid JSON array or object, no markdown or text wrapper."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.4
            )
            raw = response.choices[0].message.content.strip()
            # Clean backticks if present
            if "```" in raw:
                raw = re.sub(r"^```(?:json)?", "", raw, flags=re.MULTILINE)
                raw = re.sub(r"```$", "", raw, flags=re.MULTILINE).strip()
            # Parse JSON
            data = json.loads(raw)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, list):
                        return v
                return [data]
        except Exception as e:
            print(f"    [WARN] Attempt {attempt+1} failed: {e}", file=sys.stderr)
            time.sleep(3)
    return []

def main():
    parser = argparse.ArgumentParser(description="MSAJCE Fast Testset Generator")
    parser.add_argument("--count", type=int, default=15, help="Number of questions to generate")
    parser.add_argument("--dataset-dir", type=str, default="dataset", help="Directory containing dataset .md files")
    parser.add_argument("--output", type=str, default="eval/eval_dataset.json", help="Output JSON path")
    parser.add_argument("--no-merge", action="store_true", help="Overwrite existing dataset")
    args = parser.parse_args()

    if not NVIDIA_API_KEY:
        print("[ERROR] NVIDIA_API_KEY is missing.", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=NVIDIA_API_KEY
    )

    all_files = [f for f in os.listdir(args.dataset_dir) if f.endswith(".md")]
    if not all_files:
        print("[ERROR] No .md dataset files found.", file=sys.stderr)
        sys.exit(1)

    print(f"\n============================================================")
    print(f"  MSAJCE High-Speed RAG Testset Generator")
    print(f"  Files available: {len(all_files)}")
    print(f"  Target questions: {args.count}")
    print(f"  Output path:      {args.output}")
    print(f"============================================================\n")

    file_contents = {}
    for fn in all_files:
        path = os.path.join(args.dataset_dir, fn)
        with open(path, "r", encoding="utf-8") as f:
            text = f.read().strip()
            if len(text) > 100:
                file_contents[fn] = text

    generated_items = []
    
    # 70% single hop, 30% multi hop
    num_single = max(1, int(args.count * 0.7))
    num_multi = max(1, args.count - num_single)

    print(f"[RUN] Generating {num_single} Single-Hop questions...")
    selected_files = random.sample(list(file_contents.keys()), min(num_single, len(file_contents)))
    
    for fn in selected_files:
        content = file_contents[fn][:2500]  # Chunk context window
        cat = get_category(fn)
        prompt = PROMPT_SINGLE_HOP.format(
            source_file=fn,
            category=cat,
            content=content,
            num_pairs=2
        )
        items = generate_samples(client, prompt)
        for item in items:
            q = item.get("question", "").strip()
            ans = item.get("expected_answer", "").strip()
            if q and ans:
                generated_items.append({
                    "question": q,
                    "expected_answer": ans,
                    "category": cat,
                    "source_file": fn.replace(".md", ".pdf"),
                    "has_exact_identifier": check_has_exact_identifier(q)
                })
        print(f"  - Completed single-hop batch for {fn} (Total so far: {len(generated_items)})")
        time.sleep(1)

    print(f"\n[RUN] Generating Multi-Hop questions across document pairs...")
    file_pairs = []
    keys = list(file_contents.keys())
    for _ in range(num_multi):
        f1, f2 = random.sample(keys, 2)
        file_pairs.append((f1, f2))

    for f1, f2 in file_pairs:
        prompt = PROMPT_MULTI_HOP.format(
            source_file_1=f1,
            content_1=file_contents[f1][:1500],
            source_file_2=f2,
            content_2=file_contents[f2][:1500],
            num_pairs=1
        )
        items = generate_samples(client, prompt)
        cat1 = get_category(f1)
        for item in items:
            q = item.get("question", "").strip()
            ans = item.get("expected_answer", "").strip()
            if q and ans:
                generated_items.append({
                    "question": q,
                    "expected_answer": ans,
                    "category": cat1,
                    "source_file": f"{f1.replace('.md','.pdf')}, {f2.replace('.md','.pdf')}",
                    "has_exact_identifier": check_has_exact_identifier(q)
                })
        print(f"  - Completed multi-hop batch for {f1} + {f2} (Total so far: {len(generated_items)})")
        time.sleep(1)

    # Load existing dataset to merge
    output_data = []
    if not args.no_merge and os.path.exists(args.output):
        try:
            with open(args.output, "r", encoding="utf-8") as f:
                output_data = json.load(f)
            print(f"\n[MERGE] Loaded {len(output_data)} existing items from {args.output}")
        except Exception as e:
            print(f"[WARN] Error reading {args.output}: {e}")

    existing_q_set = {x["question"].strip().lower() for x in output_data}
    added_count = 0
    for item in generated_items:
        key = item["question"].strip().lower()
        if key not in existing_q_set:
            output_data.append(item)
            existing_q_set.add(key)
            added_count += 1

    if args.no_merge:
        output_data = generated_items
        added_count = len(generated_items)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"\n============================================================")
    print(f"  [SUCCESS] TESTSET GENERATION COMPLETED IN SECONDS!")
    print(f"  New items synthesized : {len(generated_items)}")
    print(f"  Deduplicated & added  : {added_count}")
    print(f"  Total dataset size    : {len(output_data)}")
    print(f"  Dataset saved to      : {args.output}")
    print(f"============================================================\n")

if __name__ == "__main__":
    main()
