"""
MSAJCE RAG Testset Generator (Ragas integration)

Generates synthetic evaluation questions (Single-hop, Multi-hop, Specific vs Abstract)
from the dataset markdown files, wrapping them to match the expected format of run_eval.py.

Usage:
  python eval/generate_testset.py [--count N] [--files FILE1,FILE2 | all] [--output FILE] [--no-merge]
"""
import os
import sys
import json
import re
import argparse
from types import ModuleType

# ── Monkeypatch to bypass Ragas import bug in newer LangChain versions ────────
mock_vertex = ModuleType("langchain_community.chat_models.vertexai")
mock_vertex.ChatVertexAI = None
sys.modules["langchain_community.chat_models.vertexai"] = mock_vertex

import requests
import typing as t
import asyncio
from dotenv import load_dotenv
from openai import OpenAI
from langchain_core.documents import Document
from ragas.llms import llm_factory
from ragas.embeddings.base import BaseRagasEmbeddings
from ragas.run_config import RunConfig
from ragas.testset import TestsetGenerator

# Load environment
load_dotenv()
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")


# ── Custom Embeddings Wrapper ─────────────────────────────────────────────────
class NvidiaRagasEmbeddings(BaseRagasEmbeddings):
    """
    Custom Ragas Embeddings wrapper that correctly routes requests to NVIDIA's API,
    passing the model-required input_type parameter for asymmetric embeddings.
    """
    def __init__(self, api_key: str, model_name: str = "nvidia/nv-embedqa-e5-v5"):
        super().__init__()
        self.api_key = api_key
        self.model_name = model_name
        self.url = "https://integrate.api.nvidia.com/v1/embeddings"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        self.run_config = RunConfig()

    def embed_documents(self, texts: t.List[str]) -> t.List[t.List[float]]:
        payload = {
            "input": texts,
            "model": self.model_name,
            "input_type": "passage"
        }
        res = requests.post(self.url, headers=self.headers, json=payload, timeout=30)
        res.raise_for_status()
        return [item["embedding"] for item in res.json()["data"]]

    def embed_query(self, text: str) -> t.List[float]:
        payload = {
            "input": [text],
            "model": self.model_name,
            "input_type": "query"
        }
        res = requests.post(self.url, headers=self.headers, json=payload, timeout=30)
        res.raise_for_status()
        return res.json()["data"][0]["embedding"]

    async def aembed_documents(self, texts: t.List[str]) -> t.List[t.List[float]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.embed_documents, texts)

    async def aembed_query(self, text: str) -> t.List[float]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.embed_query, text)


# ── Category mapping (mirrors process_dataset.py) ────────────────────────────
def category_from_filename(filename: str) -> str:
    """Derive the dataset category from its filename."""
    fn = os.path.splitext(os.path.basename(filename.lower()))[0]
    exact_mappings = {
        "msajce_cse": "Department — Computer Science & Engineering",
        "msajce_csbs": "Department — CS & Business Systems",
        "msajce_cyber": "Department — CS & Cyber Security",
        "msajce_aids": "Department — AI & Data Science",
        "msajce_aiml": "Department — AI & Machine Learning",
        "msajce_information_technology": "Department — Information Technology",
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
        "msajce_technology_centres": "Technology Centre",
        "msajce_library": "Library",
        "msajce_iqac": "IQAC & Accreditation",
        "msajce_nirf": "NIRF Ranking",
        "msajce_sports": "Sports & Athletics",
        "msajce_clubssocieties": "Clubs & Societies",
        "msajce_professional_societies": "Professional Societies",
        "msajce_about": "About MSAJCE",
    }
    if fn in exact_mappings:
        return exact_mappings[fn]
    if "information_technology" in fn or fn == "msajce_it":
        return "Department — Information Technology"
    if "cyber" in fn:
        return "Department — CS & Cyber Security"
    if "csbs" in fn:
        return "Department — CS & Business Systems"
    if "aiml" in fn:
        return "Department — AI & Machine Learning"
    if "aids" in fn:
        return "Department — AI & Data Science"
    if "cse" in fn:
        return "Department — Computer Science & Engineering"
    if "ece" in fn:
        return "Department — Electronics & Communication"
    if "eee" in fn:
        return "Department — Electrical & Electronics"
    if "mech" in fn:
        return "Department — Mechanical Engineering"
    if "civil" in fn:
        return "Department — Civil Engineering"
    return "General — MSAJCE"


# ── Helpers ───────────────────────────────────────────────────────────────────
def check_has_exact_identifier(question: str) -> bool:
    """Identify if the question asks about an exact code, amount, or bus route name."""
    q_lower = question.lower()
    if re.search(r'\bar\s*\d+', q_lower):
        return True
    if re.search(r'\b(cutoff|cut-off|code|number|capacity|tnea|fee|rupees|rs\.?)\b', q_lower):
        return True
    return False


def find_source_metadata(
    contexts: t.List[str],
    docs: t.List[Document],
    default_file: str = "msajce_about.pdf",
    default_category: str = "About MSAJCE",
) -> t.Tuple[str, str]:
    """Find the matching source file and category from the reference contexts."""
    if not contexts:
        return default_file, default_category

    first_ctx = contexts[0].strip()
    snippet = first_ctx[:80]

    for doc in docs:
        if snippet in doc.page_content:
            src = doc.metadata.get("source", default_file)
            cat = doc.metadata.get("category", default_category)
            return src, cat

    return default_file, default_category


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="MSAJCE RAG Testset Generator")
    parser.add_argument("--count",    type=int, default=10,
                        help="Number of questions to generate (default: 10)")
    parser.add_argument("--files",    type=str, default=None,
                        help="Comma-separated filenames or 'all' (default: core files)")
    parser.add_argument("--output",   type=str, default="eval/eval_dataset.json",
                        help="Output JSON dataset path (default: eval/eval_dataset.json)")
    parser.add_argument("--no-merge", action="store_true",
                        help="Overwrite instead of merging into existing dataset")
    args = parser.parse_args()

    if not NVIDIA_API_KEY:
        print("[ERROR] NVIDIA_API_KEY is not set. Check your environment.", file=sys.stderr)
        sys.exit(1)

    dataset_dir = "dataset"
    if not os.path.exists(dataset_dir):
        print(f"[ERROR] Dataset directory not found: {dataset_dir}", file=sys.stderr)
        sys.exit(1)

    # ── File selection ────────────────────────────────────────────────────────
    all_files = sorted([f for f in os.listdir(dataset_dir) if f.endswith(".md")])
    selected_files = []

    if args.files == "all":
        selected_files = all_files
    elif args.files:
        for f in [x.strip() for x in args.files.split(",")]:
            if not f.endswith(".md"):
                f += ".md"
            if f in all_files:
                selected_files.append(f)
            else:
                print(f"[WARN] File not found in dataset: {f}")
    else:
        # High-value default files covering core chatbot domains
        default_files = [
            "msajce_hostel.md", "msajce_admission.md", "msajce_placement.md",
            "msajce_transport.md", "msajce_about.md",
        ]
        selected_files = [f for f in default_files if f in all_files]
        if not selected_files:
            selected_files = all_files[:5]

    if not selected_files:
        print("[ERROR] No valid dataset files selected.", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  MSAJCE Ragas Testset Generator")
    print(f"  Files:    {len(selected_files)} — {', '.join(selected_files)}")
    print(f"  Target:   {args.count} questions")
    print(f"  Output:   {args.output}")
    print(f"  Mode:     {'overwrite' if args.no_merge else 'merge'}")
    print(f"{'='*60}\n")

    # ── Load LangChain Documents ──────────────────────────────────────────────
    docs = []
    for fn in selected_files:
        path = os.path.join(dataset_dir, fn)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        cat = category_from_filename(fn)
        docs.append(Document(page_content=content, metadata={"source": fn, "category": cat}))
    print(f"[LOAD] Loaded {len(docs)} documents ({sum(len(d.page_content) for d in docs):,} chars)")

    # ── Setup Ragas with rate-limit protection ──────────────────────────────────
    print("[INIT] Connecting to NVIDIA model endpoints...")
    import httpx
    import time as _time

    # Use httpx transport with automatic retry on 429/5xx
    transport = httpx.HTTPTransport(retries=5)
    http_client = httpx.Client(transport=transport, timeout=120.0)

    client = OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=NVIDIA_API_KEY,
        http_client=http_client,
        max_retries=5,        # OpenAI SDK-level retries with backoff on 429
        timeout=120.0,
    )

    # Use meta/llama-3.1-70b-instruct for high-quality structured outputs
    generator_llm = llm_factory("meta/llama-3.1-70b-instruct", client=client)
    embeddings = NvidiaRagasEmbeddings(api_key=NVIDIA_API_KEY)

    # Monkey-patch the LLM's generate to add a per-call delay (rate limit guard)
    _original_generate = generator_llm.client.chat.completions.create.__wrapped__ \
        if hasattr(generator_llm.client.chat.completions.create, '__wrapped__') \
        else None

    _call_count = [0]
    def _throttled_generate_wrapper(original_fn):
        """Wrap the LLM generate call with a 2-second delay to prevent 429."""
        import functools
        @functools.wraps(original_fn)
        def wrapper(*args, **kwargs):
            _call_count[0] += 1
            if _call_count[0] > 1:
                _time.sleep(2.0)  # 2s delay between calls
            try:
                return original_fn(*args, **kwargs)
            except Exception as e:
                if "429" in str(e) or "Too Many Requests" in str(e):
                    print(f"  [THROTTLE] 429 hit, backing off 30s...")
                    _time.sleep(30.0)
                    return original_fn(*args, **kwargs)
                raise
        return wrapper

    # Patch at the instructor level if available
    try:
        original_create = generator_llm.client.chat.completions.create
        generator_llm.client.chat.completions.create = _throttled_generate_wrapper(original_create)
        print("[INIT] Rate-limit throttle installed (2s per call, 30s backoff on 429).")
    except Exception as e:
        print(f"[WARN] Could not install throttle wrapper: {e}")

    generator = TestsetGenerator(llm=generator_llm, embedding_model=embeddings)
    print("[INIT] TestsetGenerator ready.")

    # ── Generate ──────────────────────────────────────────────────────────────
    run_cfg = RunConfig(
        max_workers=1,       # Sequential API calls
        max_retries=10,      # More retries
        max_wait=180,
        timeout=600,
    )
    print(f"[RUN]  Generating {args.count} synthetic samples (throttled, max_workers=1)...")
    testset = generator.generate_with_langchain_docs(
        docs, testset_size=args.count, run_config=run_cfg
    )
    df = testset.to_pandas()
    print(f"[RUN]  Ragas returned {len(df)} samples.")

    # ── Post-process into eval_dataset format ─────────────────────────────────
    new_samples = []
    for _, row in df.iterrows():
        question = str(row.get("user_input", "")).strip()
        expected = str(row.get("reference", "")).strip()
        contexts = row.get("reference_contexts", [])
        if isinstance(contexts, str):
            contexts = [contexts]

        if not question or not expected:
            continue

        src, cat = find_source_metadata(contexts, docs)
        has_id = check_has_exact_identifier(question)

        new_samples.append({
            "question": question,
            "expected_answer": expected,
            "category": cat,
            "source_file": src,
            "has_exact_identifier": has_id,
        })

    print(f"[POST] {len(new_samples)} valid samples after post-processing.")

    # ── Save / Merge ──────────────────────────────────────────────────────────
    output_data = []
    if not args.no_merge and os.path.exists(args.output):
        try:
            with open(args.output, "r", encoding="utf-8") as f:
                output_data = json.load(f)
            print(f"[MERGE] Loaded {len(output_data)} existing questions from {args.output}")
        except Exception as e:
            print(f"[WARN] Could not load existing dataset: {e}")

    existing_questions = {item["question"].strip().lower() for item in output_data}
    merged = 0
    for item in new_samples:
        q_key = item["question"].strip().lower()
        if q_key not in existing_questions:
            output_data.append(item)
            existing_questions.add(q_key)
            merged += 1

    if args.no_merge:
        output_data = new_samples
        merged = len(new_samples)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*60}")
    print(f"  [SUCCESS] TESTSET GENERATION COMPLETE")
    print(f"  New questions synthesized : {len(new_samples)}")
    print(f"  Merged (deduplicated)     : {merged}")
    print(f"  Total dataset size        : {len(output_data)}")
    print(f"  Output                    : {args.output}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
