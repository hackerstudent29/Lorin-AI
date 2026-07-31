import os
import sys
import json
import re
import time
import argparse
from typing import List, Dict, Any
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from dotenv import load_dotenv
from openai import OpenAI

# Load environment
load_dotenv()
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")

# Set paths relative to workspace root
WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATASET_DIR = os.path.join(WORKSPACE_DIR, "backend", "dataset")
OUTPUT_DIR = os.path.join(WORKSPACE_DIR, "backend", "dataset_qa")
JSON_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "json")
MD_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "markdown")
CHECKPOINT_FILE = os.path.join(OUTPUT_DIR, ".checkpoint.json")

# Category mapping based on filename
CATEGORY_MAPPING = {
    "msajce_cse": "Department — Computer Science & Engineering",
    "msajce_csbs": "Department — CS & Business Systems",
    "msajce_cyber": "Department — CS & Cyber Security",
    "msajce_aids": "Department — AI & Data Science",
    "msajce_aiml": "Department — AI & Machine Learning",
    "msajce_information_technology": "Department — Information Technology",
    "msajce_it": "Department — Information Technology",
    "msajce_ece": "Department — Electronics & Communication",
    "msajce_ece-act": "Department — Electronics & Communication",
    "msajce_ece_vlsi": "Department — Electronics & Communication",
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

# Thread safety locks
checkpoint_lock = Lock()
results_lock = Lock()
print_lock = Lock()

def safe_print(*args, **kwargs):
    with print_lock:
        print(*args, **kwargs)
        sys.stdout.flush()

def get_category(filename: str) -> str:
    base = os.path.splitext(os.path.basename(filename.lower()))[0]
    return CATEGORY_MAPPING.get(base, "General — MSAJCE")

# Semantic splitting of markdown by headers
def split_markdown_by_headers(text: str) -> List[Dict[str, str]]:
    lines = text.split('\n')
    sections = []
    current_section = []
    current_header = "Introduction"
    
    for line in lines:
        if line.startswith('#'):
            if current_section:
                sections.append({
                    "header": current_header,
                    "content": '\n'.join(current_section).strip()
                })
                current_section = []
            current_header = line.strip('# \t')
        current_section.append(line)
        
    if current_section:
        sections.append({
            "header": current_header,
            "content": '\n'.join(current_section).strip()
        })
        
    # Group small sections to make chunks of appropriate size (1000 - 4500 characters)
    chunks = []
    curr_header = ""
    curr_content = ""
    
    for sec in sections:
        sec_content = sec["content"]
        if not sec_content:
            continue
        if len(curr_content) + len(sec_content) > 4000 and curr_content:
            chunks.append({
                "header": curr_header,
                "content": curr_content
            })
            curr_header = sec["header"]
            curr_content = sec_content
        else:
            if curr_content:
                curr_content += "\n\n" + sec_content
                curr_header += " & " + sec["header"]
            else:
                curr_header = sec["header"]
                curr_content = sec_content
                
    if curr_content:
        chunks.append({
            "header": curr_header,
            "content": curr_content
        })
        
    return chunks

PROMPT_EXTRACT_QA = """You are an expert QA dataset generator for college information retrieval systems.
Analyze the following context excerpt from Mohamed Sathak A.J. College of Engineering (MSAJCE) documentation and extract the MAXIMUM possible number of question and answer pairs covering ALL details.

Context Section: {section_name}
Context Content:
---
{content}
---

Your goal is to extract as many accurate questions and answers as possible to completely cover the facts, figures, policies, names, codes, procedures, or links mentioned in the context.

For each QA pair, select and apply one of the following question formats to ensure a diverse set of queries:
1. "factoid" - Direct fact-based query (e.g., "What is the course code for CSBS?", "Who is the principal?")
2. "scenario" - Situational query (e.g., "If I have a cutoff of X, can I get admission under management quota?", "A student lost their ID card, what should they do?")
3. "yes_no" - Yes/No questions that require justification (e.g., "Is hostel accommodation mandatory for outstation students? Explain the rules.")
4. "procedural" - Process or step-by-step query (e.g., "What is the procedure to apply for scholarship?", "How can alumni register for the meet?")
5. "comparison" - Comparative query (e.g., "How does the placement package of CSE compare to IT?", "Compare the intake capacity between AI-DS and AI-ML.")
6. "exploratory" - Summary, role, or descriptive query (e.g., "Explain the objective of the Incubation Centre.")

Generate at least 3-8 QA pairs (depending on how dense the context is, generate more if there is a lot of factual information). Make sure every question can be fully answered using ONLY the provided context. Do not invent any facts.

Return ONLY a valid JSON array of objects, with no markdown formatting wrapper or other text.
Each object must have these keys:
- "question": string
- "answer": string (detailed, accurate answer citing facts from the context)
- "format": string (one of "factoid", "scenario", "yes_no", "procedural", "comparison", "exploratory")

JSON schema:
[
  {{
    "question": "Question text...",
    "answer": "Detailed answer...",
    "format": "scenario"
  }}
]
"""

def generate_qa_for_chunk(client: OpenAI, section_name: str, content: str, model_name: str, max_retries: int = 5) -> List[Dict[str, Any]]:
    prompt = PROMPT_EXTRACT_QA.format(section_name=section_name, content=content)
    delay = 2.0  # Base delay
    
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "You are a precise JSON-only generator. Respond ONLY with a valid JSON array. Do not wrap in markdown or add conversational filler."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                timeout=60.0
            )
            raw = response.choices[0].message.content.strip()
            
            if "```" in raw:
                raw = re.sub(r"^```(?:json)?", "", raw, flags=re.MULTILINE)
                raw = re.sub(r"```$", "", raw, flags=re.MULTILINE).strip()
                
            data = json.loads(raw)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return [data]
        except Exception as e:
            safe_print(f"    [WARN] Attempt {attempt+1} failed for section '{section_name[:30]}...': {e}")
            if "429" in str(e) or "limit" in str(e).lower() or "too many requests" in str(e).lower():
                backoff = delay * 5
                time.sleep(backoff)
                delay *= 1.5
            else:
                time.sleep(delay)
                delay *= 2.0
                
    return []

def load_checkpoint() -> Dict[str, Any]:
    with checkpoint_lock:
        if os.path.exists(CHECKPOINT_FILE):
            try:
                with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"processed_files": [], "total_questions": 0}

def save_checkpoint(processed_files: List[str], total_questions: int):
    with checkpoint_lock:
        os.makedirs(os.path.dirname(CHECKPOINT_FILE), exist_ok=True)
        with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "processed_files": sorted(list(set(processed_files))),
                "total_questions": total_questions
            }, f, indent=2)

def convert_to_markdown(filename: str, category: str, qa_pairs: List[Dict[str, Any]]) -> str:
    md = [f"# Extracted QA Pairs for `{filename}`", f"**Category**: {category}\n"]
    
    sections = {}
    for qa in qa_pairs:
        sec = qa.get("section", "General")
        if sec not in sections:
            sections[sec] = []
        sections[sec].append(qa)
        
    for sec_name, items in sections.items():
        md.append(f"## Section: {sec_name}\n")
        for idx, item in enumerate(items, 1):
            fmt = item.get("format", "general").capitalize()
            md.append(f"### Question {idx} ({fmt})")
            md.append(f"{item['question']}\n")
            md.append(f"**Answer**:\n{item['answer']}\n")
            md.append("---")
            
    return '\n'.join(md)

def process_chunk_task(client: OpenAI, task: Dict[str, Any], model_name: str) -> List[Dict[str, Any]]:
    filename = task["filename"]
    category = task["category"]
    header = task["header"]
    content = task["content"]
    chunk_idx = task["chunk_idx"]
    total_chunks = task["total_chunks"]
    
    safe_print(f"  -> Calling API for {filename} [Chunk {chunk_idx}/{total_chunks}] ('{header[:30]}...')")
    
    qa_list = generate_qa_for_chunk(client, header, content, model_name)
    
    # Post-process results
    processed_qa = []
    for qa in qa_list:
        if qa.get("question") and qa.get("answer"):
            qa["section"] = header
            qa["source_file"] = filename
            qa["category"] = category
            processed_qa.append(qa)
            
    safe_print(f"  <- Completed {filename} [Chunk {chunk_idx}/{total_chunks}]: generated {len(processed_qa)} QA pairs")
    return processed_qa

def main():
    parser = argparse.ArgumentParser(description="MSAJCE Detailed Parallel QA Pairs Extractor")
    parser.add_argument("--file", type=str, default=None, help="Process a single file specifically")
    parser.add_argument("--model", type=str, default="meta/llama-3.1-70b-instruct", help="Nvidia API model name")
    parser.add_argument("--workers", type=int, default=10, help="Number of parallel workers")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of files to process")
    parser.add_argument("--reset-checkpoint", action="store_true", help="Clear checkpoints and start fresh")
    args = parser.parse_args()
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

    if not NVIDIA_API_KEY:
        safe_print("[ERROR] NVIDIA_API_KEY is not set in environment or .env file.")
        sys.exit(1)

    client = OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=NVIDIA_API_KEY
    )

    # Initialize output folders
    os.makedirs(JSON_OUTPUT_DIR, exist_ok=True)
    os.makedirs(MD_OUTPUT_DIR, exist_ok=True)

    # Get all markdown files matching msajce_*.md, excluding msajce_all_resource_links.md
    all_files = sorted([
        f for f in os.listdir(DATASET_DIR)
        if f.startswith("msajce_") and f.endswith(".md") and f != "msajce_all_resource_links.md"
    ])

    if args.file:
        fn = args.file if args.file.endswith(".md") else args.file + ".md"
        if fn in all_files:
            all_files = [fn]
        else:
            safe_print(f"[ERROR] File not found in dataset folder: {args.file}")
            sys.exit(1)

    checkpoint = {"processed_files": [], "total_questions": 0} if args.reset_checkpoint else load_checkpoint()
    processed_files = checkpoint["processed_files"]
    total_questions = checkpoint["total_questions"]

    # Filter out files already processed
    files_to_process = [f for f in all_files if f not in processed_files]
    if args.limit:
        files_to_process = files_to_process[:args.limit]

    safe_print(f"\n============================================================")
    safe_print(f"  MSAJCE Comprehensive Parallel QA Extraction Pipeline")
    safe_print(f"  Total files located    : {len(all_files)}")
    safe_print(f"  Files already processed: {len(processed_files)}")
    safe_print(f"  Files to process       : {len(files_to_process)}")
    safe_print(f"  Model                  : {args.model}")
    safe_print(f"  Workers                : {args.workers}")
    safe_print(f"  Output folder          : {OUTPUT_DIR}")
    safe_print(f"============================================================\n")

    if not files_to_process:
        safe_print("[SUCCESS] All files have already been processed.")
        compile_master_files()
        return

    # Build list of chunk tasks
    chunk_tasks = []
    file_chunks_count = {}
    
    for fn in files_to_process:
        path = os.path.join(DATASET_DIR, fn)
        category = get_category(fn)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            
        if not content:
            safe_print(f"  [WARN] File {fn} is empty, skipping.")
            with checkpoint_lock:
                processed_files.append(fn)
            continue
            
        chunks = split_markdown_by_headers(content)
        file_chunks_count[fn] = len(chunks)
        
        for idx, chunk in enumerate(chunks, 1):
            chunk_tasks.append({
                "filename": fn,
                "category": category,
                "header": chunk["header"],
                "content": chunk["content"],
                "chunk_idx": idx,
                "total_chunks": len(chunks)
            })

    safe_print(f"[INFO] Prepared {len(chunk_tasks)} total chunk tasks across {len(files_to_process)} files.")
    safe_print(f"[INFO] Launching ThreadPoolExecutor with {args.workers} workers...")

    # Shared outputs dictionary: filename -> list of QA pairs
    results_by_file = defaultdict(list)
    completed_chunks_by_file = defaultdict(int)
    
    t0 = time.time()
    
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        # Submit all tasks
        future_to_task = {
            executor.submit(process_chunk_task, client, task, args.model): task 
            for task in chunk_tasks
        }
        
        for future in as_completed(future_to_task):
            task = future_to_task[future]
            fn = task["filename"]
            category = task["category"]
            
            try:
                qa_results = future.result()
                
                with results_lock:
                    results_by_file[fn].extend(qa_results)
                    completed_chunks_by_file[fn] += 1
                    
                    # If all chunks for this file are completed, save the file
                    if completed_chunks_by_file[fn] == file_chunks_count[fn]:
                        file_qa = results_by_file[fn]
                        if file_qa:
                            # Save individual JSON
                            json_filename = fn.replace(".md", ".json")
                            with open(os.path.join(JSON_OUTPUT_DIR, json_filename), "w", encoding="utf-8") as f:
                                json.dump(file_qa, f, indent=2, ensure_ascii=False)

                            # Save individual Markdown
                            md_filename = fn
                            md_content = convert_to_markdown(fn, category, file_qa)
                            with open(os.path.join(MD_OUTPUT_DIR, md_filename), "w", encoding="utf-8") as f:
                                f.write(md_content)
                                
                            nonlocal_total_questions = total_questions + len(file_qa)
                            total_questions = nonlocal_total_questions
                            
                            safe_print(f"\n[FILE COMPLETE] Saved {len(file_qa)} QA pairs for {fn} (Running Total Qs: {total_questions})")
                        
                        processed_files.append(fn)
                        save_checkpoint(processed_files, total_questions)
                        
            except Exception as exc:
                safe_print(f"  [ERROR] Task for {fn} [Chunk {task['chunk_idx']}] generated an exception: {exc}")

    duration = time.time() - t0
    safe_print(f"\n[INFO] Parallel processing finished in {duration:.1f} seconds.")
    safe_print("[INFO] Compiling master files...")
    compile_master_files()

def compile_master_files():
    all_qa = []
    
    if not os.path.exists(JSON_OUTPUT_DIR):
        safe_print("[ERROR] JSON output directory does not exist. Cannot compile master files.")
        return
        
    json_files = sorted([f for f in os.listdir(JSON_OUTPUT_DIR) if f.endswith(".json")])
    for jf in json_files:
        path = os.path.join(JSON_OUTPUT_DIR, jf)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    all_qa.extend(data)
        except Exception as e:
            safe_print(f"  [WARN] Could not load {jf} during compile: {e}")
            
    # Save master JSON
    master_json_path = os.path.join(OUTPUT_DIR, "master_qa.json")
    with open(master_json_path, "w", encoding="utf-8") as f:
        json.dump(all_qa, f, indent=2, ensure_ascii=False)
    safe_print(f"  - Wrote master JSON: {master_json_path} ({len(all_qa)} total QA pairs)")
    
    # Save master Markdown
    master_md_path = os.path.join(OUTPUT_DIR, "master_qa.md")
    with open(master_md_path, "w", encoding="utf-8") as f:
        f.write("# Consolidated MSAJCE Knowledge Base QA Pairs\n\n")
        f.write(f"Total QA Pairs: {len(all_qa)}\n\n")
        
        by_file = {}
        for qa in all_qa:
            src = qa.get("source_file", "unknown")
            if src not in by_file:
                by_file[src] = []
            by_file[src].append(qa)
            
        for src_file in sorted(by_file.keys()):
            items = by_file[src_file]
            category = items[0].get("category", "General")
            f.write(f"## Source File: `{src_file}` (Category: {category})\n\n")
            
            for idx, item in enumerate(items, 1):
                fmt = item.get("format", "general").capitalize()
                f.write(f"### Q{idx} ({fmt}) — {item.get('section', 'General')}\n")
                f.write(f"{item['question']}\n\n")
                f.write(f"**Answer**:\n{item['answer']}\n\n")
                f.write("---\n\n")
                
    safe_print(f"  - Wrote master Markdown: {master_md_path}")

if __name__ == "__main__":
    main()
