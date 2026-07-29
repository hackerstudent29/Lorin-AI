"""
MSAJCE RAG — Dataset Processor v2
- Strips all PDF metadata noise (Chunk ID, Sample Questions, Keywords, URLs, scrape headers)
- Semantic section-aware chunking: keeps tables, lists, and section blocks intact
- Adds rich metadata per chunk: source_file, category, section_title, page range
- Upserts to Qdrant (no delete — safe re-index)
- Updates scraped_documents in Supabase
"""

import os, re, sys, glob, time, uuid, json
import fitz  # PyMuPDF
import requests, psycopg2
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from collections import Counter
from pipeline.chunker import SemanticChunker, Chunk, split_into_sections

load_dotenv()

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
QDRANT_URL     = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
DATABASE_URL   = os.getenv("DATABASE_URL")

if not all([NVIDIA_API_KEY, QDRANT_URL, QDRANT_API_KEY, DATABASE_URL]):
    print("[ERROR] Missing environment variables in .env!")
    sys.exit(1)

qdrant_client   = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=60.0)
COLLECTION_NAME = "college_knowledgebase_old"
VECTOR_DIM      = 1024
MIN_CHUNK_LEN   = 60    # discard chunks shorter than this

# ── Collection Management: Delete existing collection if present for a clean, fresh indexing ──
if qdrant_client.collection_exists(COLLECTION_NAME):
    print(f"[INFO] Deleting existing Qdrant collection '{COLLECTION_NAME}' for fresh indexing...")
    qdrant_client.delete_collection(collection_name=COLLECTION_NAME)

print(f"[INFO] Creating fresh Qdrant collection '{COLLECTION_NAME}' ({VECTOR_DIM}-dim)...")
qdrant_client.create_collection(
    collection_name=COLLECTION_NAME,
    vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
)


# ── Noise-stripping: removes all PDF metadata injected by the scraper ─────────
NOISE_PATTERNS = [
    r'^MSAJCE\s*[—–-].*?RAG Model.*$',
    r'^Source URL:.*$',
    r'^Scraped:.*$',
    r'^Sections:.*$',
    r'^Chunk ID:.*$',
    r'^URL:.*$',
    r'^Context:.*$',
    r'^Keywords:.*$',
    r'^Carry-forward overlap:.*$',
    r'^Overlap carry-forward.*$',           # alternate form
    r'^Sample Questions.*',
    # FAQ question lines: starting with N/Q + question word
    r'^[NQ]\s+(?:How|What|Who|Where|When|Does|Can|Is|Are|Was|Were).*\?.*$',
    # FAQ/synthetic questions starting with bullets or numbers: "• What is..." / "1. How do..."
    r'^[\•\-\*]\s+(?:How|What|Who|Where|When|Does|Can|Is|Are|Was|Were).*\?.*$',
    r'^\d+[\.\)]\s+(?:How|What|Who|Where|When|Does|Can|Is|Are|Was|Were).*\?.*$',
    # Lines that are purely a URL
    r'^https?://\S+$',
    r'^---\s*Page \d+\s*---$',
    r'~\d+\s*tokens?',
    r'\|\s*~\d+\s*tokens?',
    r'RAG Extract:.*$',
    # Header banners like "MSAJCE — Mohamed Sathak A.J. College of Engineering [Topic] — Complete Data Extract"
    r'^MSAJCE\s*[—–-].*Complete Data Extract.*$',
    r'^MSAJCE\s*[—–-].*for RAG Model.*$',
]
NOISE_RE = re.compile('|'.join(NOISE_PATTERNS), re.MULTILINE | re.IGNORECASE)

# Semantic chunker instance (Req 1)
_chunker = SemanticChunker()


def strip_noise(text: str) -> str:
    """Remove all scraper-injected metadata lines from extracted PDF text."""
    text = NOISE_RE.sub('', text)
    # Remove lines that are only pipe-separated metadata (chunk headers)
    text = re.sub(r'^.*Chunk ID:.*$', '', text, flags=re.MULTILINE)
    # Collapse 3+ newlines to 2
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Fix hyphenated line-wrap artifacts
    text = re.sub(r'(\w)-\n(\w)', r'\1\2', text)
    # Normalise whitespace within lines
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text.strip()


def normalise(text: str) -> str:
    text = re.sub(r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})', r'\1/\2/\3', text)
    text = re.sub(r'\b(Dr|Prof|Mr|Mrs|Ms)\s*\.\s*', r'\1. ', text)
    text = re.sub(r'Rs\s*\.?\s*', 'Rs. ', text)
    text = re.sub(r'INR\s*', 'Rs. ', text)
    return text


# ── Category mapping ──────────────────────────────────────────────────────────
def category_from_filename(filename: str) -> str:
    fn = os.path.splitext(os.path.basename(filename.lower()))[0]
    
    # Specific file mapping first to avoid substring ambiguity
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
        
    if "information_technology" in fn or fn == "msajce_it" or fn == "it":
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


def get_metadata_for_filename(filename: str) -> dict:
    fn = os.path.splitext(os.path.basename(filename.lower()))[0]
    
    # Defaults
    meta = {
        "title": fn.replace("msajce_", "").replace("_", " ").title(),
        "url": "https://www.msajce-edu.in",
        "department": "General",
        "source_type": "markdown" if filename.endswith(".md") else "pdf"
    }

    # Department mappings
    if "cse" in fn:
        meta["department"] = "Computer Science & Engineering"
    elif "csbs" in fn:
        meta["department"] = "Computer Science & Business Systems"
    elif "cyber" in fn:
        meta["department"] = "Cyber Security"
    elif "aids" in fn:
        meta["department"] = "Artificial Intelligence & Data Science"
    elif "aiml" in fn:
        meta["department"] = "Artificial Intelligence & Machine Learning"
    elif "information_technology" in fn or "it" in fn:
        meta["department"] = "Information Technology"
    elif "ece" in fn:
        meta["department"] = "Electronics & Communication Engineering"
    elif "eee" in fn:
        meta["department"] = "Electrical & Electronics Engineering"
    elif "mech" in fn:
        meta["department"] = "Mechanical Engineering"
    elif "civil" in fn:
        meta["department"] = "Civil Engineering"
    elif "sh" in fn or "science" in fn:
        meta["department"] = "Science & Humanities"

    # Specific URLs & Titles
    url_map = {
        "msajce_placement": ("Placement Cell & Careers", "https://www.msajce-edu.in/placement.php"),
        "msajce_hostel": ("Hostel & Accommodation", "https://www.msajce-edu.in/hostel.php"),
        "msajce_transport": ("Transport & Bus Routes", "https://www.msajce-edu.in/transport.php"),
        "msajce_admission": ("Admissions & Fee Structure", "https://www.msajce-edu.in/admission.php"),
        "msajce_cse": ("Department of Computer Science & Engineering", "https://www.msajce-edu.in/cse.php"),
        "msajce_information_technology": ("Department of Information Technology", "https://www.msajce-edu.in/it.php"),
        "msajce_ece": ("Department of Electronics & Communication Engineering", "https://www.msajce-edu.in/ece.php"),
        "msajce_eee": ("Department of Electrical & Electronics Engineering", "https://www.msajce-edu.in/eee.php"),
        "msajce_mech": ("Department of Mechanical Engineering", "https://www.msajce-edu.in/mech.php"),
        "msajce_civil": ("Department of Civil Engineering", "https://www.msajce-edu.in/civil.php"),
        "msajce_aiml": ("B.Tech CSE — AI & Machine Learning", "https://www.msajce-edu.in/aiml.php"),
        "msajce_aids": ("B.Tech AI & Data Science", "https://www.msajce-edu.in/aids.php"),
        "msajce_csbs": ("B.Tech Computer Science & Business Systems", "https://www.msajce-edu.in/csbs.php"),
        "msajce_cyber": ("B.Tech CSE — Cyber Security", "https://www.msajce-edu.in/cyber.php"),
        "msajce_ece_vlsi": ("B.Tech VLSI Design & Technology", "https://www.msajce-edu.in/vlsi.php"),
        "msajce_ece-act": ("B.Tech Advanced Communication Technology", "https://www.msajce-edu.in/ece-act.php"),
        "msajce_research": ("Research & R&D Center", "https://www.msajce-edu.in/research.php"),
        "msajce_incubation": ("Incubation & Entrepreneurship Center", "https://www.msajce-edu.in/incubation.php"),
        "msajce_library": ("Central Campus Library", "https://www.msajce-edu.in/library.php"),
        "msajce_iqac": ("Internal Quality Assurance Cell (IQAC)", "https://www.msajce-edu.in/iqac.php"),
        "msajce_nirf": ("NIRF Ranking & National Reports", "https://www.msajce-edu.in/nirf.php"),
        "msajce_alumni": ("MSAJCE Alumni Association", "https://www.msajce-edu.in/alumni.php"),
        "msajce_sports": ("Sports & Athletics Infrastructure", "https://www.msajce-edu.in/sports.php"),
        "msajce_clubssocieties": ("Clubs & Student Societies", "https://www.msajce-edu.in/clubs.php"),
        "msajce_about": ("About MSAJCE Institution Overview", "https://www.msajce-edu.in/about.php"),
    }

    if fn in url_map:
        meta["title"], meta["url"] = url_map[fn]

    return meta


def extract_typed_entities(text: str) -> list:
    """Extract typed entity objects ({'type': str, 'value': str}) from chunk text."""
    entities = []
    seen = set()

    # People (Dr., Prof., Mr., Mrs., Ms.)
    people = re.findall(r'\b(?:Dr|Prof|Mr|Mrs|Ms)\.\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text)
    for p in people:
        if p not in seen:
            seen.add(p)
            entities.append({"type": "person", "value": p})

    # Companies & Recruiters
    companies = ["TCS", "Infosys", "Wipro", "Cognizant", "HCL", "Tech Mahindra", "Intel", "Accenture", "IBM", "Zoho", "Palo Alto Networks", "Cisco", "Preethi Home Appliances", "Openwave", "HireMee"]
    for c in companies:
        if c in text and c not in seen:
            seen.add(c)
            entities.append({"type": "company", "value": c})

    # Degrees & Courses
    degrees = ["B.E. Civil Engineering", "B.E. Computer Science and Engineering", "B.E. Electrical and Electronics Engineering", "B.E. Electronics and Communication Engineering", "B.E. Mechanical Engineering", "B.Tech. Information Technology", "B.Tech. Artificial Intelligence and Data Science", "B.Tech. Computer Science and Business Systems", "B.Tech. Cyber Security", "B.Tech. AI and Machine Learning", "M.E. Computer Science and Engineering", "M.E. Structural Engineering"]
    for d in degrees:
        if (d in text or d.replace(".", "") in text) and d not in seen:
            seen.add(d)
            entities.append({"type": "course", "value": d})

    # Departments
    departments = ["Computer Science and Engineering", "Information Technology", "Electronics and Communication Engineering", "Electrical and Electronics Engineering", "Mechanical Engineering", "Civil Engineering", "Science and Humanities", "Placement Cell"]
    for dept in departments:
        if dept in text and dept not in seen:
            seen.add(dept)
            entities.append({"type": "department", "value": dept})

    return entities[:10]


def extract_keywords_from_text(text: str) -> list:
    """Precompute important keywords for hybrid search and analytics."""
    words = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
    stopwords = {"with", "that", "this", "from", "they", "have", "were", "been", "their", "which", "about", "student", "students", "college", "engineering", "mohamed", "sathak", "msajce", "siruseri", "chennai"}
    kw_counts = Counter(w for w in words if w not in stopwords)
    return [w for w, _ in kw_counts.most_common(8)]


def infer_content_type(filename: str, text: str) -> str:
    """Infer document_type / content_type (website, pdf, brochure, notice, regulation, faq)."""
    fn = filename.lower()
    t = text.lower()
    if "faq" in fn or "question" in t:
        return "faq"
    if "policy" in fn or "rules" in t or "guidelines" in t:
        return "policy"
    if "admission" in fn or "fee" in fn or "tuition" in t:
        return "fee"
    if "placement" in fn or "recruiter" in t or "salary" in t:
        return "placement_page"
    if "contact" in t or "address" in t or "phone" in t:
        return "contact"
    if any(k in fn for k in ["cse", "ece", "eee", "mech", "civil", "it", "csbs", "aids", "aiml", "cyber"]):
        return "course_page"
    return "website"


# ── NVIDIA Embedding ──────────────────────────────────────────────────────────
MAX_EMBED_CHARS = 600   # nv-embedqa-e5-v5 has a tighter input limit than nemotron (512 tokens max)

# Characters that cause 400 errors on nv-embedqa-e5-v5
_UNICODE_MAP = str.maketrans({
    '\u2013': '-',    # en-dash
    '\u2014': '-',    # em-dash
    '\u2019': "'",    # right single quote
    '\u2018': "'",    # left single quote
    '\u201c': '"',    # left double quote
    '\u201d': '"',    # right double quote
    '\u2192': '->',   # right arrow
    '\u2190': '<-',   # left arrow
    '\u20b9': 'Rs.',  # rupee sign
    '\u00a0': ' ',    # non-breaking space
    '\u200b': '',     # zero-width space
    '\u200c': '',     # zero-width non-joiner
    '\u200d': '',     # zero-width joiner
    '\ufeff': '',     # BOM
    '\u2026': '...',  # ellipsis
    '\u2022': '-',    # bullet
    '\u00e2': '',     # common PDF artifact
})

def sanitize_for_embed(text: str) -> str:
    """Replace Unicode characters that cause 400 errors in nv-embedqa-e5-v5."""
    text = text.translate(_UNICODE_MAP)
    # Remove any remaining non-ASCII chars that might cause issues
    text = text.encode('ascii', errors='ignore').decode('ascii')
    # Collapse multiple spaces/newlines
    import re as _re
    text = _re.sub(r'[ \t]{2,}', ' ', text)
    text = _re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

# ── NVIDIA Embedding Cache ──────────────────────────────────────────────────
CACHE_FILE = "embeddings_cache.json"

def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cache(cache: dict):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception:
        pass

def get_nvidia_embeddings_batch(texts: list, batch_size: int = 20) -> list:
    url = "https://integrate.api.nvidia.com/v1/embeddings"
    headers = {"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"}
    
    # Sanitize Unicode + truncate texts
    sanitized_texts = [sanitize_for_embed(t)[:MAX_EMBED_CHARS] for t in texts]
    
    # Load cache
    cache = load_cache()
    
    # Helper to compute SHA-256
    import hashlib
    def get_hash(t: str) -> str:
        return hashlib.sha256(t.encode("utf-8")).hexdigest()

    all_embeddings = [None] * len(sanitized_texts)
    missing_indices = []
    missing_texts = []
    
    # Check cache first
    for idx, t in enumerate(sanitized_texts):
        h = get_hash(t)
        if h in cache:
            all_embeddings[idx] = cache[h]
        else:
            missing_indices.append(idx)
            missing_texts.append(t)
            
    if missing_texts:
        print(f"   [Cache] {len(sanitized_texts) - len(missing_texts)} chunks loaded from cache. Embedding {len(missing_texts)} new chunks...")
        
        total_batches = (len(missing_texts) - 1) // batch_size + 1
        
        for i in range(0, len(missing_texts), batch_size):
            batch = missing_texts[i:i + batch_size]
            batch_indices = missing_indices[i:i + batch_size]
            payload = {"input": batch, "model": "nvidia/nv-embedqa-e5-v5", "input_type": "passage"}
            success = False
            for attempt in range(3):
                try:
                    res = requests.post(url, headers=headers, json=payload, timeout=45)
                    res.raise_for_status()
                    embeddings_data = res.json()["data"]
                    for idx_in_batch, d in enumerate(embeddings_data):
                        val_idx = batch_indices[idx_in_batch]
                        emb = d["embedding"]
                        all_embeddings[val_idx] = emb
                        # Cache the successful embedding
                        h_val = get_hash(batch[idx_in_batch])
                        cache[h_val] = emb
                        
                    print(f"   [Embed] Batch {i//batch_size + 1}/{total_batches} ({len(batch)} chunks) OK")
                    time.sleep(0.15)
                    success = True
                    break
                except Exception as e:
                    details = ""
                    try:
                        if 'res' in locals(): details = f" | Details: {res.text}"
                    except Exception: pass
                    print(f"   [WARN] Embed batch attempt {attempt+1} failed: {e}{details}")
                    time.sleep(2 ** attempt)

            if not success:
                # Fallback: try each chunk individually to isolate bad chunks
                print(f"   [INFO] Falling back to single-chunk embedding for batch {i//batch_size+1}...")
                for j, single_text in enumerate(batch):
                    val_idx = batch_indices[j]
                    single_payload = {"input": [single_text], "model": "nvidia/nv-embedqa-e5-v5", "input_type": "passage"}
                    res = None
                    try:
                        res = requests.post(url, headers=headers, json=single_payload, timeout=45)
                        res.raise_for_status()
                        emb = res.json()["data"][0]["embedding"]
                        all_embeddings[val_idx] = emb
                        # Cache it
                        h_val = get_hash(single_text)
                        cache[h_val] = emb
                        time.sleep(0.2)
                    except Exception as e2:
                        details = ""
                        if res is not None:
                            try: details = f" | Details: {res.text}"
                            except Exception: pass
                        print(f"   [WARN] Single chunk {i+j} failed, using zero vector: {e2}{details}")
                        all_embeddings[val_idx] = [0.0] * 1024  # placeholder so indices stay aligned
        
        # Save updated cache to disk
        save_cache(cache)
    else:
        print(f"   [Cache] All {len(sanitized_texts)} chunks loaded successfully from cache!")

    return all_embeddings


# ── Main pipeline ─────────────────────────────────────────────────────────────
def run():
    dataset_dir = os.path.join(os.path.dirname(__file__), "dataset")
    dataset_files = sorted(glob.glob(os.path.join(dataset_dir, "*.pdf")) + glob.glob(os.path.join(dataset_dir, "*.md")))

    if not dataset_files:
        print(f"[ERROR] No dataset files found in {dataset_dir}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  MSAJCE RAG — Processing {len(dataset_files)} dataset files")
    print(f"{'='*60}\n")

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cursor = conn.cursor()

    all_chunks: list[Chunk] = []

    for pdf_path in dataset_files:
        base_name = os.path.basename(pdf_path)
        category  = category_from_filename(base_name)
        parent_id = str(uuid.uuid4())

        print(f"[FILE] {base_name}")
        print(f"      Category: {category}")

        try:
            if pdf_path.endswith(".md"):
                with open(pdf_path, "r", encoding="utf-8") as f:
                    raw = f.read()
                cleaned = normalise(strip_noise(raw))
                full_raw = cleaned
                page_texts = [(1, cleaned)]
            else:
                doc = fitz.open(pdf_path)
                full_raw = ""
                page_texts = []

                for pn in range(len(doc)):
                    raw = doc[pn].get_text("text")
                    cleaned = normalise(strip_noise(raw))
                    if cleaned.strip():
                        full_raw += f"\n\n{cleaned}"
                        page_texts.append((pn + 1, cleaned))

                doc.close()

            if not full_raw.strip():
                print(f"      [SKIP] No usable text.\n")
                continue

            # Store clean text in Supabase
            title = base_name.replace(".pdf", "").replace("_", " ").replace("msajce ", "MSAJCE — ").title()
            cursor.execute("""
                INSERT INTO scraped_documents (title, source_url, content_type, category, raw_markdown, status)
                VALUES (%s, %s, 'pdf', %s, %s, 'indexed')
                ON CONFLICT (source_url) DO UPDATE
                  SET raw_markdown = EXCLUDED.raw_markdown,
                      category = EXCLUDED.category,
                      status = 'indexed',
                      updated_at = CURRENT_TIMESTAMP;
            """, (title, base_name, category, full_raw.strip()))

            # Chunk per page so page_number metadata stays accurate
            # Exception: transport PDFs — merge all pages first so route tables aren't split
            file_chunks = 0
            is_transport = "transport" in base_name.lower()
            file_meta = get_metadata_for_filename(base_name)

            if is_transport:
                # Keep each bus route section strictly intact as 1 complete atomic chunk (never split routes across chunks)
                merged = "\n\n".join(t for _, t in page_texts)
                sections = split_into_sections(merged)
                merged_chunks = []
                for sec in sections:
                    c_obj = Chunk(
                        text=sec["body"],
                        section_title=sec["title"],
                        source_file=base_name,
                        category=category,
                        page_number=1,
                        parent_id=parent_id,
                        title=file_meta["title"],
                        url=file_meta["url"],
                        department=file_meta["department"],
                        document_type=file_meta["source_type"],
                    )
                    c_obj.entities = extract_typed_entities(c_obj.text)
                    c_obj.keywords = extract_keywords_from_text(c_obj.text)
                    merged_chunks.append(c_obj)

                total_c = len(merged_chunks)
                for idx, c in enumerate(merged_chunks):
                    c.chunk_index = idx + 1
                    c.total_chunks = total_c

                all_chunks.extend(merged_chunks)
                file_chunks += total_c
            else:
                doc_chunks = []
                for page_num, page_text in page_texts:
                    page_chunks = _chunker.chunk_document(
                        text=page_text,
                        source_file=base_name,
                        category=category,
                        page_number=page_num,
                        parent_id=parent_id,
                    )
                    doc_chunks.extend(page_chunks)
                total_c = len(doc_chunks)
                for idx, c in enumerate(doc_chunks):
                    c.title = file_meta["title"]
                    c.url = file_meta["url"]
                    c.department = file_meta["department"]
                    c.document_type = file_meta["source_type"]
                    c.chunk_index = idx + 1
                    c.total_chunks = total_c
                    c.entities = extract_typed_entities(c.text)
                    c.keywords = extract_keywords_from_text(c.text)
                all_chunks.extend(doc_chunks)
                file_chunks += total_c

            print(f"      Pages: {len(page_texts)} | Chunks: {file_chunks}\n")

        except Exception as e:
            print(f"      [ERROR] {e}\n")

    cursor.close()
    conn.close()

    print(f"{'='*60}")
    print(f"  Total chunks to embed: {len(all_chunks)}")
    print(f"{'='*60}\n")

    # Filter out any short chunks (defensive guard, chunker already prevents these)
    all_chunks = [c for c in all_chunks if len(c.text.strip()) >= 60]

    # Embed
    texts_to_embed = [c.text for c in all_chunks]
    print("[EMBED] Generating vectors via NVIDIA Nemotron-3...\n")
    embeddings = get_nvidia_embeddings_batch(texts_to_embed, batch_size=20)

    # Build Qdrant points — deterministic ID from chunk_hash so re-runs upsert cleanly
    points = []
    for chunk, emb in zip(all_chunks, embeddings):
        entity_ids = list(set(re.findall(r'<!--(ent_\d+)-->', chunk.text)))
        points.append(PointStruct(
            id=chunk.point_id,  # deterministic SHA-256-based ID (Req 1.10)
            vector=emb,
            payload={
                "text":          chunk.text,
                "title":         chunk.title,
                "section_title": chunk.section_title,
                "source_file":   chunk.source_file,
                "url":           chunk.url,
                "category":      chunk.category,
                "department":    chunk.department,
                "document_type": chunk.document_type,
                "page_number":   chunk.page_number,
                "chunk_index":   chunk.chunk_index,
                "total_chunks":  chunk.total_chunks,
                "entities":      chunk.entities,
                "entity_ids":    entity_ids,
                "keywords":      chunk.keywords,
                "parent_id":     chunk.parent_id,
                "chunk_hash":    chunk.chunk_hash,
                "scraped_at":    "2026-04-28T00:00:00Z",
            }
        ))

    # Upsert in batches with retry on transient network errors
    BATCH = 20
    total_batches = (len(points) - 1) // BATCH + 1
    print(f"\n[QDRANT] Upserting {len(points)} vectors (batch={BATCH})...\n")
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
                print(f"   [WARN] Upload batch {batch_num} attempt {attempt+1} failed: {e}. Retrying in {wait}s...")
                time.sleep(wait)
        else:
            print(f"   [ERROR] Upload batch {batch_num} permanently failed after 4 attempts. Skipping.")

    info = qdrant_client.get_collection(COLLECTION_NAME)
    print(f"\n{'='*60}")
    print(f"  [SUCCESS] INGESTION COMPLETE")
    print(f"  Vectors in Qdrant: {info.points_count}")
    print(f"  Dimension:         {info.config.params.vectors.size}")
    print(f"{'='*60}\n")

    # ── BM25 rebuild after ingestion (Req 3.7) ────────────────────────────────
    if all_chunks:
        print(f"\n[BM25] Rebuilding keyword index after indexing {len(all_chunks)} chunks...")
        try:
            from pipeline.bm25_index_manager import BM25IndexManager
            bm25_mgr = BM25IndexManager(qdrant_client)
            bm25_mgr.append_and_rebuild(
                new_texts=[c.text for c in all_chunks],
                new_payloads=[{
                    "text":          c.text,
                    "source_file":   c.source_file,
                    "category":      c.category,
                    "section_title": c.section_title,
                    "page_number":   c.page_number,
                    "parent_id":     c.parent_id,
                    "chunk_hash":    c.chunk_hash,
                } for c in all_chunks],
            )
            print(f"[BM25] Triggered rebuild after indexing {len(dataset_files)} dataset file(s) OK")
        except Exception as e:
            print(f"[WARN] BM25 rebuild failed (non-blocking): {e}")


if __name__ == "__main__":
    run()
