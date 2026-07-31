"""
MSAJCE Campus RAG API Server v3
Pipeline: SpellCorrect → Intent → Cache → QueryRewrite → HybridRetrieve
         → Rerank → FaithfulnessCheck → LLMGenerate → CacheSave
New endpoints: POST /api/feedback, POST /api/debug/rerank
"""

import os, re, logging, hashlib, json, requests, psycopg2
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from qdrant_client import QdrantClient

# ── Pipeline components ───────────────────────────────────────────────────────
from pipeline.spell_corrector      import SpellCorrector
from pipeline.bm25_index_manager   import BM25IndexManager
from pipeline.hybrid_retriever     import HybridRetriever
from pipeline.query_rewriter       import QueryRewriter
from pipeline.faithfulness_checker import FaithfulnessChecker
import rag_config
from rag_config import (
    RERANK_SCORE_THRESHOLD, RERANK_TOP_N, CATEGORY_CONFIDENCE_THRESHOLD,
    FAITHFULNESS_TRIGGER_THRESHOLD,
)

load_dotenv()

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if os.getenv("DEBUG") else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY")
QDRANT_URL     = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
DATABASE_URL   = os.getenv("DATABASE_URL")

qdrant_client   = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=30.0)
COLLECTION_NAME = "college_knowledgebase"

# ── Initialise pipeline components at startup ─────────────────────────────────
def _make_embed_fn():
    def embed(text: str) -> list:
        return get_nvidia_embedding(text, input_type="query")
    return embed

bm25_manager        = BM25IndexManager(qdrant_client)
spell_corrector     = SpellCorrector()
faithfulness_checker = FaithfulnessChecker(NVIDIA_API_KEY)

def db_connect():
    return psycopg2.connect(DATABASE_URL)

query_rewriter  = QueryRewriter(NVIDIA_API_KEY, db_conn_fn=db_connect)
hybrid_retriever = None   # initialised after app startup (needs embed_fn)

SEED_CACHE: list[dict] = [
    {
        "query": "what courses does msajce offer",
        "answer": """MSAJCE (Mohamed Sathak A.J. College of Engineering) offers the following programmes:

## 🎓 Undergraduate B.E / B.Tech Programmes

| Programme | Total Intake | Govt Quota | Mgmt Quota |
|---|---|---|---|
| Civil Engineering | 30 | 15 | 15 |
| Computer Science and Engineering (CSE) | 60 | 30 | 30 |
| Electronics and Communication Engineering (ECE) | 60 | 30 | 30 |
| Electrical and Electronics Engineering (EEE) | 30 | 15 | 15 |
| Mechanical Engineering | 30 | 15 | 15 |
| Information Technology (IT) | 60 | 30 | 30 |
| Artificial Intelligence and Data Science (AI&DS) | 60 | 30 | 30 |
| Computer Science and Business Systems (CSBS) | 30 | 15 | 15 |
| CSE (Cyber Security) | 30 | 15 | 15 |
| Artificial Intelligence and Machine Learning (AI&ML) | 60 | 30 | 30 |
| Electronics (VLSI Design and Technology) | 30 | 15 | 15 |
| ECE (Advanced Communication Technology) | 30 | 15 | 15 |
| Bachelor of Architecture | 40 | 20 | 20 |
| Bachelor of Design | 30 | 15 | 15 |

## 🎓 Postgraduate Programmes (M.E / M.Arch)

| Programme | Total Intake |
|---|---|
| Computer Science and Engineering | 9 |
| Structural Engineering | 18 |
| Master of Architecture | 15 |

## 🔬 Research Programme
- **Ph.D** in Mechanical Engineering

All programmes are approved by AICTE and affiliated to Anna University, Chennai.""",
        "citations": [{"source": "msajce_admission.md", "page": "1", "section": "Programmes Offered"}],
    },
    {
        "query": "what are the courses in msajce",
        "answer": """MSAJCE offers 14 UG programmes, 3 PG programmes and a Ph.D programme. The key UG courses are: CSE, IT, ECE, EEE, Mechanical, Civil, AI&DS, AI&ML, CSBS, Cyber Security, VLSI, ACT, B.Arch, and B.Design. For the full intake details ask: "What courses does MSAJCE offer?".""",
        "citations": [{"source": "msajce_admission.md", "page": "1", "section": "Programmes Offered"}],
    },
    {
        "query": "list of departments in msajce",
        "answer": """MSAJCE has the following departments:
1. Computer Science and Engineering (CSE)
2. Information Technology (IT)
3. Electronics and Communication Engineering (ECE)
4. Electrical and Electronics Engineering (EEE)
5. Mechanical Engineering
6. Civil Engineering
7. Artificial Intelligence and Data Science (AI&DS)
8. Artificial Intelligence and Machine Learning (AI&ML)
9. Computer Science and Business Systems (CSBS)
10. CSE (Cyber Security)
11. Science and Humanities (S&H)

Plus Architecture and Design programmes.""",
        "citations": [{"source": "msajce_admission.md", "page": "1", "section": "Programmes Offered"}],
    },
]

def seed_cache_entries():
    """Pre-populate query_cache with guaranteed correct answers for commonly failed queries."""
    try:
        conn = db_connect(); conn.autocommit = True; cur = conn.cursor()
        for entry in SEED_CACHE:
            q_hash = hashlib.sha256(entry["query"].encode()).hexdigest()
            # Only seed if no entry exists (don't overwrite self-healed answers)
            cur.execute("SELECT 1 FROM query_cache WHERE query_hash = %s", (q_hash,))
            if not cur.fetchone():
                cur.execute(
                    "INSERT INTO query_cache (query_hash, query_text, response_text, citations) VALUES (%s, %s, %s, %s)",
                    (q_hash, entry["query"], entry["answer"], json.dumps(entry["citations"]))
                )
                logger.info(f"[SeedCache] Seeded: '{entry['query']}'")
        cur.close(); conn.close()
    except Exception as e:
        logger.warning(f"[SeedCache] Failed: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    global hybrid_retriever
    logger.info("[Startup] Loading BM25 index…")
    bm25_manager.load_or_build()
    hybrid_retriever = HybridRetriever(
        bm25_mgr=bm25_manager,
        qdrant_client=qdrant_client,
        embed_fn=_make_embed_fn(),
        collection=COLLECTION_NAME,
    )
    # Warm up spell corrector (first Levenshtein call loads the C extension — can take 500ms)
    spell_corrector.correct("warmup msajce")
    # Seed critical Q&A pairs into cache so retriever failures never return blank answers
    seed_cache_entries()
    logger.info("[Startup] Pipeline ready.")
    yield

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="MSAJCE Campus RAG API v3", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "MSAJCE RAG API Server is running"}



# ── Pydantic models ───────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    bypass_cache: bool = False
    stream: bool = False

class Citation(BaseModel):
    source: str
    page: Optional[str] = None
    section: Optional[str] = None

class TokenUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class ChatResponse(BaseModel):
    answer: str
    citations: List[Citation]
    modelUsed: str
    isCached: bool
    tokenUsage: Optional[TokenUsage] = None
    message_id: Optional[str] = None   # DB UUID of the saved assistant message
    followups: List[str] = []

class FeedbackRequest(BaseModel):
    message_id: str
    session_id: str
    rating: int   # must be -1 or 1

class DebugRerankRequest(BaseModel):
    query: str
    passages: List[str]


# ── Noise stripping ───────────────────────────────────────────────────────────
NOISE_PATTERNS = [
    r'Chunk ID:.*?\n', r'URL:.*?\n', r'Context:.*?\n',
    r'Sample Questions.*?(?=\n\n|\Z)',
    r'Keywords:.*?\n', r'Carry-forward overlap:.*?\n',
    r'Overlap carry-forward.*?\n',           # alternate form
    r'--- Page \d+ ---\n?', r'~\d+ tokens?\b',
    r'Scraped:.*?\n', r'Source URL:.*?\n',
    r'MSAJCE[^.]*Complete Data Extract.*?\n',  # banner lines
]
NOISE_RE = re.compile('|'.join(NOISE_PATTERNS), re.DOTALL | re.IGNORECASE)

def clean_chunk(text: str) -> str:
    text = NOISE_RE.sub('', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ── NVIDIA helpers ────────────────────────────────────────────────────────────
def get_nvidia_embedding(text: str, input_type: str = "query") -> list:
    res = requests.post(
        "https://integrate.api.nvidia.com/v1/embeddings",
        headers={"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"},
        json={"input": [text], "model": "nvidia/nv-embedqa-e5-v5", "input_type": input_type},
        timeout=20,
    )
    res.raise_for_status()
    return res.json()["data"][0]["embedding"]


def rerank_nvidia(query: str, passages: list) -> tuple:
    """
    Returns (rankings, rerank_succeeded).
    rankings: sorted [{index, logit}]. Falls back to identity on error.
    rerank_succeeded: bool — False means we used the cosine-similarity fallback.
    """
    try:
        res = requests.post(
            "https://ai.api.nvidia.com/v1/retrieval/nvidia/llama-nemotron-rerank-1b-v2/reranking",
            headers={"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"},
            json={
                "model":    "nvidia/llama-nemotron-rerank-1b-v2",
                "query":    {"text": query},
                "passages": [{"text": p} for p in passages],
            },
            timeout=25,
        )
        res.raise_for_status()
        rankings = res.json().get("rankings", [])
        rankings = sorted(rankings, key=lambda r: r.get("logit", r.get("score", 0)), reverse=True)

        # Log all logit scores at DEBUG (Req 4.1)
        for r in rankings:
            score = r.get("logit", r.get("score", 0))
            passed = score >= RERANK_SCORE_THRESHOLD
            logger.debug(f"[Reranker] idx={r['index']} logit={score:.4f} passed={passed}")

        return rankings, True
    except Exception as e:
        logger.warning(f"[Reranker] Rerank failed (cosine fallback): {e}")
        return [{"index": i, "logit": 1.0} for i in range(len(passages))], False


def generate_followup_questions(query: str, answer: str, context_blocks: Optional[list] = None) -> List[str]:
    """Generate 3 follow-up questions based only on the query and answer to save tokens."""
    if not answer:
        return []
        
    system_prompt = (
        "You are a follow-up question generator for a college chatbot.\n"
        "Generate 3 logical follow-up questions the user might ask NEXT, based on the BOT ANSWER.\n"
        "RULES:\n"
        "1. Do NOT repeat anything already answered.\n"
        "2. Keep them short, relevant, and self-contained.\n"
        "3. Output ONLY a JSON array of 3 strings.\n"
        "Example: [\"What is the hostel fee?\", \"Where is it located?\", \"Who is the HOD?\"]"
    )
    user_prompt = (
        f"USER QUESTION: {query}\n"
        f"BOT ANSWER: {answer[:800]}\n\n"
        "Generate 3 follow-up questions (JSON array only):"
    )
    try:
        res = requests.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "meta/llama-3.1-8b-instruct",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.4,
                "max_tokens": 160
            },
            timeout=3.5,
        )
        res.raise_for_status()
        content = res.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\n?|```$", "", content, flags=re.MULTILINE).strip()
        m = re.search(r'\[.*\]', content, re.DOTALL)
        content = m.group(0) if m else content
        questions = json.loads(content)
        if isinstance(questions, list):
            return [str(q).strip().rstrip("?") + "?" for q in questions[:3] if str(q).strip()]
    except Exception as e:
        logger.warning(f"[Followups] Generation failed: {e}")
    return []


def match_entity_in_db(query_name: str) -> Optional[str]:
    """Check if the given query matches a known entity (person) in the database."""
    if not query_name or len(query_name) < 3:
        return None
    try:
        conn = db_connect(); cur = conn.cursor()
        cur.execute("SELECT entity_id, similarity FROM match_entity(%s)", (query_name,))
        row = cur.fetchone()
        cur.close(); conn.close()
        if row and row[1] is not None and row[1] >= 0.4:
            logger.info(f"[EntityMatch] Resolved '{query_name}' to {row[0]} (sim: {row[1]:.2f})")
            return row[0]
    except Exception as e:
        logger.warning(f"[EntityMatch] Failed: {e}")
    return None

def preprocess_query(query: str) -> dict:
    """Classify intent + expand keywords + infer category with confidence."""
    q = query.lower().strip("?.! ")

    greetings = {"hi","hello","hey","greetings","good morning","good afternoon","good evening","howdy"}
    goodbyes  = {"bye","goodbye","see you","exit","quit","talk to you later","cya"}
    thanks    = {"thanks","thank you","thank you so much","great","awesome","perfect","nice"}
    if q in greetings:
        return {"intent":"greeting","keywords":"","category":None,"category_confidence":0,"direct_response":"Hello! 👋 I'm Lorin, your MSAJCE campus assistant. Whether it's admissions, departments, hostel, transport, or placements — I'm here to help! What would you like to know?","usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}}
    if q in goodbyes:
        return {"intent":"goodbye","keywords":"","category":None,"category_confidence":0,"direct_response":"Goodbye! It was great chatting with you. Feel free to come back anytime you have questions about MSAJCE. Best of luck! 😊","usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}}
    if q in thanks:
        return {"intent":"compliment","keywords":"","category":None,"category_confidence":0,"direct_response":"You're welcome! Happy to help. If you have more questions about MSAJCE, just ask! 😊","usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}}

    developer_keywords = ["who is ram", "who is ramanathan", "who is zendrum", "who is the developer", "who created", "who built", "creator of", "developer of", "ur host", "your host", "who made you", "tell me about ram", "tell me about the developer"]
    if any(k in q for k in developer_keywords) or q in ["ram", "ramanathan", "zendrum", "developer", "creator"]:
        return {
            "intent": "developer_query",
            "keywords": "",
            "category": None,
            "category_confidence": 0,
            "direct_response": "I was developed by **Ramanathan S.** (B.Tech IT, MSAJCE 2024-2028 batch). He is the creator of this chatbot, Lorin AI, Listen Zenify, ZenDrum Booking, and Zen Hostel. You can learn more about him and his work at his portfolio: [https://ramanathanportfolio.vercel.app](https://ramanathanportfolio.vercel.app)",
            "usage": {"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}
        }

    # Compact category list (short labels save ~150 tokens per call)
    COMPACT_CATS = [
        "Department-CSE","Department-CSBS","Department-CyberSecurity",
        "Department-AIDS","Department-AIML","Department-IT",
        "Department-ECE","Department-EEE","Department-Mech",
        "Department-Civil","Department-S&H",
        "Alumni","Placement","Admission","Hostel","Transport",
        "Research","Incubation","TechCentre","Library",
        "IQAC","NIRF","Sports","Clubs","ProfSocieties","General",
    ]
    category_list_str = ", ".join(COMPACT_CATS)
    system_prompt = (
        "MSAJCE chatbot classifier. Classify intent: 'greeting'|'goodbye'|'compliment'|'guidance_query'|'college_query'.\n"
        "For college_query: extract core search keywords (strip honorifics sir/maam/dr/mr/mrs). "
        "Set category=null when asking about a person/staff.\n"
        f"Categories: {category_list_str}\n"
        'JSON only: {"intent":"...","keywords":"...","category":null,"category_confidence":0.0,"direct_response":""}'
    )
    try:
        res = requests.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"},
            json={"model":"meta/llama-3.1-8b-instruct",
                  "messages":[{"role":"system","content":system_prompt},{"role":"user","content":query}],
                  "temperature":0.0,"max_tokens":150},
            timeout=15,
        )
        res.raise_for_status()
        rj = res.json()
        raw = rj["choices"][0]["message"]["content"].strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\n?|```$", "", raw, flags=re.MULTILINE).strip()
        # Extract JSON object from response (in case model adds surrounding text)
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        raw = m.group(0) if m else raw
        # Remove unescaped control characters which cause json decode errors
        raw = re.sub(r'[\x00-\x1F\x7F]', '', raw)
        data = json.loads(raw)
        data["usage"] = rj.get("usage", {"prompt_tokens":0,"completion_tokens":0,"total_tokens":0})
        return data
    except Exception as e:
        logger.warning(f"[Preprocess] Failed: {e}")
        return {"intent":"college_query","keywords":query,"category":None,"category_confidence":0,"direct_response":"","usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}}


def generate_guidance_answer(user_query: str, context_blocks: list) -> tuple:
    """
    For guidance_query: combine LLM general knowledge + relevant MSAJCE context.
    Used for career advice, field exploration, 'which course suits me' type questions.
    """
    # Build MSAJCE context if any relevant chunks were found
    msajce_context = ""
    if context_blocks:
        ctx_parts = []
        for blk in context_blocks:
            sec = blk.get("section_title", "")
            cat = blk.get("category", "")
            if sec and sec != "Overview":
                ctx_parts.append(f"[{cat} — {sec}]\n{blk['text']}")
            else:
                ctx_parts.append(f"[{cat}]\n{blk['text']}")
        msajce_context = "\n\n---\n\n".join(ctx_parts)

    system_prompt = f"""You are Lorin, the friendly AI assistant and campus guide for Mohamed Sathak A.J. College of Engineering (MSAJCE), Chennai.

The user is asking for guidance, career advice, or has a general academic question. Answer using BOTH your general knowledge AND any relevant MSAJCE information below.

YOUR APPROACH:
1. First, answer the general question helpfully using your knowledge (career guidance, field explanation, etc.)
2. Then, naturally connect it to what MSAJCE offers — mention relevant programmes, departments, or facilities if applicable
3. Be warm and encouraging — like a senior student giving honest advice
4. If MSAJCE doesn't offer something the user is interested in (e.g., Civil Engineering), honestly say so and suggest the closest available programmes

MSAJCE RELEVANT INFO (use if applicable, skip if not relevant):
{msajce_context if msajce_context else "No specific MSAJCE data found for this query."}

FORMAT: Use clear Markdown with ## headings. Keep it concise but helpful.
NEVER mention "sources", "documents", "chunks", or internal references.
"""
    try:
        res = requests.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"},
            json={"model": "meta/llama-3.1-8b-instruct",
                  "messages": [{"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_query}],
                  "temperature": 0.3, "max_tokens": 1000},
            timeout=30,
        )
        res.raise_for_status()
        rj = res.json()
        return rj["choices"][0]["message"]["content"].strip(), rj.get("usage", {})
    except Exception as e:
        logger.error(f"[LLM-Guidance] Generation failed: {e}")
        raise


# Keywords that indicate the answer will likely be a long list/table
_TABLE_SIGNALS = [
    "route", "bus", "timing", "schedule", "all course", "all department",
    "list all", "fee structure", "fee detail", "subjects", "syllabus",
    "placement statistic", "companies", "recruiters", "transport",
]

def _pick_max_tokens(user_query: str, context_blocks: list) -> int:
    """Return an appropriate max_tokens budget based on query and context size."""
    q = user_query.lower()
    ctx_chars = sum(len(b.get("text", "")) for b in context_blocks)
    if any(sig in q for sig in _TABLE_SIGNALS) or ctx_chars > 2500:
        return 2000   # Tables, long lists, multi-topic queries
    if ctx_chars < 500 or len(user_query.split()) <= 6:
        return 600    # Short factual answers
    return 1000       # Default


def get_recent_history(session_id: str, max_turns: int = 4) -> list:
    """
    Fetch the last N turns of conversation for a session to give the LLM memory context.
    Returns a list of {role, content} dicts (oldest first, suitable for LLM messages array).
    """
    if not session_id:
        return []
    try:
        conn = db_connect(); conn.autocommit = True; cur = conn.cursor()
        cur.execute("""
            SELECT role, content FROM chat_messages
            WHERE session_id = %s::uuid
            ORDER BY created_at DESC
            LIMIT %s
        """, (session_id, max_turns * 2 + 1))
        rows = cur.fetchall()
        cur.close(); conn.close()
        # Skip the most recent user message (current query — already passed as user_query)
        turns = []
        skipped = False
        for role, content in rows:
            if not skipped and role == "user":
                skipped = True
                continue
            # Smart-truncate long assistant answers to save tokens
            if role == "assistant" and len(content) > 500:
                content = content[:250].strip() + " ... " + content[-150:].strip()
            turns.append({"role": role, "content": content})
            if len(turns) >= max_turns * 2:
                break
        return list(reversed(turns))  # oldest first
    except Exception as e:
        logger.warning(f"[History] Failed to fetch: {e}")
        return []


def generate_answer(user_query: str, context_blocks: list, session_id: str = "") -> tuple:
    ctx_parts = []
    for i, blk in enumerate(context_blocks, 1):
        section  = blk.get("section_title", "")
        category = blk.get("category", "")
        label = f"[{category}" + (f" — {section}" if section and section != "Overview" else "") + "]"
        ctx_parts.append(f"{label}\n{blk['text']}")
    context_str = "\n\n---\n\n".join(ctx_parts)

    max_tok = _pick_max_tokens(user_query, context_blocks)

    system_prompt = f"""You are Lorin, the official AI assistant for Mohamed Sathak A.J. College of Engineering (MSAJCE), Chennai.

RULES:
1. Answer directly and concisely using facts from SOURCES. State the main key answer (e.g. intake count, fee amount, exact date, link, or location) clearly upfront.
2. For multi-item lists, routes, or full course catalogs: follow the direct answer with a complete markdown table. CRITICAL: Always use standard markdown table format and ensure each row (including headers, separators, and data lines) ends with a literal newline (\n). Never output a table on a single line or with spaces replacing the newlines.
3. Never cite internal source file labels, page numbers, or raw snippet markers in the answer text.
4. CRITICAL — Numbers & figures: Only state a number (salary, intake, cutoff, fee) if it is LITERALLY written in the SOURCES below. Never infer or estimate.
5. Salary ranges from domain/career sections (e.g. "industry average Rs. 25 LPA") are NOT placement package facts — never present them as MSAJCE placement data.
6. Missing info → "I couldn't find details about [topic] in college records. Contact: +91 99400 04500 or msajce.office@gmail.com."
7. AMBIGUOUS QUERIES: If the user asks for a department-level item or position (e.g., "HOD name", "syllabus", "fees") without specifying the department, ask the user which department they are interested in (e.g., CSE, ECE, IT, AI&DS, AI&ML, Civil, Mech, EEE, CSBS) or provide a list of available department options. Never arbitrarily select a random department.
8. DEVELOPER & CREATOR ATTRIBUTION: If the user asks who created, built, or developed this chatbot, Lorin AI, Listen Zenify, ZenDrum Booking, or Zen Hostel, OR asks about "developer", "ram", "ramanathan", or "zendrum", identify **Ramanathan S.** (B.Tech IT, MSAJCE 2024-2028 batch) as the developer and ONLY tell them about Ramanathan. Do not confuse him with any other person. (Link: https://ramanathanportfolio.vercel.app)
9. LINKS & URLS: Whenever a website link, official page URL, PDF download link, email address, or phone number is LITERALLY present in the SOURCES below, you MUST explicitly include the exact clickable link in your answer formatted as `[Link Title](https://...)` or plain URL. CRITICAL: Never invent, guess, or hallucinate links (such as LinkedIn profiles or external websites) that are NOT explicitly written in the SOURCES! If a link is not in the SOURCES, do not include a link.
10. IMAGES & VISUAL MEDIA: If the user asks to see images, photos, or facilities, OR if image/media URLs (such as `.jpg`, `.png`, `.jpeg`, `.gif`) are present in the SOURCES for the requested topic (like sports, campus, labs, gym, events), you MUST include those image links in your answer formatted as markdown images: `![Image Description](image_url)` so they render visually in the chat!
11. TRANSPORT QUERIES (COLLEGE BUS VS MTC BUS): When a user asks how to travel/reach the college from a specific area, or which bus goes to/passes through a specific stop:
    - You MUST prioritize and check the COLLEGE BUSES (AR 3, AR 4, N/3, AR 6, AR 7, AR 8, AR 9, AR 10, R 22) first.
    - If a college bus route stops at or near that place, state the College Bus Route number, departure time, and driver contact info.
    - Mention MTC (public state transport) buses (such as 102, 105, 570, 221H, B19) only as secondary/alternative options.
    - NEVER suggest MTC state transport as the primary option if a college bus route is available for that location.
12. STRICT GROUNDING ON STOPS & LOCATIONS: Never assume, infer, or hallucinate that a bus route passes through a location or stop unless that location/stop is EXPLICITLY listed in the SOURCES for that specific route. For example, if a route lists 'Adyar at 7:00 AM', do not claim it passes through 'Velachery' at 7:00 AM. Only mention routes that explicitly contain the user's requested stop/location in their route description in the SOURCES.




SOURCES:
{context_str}
"""

    # Build messages: system prompt + prior history turns + current question
    history_msgs = get_recent_history(session_id) if session_id else []
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history_msgs)
    messages.append({"role": "user", "content": user_query})

    try:
        res = requests.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"},
            json={"model":"meta/llama-3.1-8b-instruct",
                  "messages": messages,
                  "temperature":0.1,"max_tokens":max_tok},
            timeout=30,
        )
        res.raise_for_status()
        rj = res.json()
        return rj["choices"][0]["message"]["content"].strip(), rj.get("usage",{})
    except Exception as e:
        logger.error(f"[LLM] Generation failed: {e}")
        return "I couldn't generate an answer due to a backend timeout. Please try again.", {}



def generate_answer_stream(user_query: str, context_blocks: list):
    ctx_parts = []
    for i, blk in enumerate(context_blocks, 1):
        section  = blk.get("section_title", "")
        category = blk.get("category", "")
        label = f"[{category}" + (f" — {section}" if section and section != "Overview" else "") + "]"
        ctx_parts.append(f"{label}\n{blk['text']}")
    context_str = "\n\n---\n\n".join(ctx_parts)

    max_tok = _pick_max_tokens(user_query, context_blocks)

    system_prompt = f"""You are Lorin, the official AI assistant for Mohamed Sathak A.J. College of Engineering (MSAJCE), Chennai.

RULES:
1. Answer directly and concisely using facts from SOURCES. State the main key answer (e.g. intake count, fee amount, exact date, link, or location) clearly upfront.
2. For multi-item lists, routes, or full course catalogs: follow the direct answer with a complete markdown table. CRITICAL: Always use standard markdown table format and ensure each row (including headers, separators, and data lines) ends with a literal newline (\n). Never output a table on a single line or with spaces replacing the newlines.
3. Never cite internal source file labels, page numbers, or raw snippet markers in the answer text.
4. CRITICAL — Numbers & figures: Only state a number (salary, intake, cutoff, fee) if it is LITERALLY written in the SOURCES below. Never infer or estimate.
5. Salary ranges from domain/career sections (e.g. "industry average Rs. 25 LPA") are NOT placement package facts — never present them as MSAJCE placement data.
6. Missing info → "I couldn't find details about [topic] in college records. Contact: +91 99400 04500 or msajce.office@gmail.com."
7. AMBIGUOUS QUERIES: If the user asks for a department-level item or position (e.g., "HOD name", "syllabus", "fees") without specifying the department, ask the user which department they are interested in (e.g., CSE, ECE, IT, AI&DS, AI&ML, Civil, Mech, EEE, CSBS) or provide a list of available department options. Never arbitrarily select a random department.
8. DEVELOPER & CREATOR ATTRIBUTION: If the user asks who created, built, or developed this chatbot, Lorin AI, Listen Zenify, ZenDrum Booking, or Zen Hostel, OR asks about "developer", "ram", "ramanathan", or "zendrum", identify **Ramanathan S.** (B.Tech IT, MSAJCE 2024-2028 batch) as the developer and ONLY tell them about Ramanathan. Do not confuse him with any other person. (Link: https://ramanathanportfolio.vercel.app)
9. LINKS & URLS: Whenever a website link, official page URL, PDF download link, email address, or phone number is LITERALLY present in the SOURCES below, you MUST explicitly include the exact clickable link in your answer formatted as `[Link Title](https://...)` or plain URL. CRITICAL: Never invent, guess, or hallucinate links (such as LinkedIn profiles or external websites) that are NOT explicitly written in the SOURCES! If a link is not in the SOURCES, do not include a link.
10. IMAGES & VISUAL MEDIA: If the user asks to see images, photos, or facilities, OR if image/media URLs (such as `.jpg`, `.png`, `.jpeg`, `.gif`) are present in the SOURCES for the requested topic (like sports, campus, labs, gym, events), you MUST include those image links in your answer formatted as markdown images: `![Image Description](image_url)` so they render visually in the chat!
11. TRANSPORT QUERIES (COLLEGE BUS VS MTC BUS): When a user asks how to travel/reach the college from a specific area, or which bus goes to/passes through a specific stop:
    - You MUST prioritize and check the COLLEGE BUSES (AR 3, AR 4, N/3, AR 6, AR 7, AR 8, AR 9, AR 10, R 22) first.
    - If a college bus route stops at or near that place, state the College Bus Route number, departure time, and driver contact info.
    - Mention MTC (public state transport) buses (such as 102, 105, 570, 221H, B19) only as secondary/alternative options.
    - NEVER suggest MTC state transport as the primary option if a college bus route is available for that location.
12. STRICT GROUNDING ON STOPS & LOCATIONS: Never assume, infer, or hallucinate that a bus route passes through a location or stop unless that location/stop is EXPLICITLY listed in the SOURCES for that specific route. For example, if a route lists 'Adyar at 7:00 AM', do not claim it passes through 'Velachery' at 7:00 AM. Only mention routes that explicitly contain the user's requested stop/location in their route description in the SOURCES.




SOURCES:
{context_str}
"""
    import json
    try:
        res = requests.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"},
            json={"model":"meta/llama-3.1-8b-instruct",
                  "messages":[{"role":"system","content":system_prompt},
                               {"role":"user","content":user_query}],
                  "temperature":0.1,"max_tokens":max_tok, "stream": True},
            timeout=30,
            stream=True
        )
        res.raise_for_status()
        
        for line in res.iter_lines():
            if line:
                line_str = line.decode('utf-8')
                if line_str.startswith("data: ") and line_str != "data: [DONE]":
                    try:
                        data = json.loads(line_str[6:])
                        if data.get("choices") and "delta" in data["choices"][0]:
                            content = data["choices"][0]["delta"].get("content", "")
                            if content:
                                yield {"type": "content", "content": content}
                        if data.get("usage"):
                            yield {"type": "usage", "usage": data["usage"]}
                    except Exception:
                        pass
    except Exception as e:
        logger.error(f"[LLM] Streaming failed: {e}")
        yield {"type": "error", "content": "Error generating response."}
def save_message(session_id: Optional[str], role: str, content: str, metadata: dict = None, prompt_tokens: int = 0, completion_tokens: int = 0, citations: list = None) -> Optional[str]:
    """Save a chat message and return its UUID. Auto-creates session row if needed."""
    if not session_id:
        return None
    try:
        conn = db_connect(); conn.autocommit = True; cur = conn.cursor()
        # Ensure session row exists (upsert) so FK constraint passes
        cur.execute("""
            INSERT INTO chat_sessions (id, user_id, session_title)
            VALUES (%s::uuid, 'anonymous', 'Chat Session')
            ON CONFLICT (id) DO NOTHING
        """, (session_id,))
        cur.execute("""
            INSERT INTO chat_messages (session_id, role, content, metadata, prompt_tokens, completion_tokens, citations)
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (session_id, role, content, json.dumps(metadata or {}), prompt_tokens, completion_tokens, json.dumps(citations or [])))
        msg_id = str(cur.fetchone()[0])
        cur.close(); conn.close()
        return msg_id
    except Exception as e:
        logger.warning(f"[DB] save_message failed: {e}")
        return None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/chat/history/{session_id}")
def get_chat_history(session_id: str):
    """Retrieve chat history with feedback status for a given session."""
    try:
        conn = db_connect()
        cur = conn.cursor()
        cur.execute("""
            SELECT m.id, m.role, m.content, m.citations, m.prompt_tokens, m.completion_tokens, m.created_at, m.metadata, f.rating
            FROM chat_messages m
            LEFT JOIN message_feedback f ON m.id = f.message_id
            WHERE m.session_id = %s::uuid
            ORDER BY m.created_at ASC
        """, (session_id,))
        rows = cur.fetchall()
        cur.close()
        conn.close()

        history = []
        for row in rows:
            msg_id = str(row[0])
            role = row[1]
            content = row[2]
            citations = row[3] or []
            prompt_tokens = row[4] or 0
            completion_tokens = row[5] or 0
            created_at = int(row[6].timestamp() * 1000) if row[6] else 0
            metadata = row[7] or {}
            rating = row[8]

            feedback_state = "none"
            if rating == 1:
                feedback_state = "thumbs_up"
            elif rating == -1:
                feedback_state = "thumbs_down"

            if isinstance(citations, str):
                try:
                    citations = json.loads(citations)
                except Exception:
                    citations = []

            # Determine model used
            model_used = metadata.get("model_used")
            if not model_used:
                if metadata.get("intent") == "intent-classifier":
                    model_used = "intent-classifier"
                elif metadata.get("from_cache"):
                    model_used = "cache"
                else:
                    model_used = "meta/llama-3.1-8b-instruct"

            is_cached = metadata.get("from_cache", False)

            history.append({
                "id": msg_id,
                "role": role,
                "content": content,
                "createdAt": created_at,
                "citations": citations,
                "modelUsed": model_used,
                "isCached": is_cached,
                "tokenUsage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens
                },
                "message_id": msg_id,
                "feedbackState": feedback_state,
                "followups": metadata.get("followups", [])
            })
        return history
    except Exception as e:
        logger.error(f"[History] Failed to retrieve history for session {session_id}: {e}")
        raise HTTPException(500, detail=str(e))


@app.delete("/api/cache/clear")
def clear_cache(query_text: Optional[str] = Query(default=None)):
    try:
        conn = db_connect(); conn.autocommit = True; cur = conn.cursor()
        if query_text:
            h = hashlib.sha256(query_text.lower().encode()).hexdigest()
            cur.execute("DELETE FROM query_cache WHERE query_hash=%s", (h,))
        else:
            cur.execute("DELETE FROM query_cache")
        deleted = cur.rowcount
        cur.close(); conn.close()
        return {"status":"ok","deleted":deleted}
    except Exception as e:
        raise HTTPException(500, str(e))


def process_feedback_correction(message_id: str, session_id: str, rating: int):
    """
    Background worker triggered when negative feedback (-1) is received.
    Uses an LLM Judge to evaluate if dislike is due to a real QA/Factual mismatch or user fun.
    If a real QA mismatch is found, it performs fresh hybrid search, synthesizes a ground-truth answer,
    purges bad cache entries, updates query_cache, and records the audit log in feedback_correction_log.
    """
    if rating != -1:
        return

    try:
        conn = db_connect()
        conn.autocommit = True
        cur = conn.cursor()

        # Create audit table if it does not exist
        cur.execute("""
            CREATE TABLE IF NOT EXISTS feedback_correction_log (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                message_id UUID NOT NULL,
                session_id UUID NOT NULL,
                user_query TEXT,
                original_answer TEXT,
                verdict VARCHAR(50),
                reason TEXT,
                corrected_answer TEXT,
                cache_updated BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Fetch the assistant message
        cur.execute("""
            SELECT content, metadata FROM chat_messages WHERE id = %s::uuid
        """, (message_id,))
        assistant_row = cur.fetchone()
        if not assistant_row:
            cur.close(); conn.close()
            return

        original_answer, metadata = assistant_row[0], assistant_row[1] or {}

        # Fetch the previous user query in the session
        cur.execute("""
            SELECT content FROM chat_messages 
            WHERE session_id = %s::uuid AND role = 'user' AND created_at <= (
                SELECT created_at FROM chat_messages WHERE id = %s::uuid
            )
            ORDER BY created_at DESC LIMIT 1
        """, (session_id, message_id))
        user_row = cur.fetchone()
        user_query = user_row[0] if user_row else ""

        if not user_query:
            cur.close(); conn.close()
            return

        logger.info(f"[Self-Healing] Analyzing 👎 feedback for query: '{user_query[:50]}'")

        # Step 1: LLM Evaluator (Judge) prompt
        judge_prompt = f"""You are an objective AI evaluator analyzing negative user feedback.
User Question: "{user_query}"
Assistant Answer: "{original_answer}"

Evaluate if the assistant answer has a genuine factual error, hallucination, or QA mismatch relative to the user question.

Respond ONLY with valid JSON matching this schema:
{{
  "verdict": "REAL_QA_MISMATCH" or "USER_DISSATISFACTION_OR_FUN",
  "reason": "Short 1-sentence explanation of your verdict."
}}
"""
        judge_res = requests.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "meta/llama-3.1-8b-instruct",
                "messages": [{"role": "user", "content": judge_prompt}],
                "temperature": 0.1
            },
            timeout=20
        )
        judge_res.raise_for_status()
        raw_judge = judge_res.json()["choices"][0]["message"]["content"].strip()
        if "```" in raw_judge:
            raw_judge = re.sub(r"^```(?:json)?", "", raw_judge, flags=re.MULTILINE)
            raw_judge = re.sub(r"```$", "", raw_judge, flags=re.MULTILINE).strip()
        
        judge_data = json.loads(raw_judge)
        verdict = judge_data.get("verdict", "USER_DISSATISFACTION_OR_FUN")
        reason = judge_data.get("reason", "No reason provided")

        corrected_answer = None
        cache_updated = False

        # Step 2: Self-Correction if REAL_QA_MISMATCH
        if verdict == "REAL_QA_MISMATCH":
            logger.info(f"[Self-Healing] Real QA mismatch detected! Correcting query: '{user_query[:50]}'")
            
            # Fetch fresh hybrid context
            candidates = hybrid_retriever.retrieve(user_query, user_query, category=None) if hybrid_retriever else []
            if candidates:
                context_blocks = []
                citations = []
                for i, c in enumerate(candidates[:6]):
                    if isinstance(c, dict):
                        text = clean_chunk(c.get("text", "") or c.get("payload", {}).get("text", ""))
                        payload = c.get("payload", {})
                        source_val = payload.get("source_file", payload.get("source", "MSAJCE"))
                        page_val = str(payload.get("page_number", payload.get("page", "")))
                        sec_val = payload.get("section_title", payload.get("section", ""))
                        cat_val = payload.get("category", "")
                    else:
                        text = clean_chunk(str(c))
                        source_val, page_val, sec_val, cat_val = "MSAJCE", "", "", ""
                    if text:
                        context_blocks.append({"text": text, "section_title": sec_val, "category": cat_val})
                        citations.append({"source": source_val, "page": page_val, "section": sec_val})

                # Synthesize high-accuracy ground truth answer
                corrected_answer, _ = generate_answer(user_query, context_blocks)

                # Purge old cache entry and store corrected answer
                query_hash = hashlib.sha256(user_query.lower().encode()).hexdigest()
                cur.execute("DELETE FROM query_cache WHERE query_hash = %s", (query_hash,))
                
                citations_json = json.dumps(citations)
                cur.execute("""
                    INSERT INTO query_cache (query_hash, query_text, response_text, citations)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (query_hash) DO UPDATE
                        SET response_text = EXCLUDED.response_text,
                            citations = EXCLUDED.citations,
                            created_at = CURRENT_TIMESTAMP
                """, (query_hash, user_query.lower(), corrected_answer, citations_json))
                cache_updated = True
                logger.info(f"[Self-Healing] Updated cache with corrected answer for '{user_query[:50]}'")

        # Step 3: Log audit trail
        cur.execute("""
            INSERT INTO feedback_correction_log (message_id, session_id, user_query, original_answer, verdict, reason, corrected_answer, cache_updated)
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s)
        """, (message_id, session_id, user_query, original_answer, verdict, reason, corrected_answer, cache_updated))

        cur.close()
        conn.close()

    except Exception as e:
        logger.error(f"[Self-Healing] Failed to process feedback correction: {e}")


@app.post("/api/feedback")
@limiter.limit("10/minute")
def feedback_endpoint(req: FeedbackRequest, background_tasks: BackgroundTasks, request: Request):
    """Thumbs up/down feedback on an assistant message with self-healing correction."""
    # Validate rating before any DB call (Req 9.4)
    if req.rating not in rag_config.FEEDBACK_VALID_RATINGS:
        raise HTTPException(422, detail={"error": "rating must be -1 or 1"})

    try:
        conn = db_connect(); conn.autocommit = True; cur = conn.cursor()

        # Check message exists (Req 9.3)
        cur.execute("SELECT id FROM chat_messages WHERE id = %s", (req.message_id,))
        if not cur.fetchone():
            cur.close(); conn.close()
            raise HTTPException(404, detail={"error": "message not found"})

        # Upsert — allow changing rating (Req 9.7)
        cur.execute("""
            INSERT INTO message_feedback (message_id, session_id, rating)
            VALUES (%s::uuid, %s::uuid, %s)
            ON CONFLICT (message_id) DO UPDATE
                SET rating = EXCLUDED.rating,
                    created_at = CURRENT_TIMESTAMP
        """, (req.message_id, req.session_id, req.rating))

        cur.close(); conn.close()
        logger.info(f"[Feedback] message={req.message_id} rating={req.rating}")

        # Trigger self-healing background evaluator on negative rating (-1)
        if req.rating == -1:
            background_tasks.add_task(process_feedback_correction, req.message_id, req.session_id, req.rating)

        return {"status": "ok", "self_healing_triggered": req.rating == -1}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Feedback] DB error: {e}")
        raise HTTPException(500, str(e))



@app.get("/api/admin/stats")
def admin_stats():
    """Retrieve high-level statistics for the admin dashboard."""
    try:
        conn = db_connect(); cur = conn.cursor()
        
        # Total Queries
        cur.execute("SELECT COUNT(*) FROM chat_messages WHERE role = 'user'")
        total_queries = cur.fetchone()[0] or 0
        
        # Cache Hits
        cur.execute("SELECT SUM(hit_count) FROM query_cache")
        cache_hits = cur.fetchone()[0] or 0
        
        # Feedback Stats
        cur.execute("SELECT COUNT(*) FROM message_feedback WHERE rating = 1")
        thumbs_up = cur.fetchone()[0] or 0
        
        cur.execute("SELECT COUNT(*) FROM message_feedback WHERE rating = -1")
        thumbs_down = cur.fetchone()[0] or 0
        
        cur.close(); conn.close()
        
        return {
            "total_queries": total_queries,
            "cache_hits": cache_hits,
            "feedback": {
                "thumbs_up": thumbs_up,
                "thumbs_down": thumbs_down
            }
        }
    except Exception as e:
        logger.error(f"[Admin] Stats query failed: {e}")
        raise HTTPException(500, str(e))
@app.get("/api/feedback/log")
def get_feedback_correction_log():
    """Retrieve self-healing feedback correction audit logs."""
    try:
        conn = db_connect(); cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS feedback_correction_log (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                message_id UUID NOT NULL,
                session_id UUID NOT NULL,
                user_query TEXT,
                original_answer TEXT,
                verdict VARCHAR(50),
                reason TEXT,
                corrected_answer TEXT,
                cache_updated BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            SELECT id, message_id, session_id, user_query, original_answer, verdict, reason, corrected_answer, cache_updated, created_at
            FROM feedback_correction_log
            ORDER BY created_at DESC LIMIT 50
        """)
        rows = cur.fetchall()
        cur.close(); conn.close()

        logs = []
        for r in rows:
            logs.append({
                "id": str(r[0]),
                "message_id": str(r[1]),
                "session_id": str(r[2]),
                "user_query": r[3],
                "original_answer": r[4],
                "verdict": r[5],
                "reason": r[6],
                "corrected_answer": r[7],
                "cache_updated": r[8],
                "created_at": r[9].isoformat() if r[9] else None
            })
        return {"logs": logs}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/debug/rerank")
def debug_rerank(req: DebugRerankRequest):
    """Raw reranker diagnostic endpoint (Req 4.4)."""
    if not req.passages:
        raise HTTPException(400, detail="passages list cannot be empty")
    if len(req.passages) > 100:
        raise HTTPException(400, detail="passages list cannot exceed 100 items")

    logger.info(f"[DebugRerank] query='{req.query[:60]}' passages={len(req.passages)}")
    try:
        res = requests.post(
            "https://ai.api.nvidia.com/v1/retrieval/nvidia/llama-nemotron-rerank-1b-v2/reranking",
            headers={"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"},
            json={
                "model":    "nvidia/llama-nemotron-rerank-1b-v2",
                "query":    {"text": req.query},
                "passages": [{"text": p} for p in req.passages],
            },
            timeout=25,
        )
        res.raise_for_status()
        rankings = res.json().get("rankings", [])
        return {
            "query": req.query,
            "results": [
                {
                    "passage": req.passages[r["index"]],
                    "index":   r["index"],
                    "logit":   r.get("logit", r.get("score", 0)),
                }
                for r in rankings
            ]
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/chat")
@limiter.limit("10/minute;25/day")
def chat_endpoint(req: ChatRequest, request: Request):
    user_query = req.message.strip()
    if not user_query:
        raise HTTPException(400, "Query cannot be empty.")

    # ── Step 0a: Exact Cache lookup (bypasses all LLM processing) ─────────────
    q_hash = hashlib.sha256(user_query.lower().encode()).hexdigest()
    if not getattr(req, "bypass_cache", False):
        try:
            conn = db_connect(); conn.autocommit = True; cur = conn.cursor()
            cur.execute("SELECT response_text, citations FROM query_cache WHERE query_hash=%s", (q_hash,))
            row = cur.fetchone()
            if row:
                cur.execute("UPDATE query_cache SET hit_count=hit_count+1, last_accessed=CURRENT_TIMESTAMP WHERE query_hash=%s", (q_hash,))
                cur.close(); conn.close()
                cits = json.loads(row[1]) if isinstance(row[1], str) else (row[1] or [])
                save_message(req.session_id, "user", user_query)
                cached_msg_id = save_message(req.session_id, "assistant", row[0], {"from_cache": True})
                return ChatResponse(answer=row[0], citations=cits,
                                    modelUsed="cache", isCached=True,
                                    tokenUsage=TokenUsage(prompt_tokens=0,completion_tokens=0,total_tokens=0),
                                    message_id=cached_msg_id)
            cur.close(); conn.close()
        except Exception as e:
            logger.warning(f"[Cache] Lookup failed: {e}")

    # ── Step 0b: Spell correction (skip for very short queries) ───────────────
    if len(user_query.split()) <= 2:
        # Short queries like "hi", "hello", "bye" — don't spell-correct, run intent first
        corrected_query, corrections = user_query, []
    else:
        corrected_query, corrections = spell_corrector.correct(user_query)
    if corrections:
        logger.debug(f"[SpellCorrector] corrections={corrections}")

    # ── Step 1: Save user message & Query rewriting for multi-turn context ──────
    save_message(req.session_id, "user", user_query, {
        "corrected_query": corrected_query if corrected_query != user_query else None,
    })

    # Fetch simple history check to decide whether to rewrite (Req 6)
    history_msgs = get_recent_history(req.session_id, max_turns=1) if req.session_id else []
    has_history = len(history_msgs) > 0

    active_query = corrected_query
    was_rewritten = False
    prep = None

    if has_history:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            fut_rewrite = executor.submit(query_rewriter.rewrite, corrected_query, req.session_id)
            fut_prep = executor.submit(preprocess_query, corrected_query)
            
            rewritten_query, was_rewritten = fut_rewrite.result()
            prep = fut_prep.result()
            
        if was_rewritten:
            active_query = rewritten_query
            prep["keywords"] = active_query
    else:
        prep = preprocess_query(corrected_query)

    # ── Step 2: Intent + keyword expansion on active_query ──────────────────────
    intent    = prep.get("intent", "college_query")
    keywords  = prep.get("keywords") or active_query
    # Strip honorifics: sir, maam, mam, mr, mrs, dr from keywords
    keywords  = re.sub(r"\b(sir|maam|mam|mr|mrs|dr|professor|prof)\b", "", keywords, flags=re.IGNORECASE).strip()
    if not keywords: keywords = active_query
    # Person name fuzzy boost: if keywords looks like a single short name, also search first-name only prefix
    kw_words = keywords.split()
    if len(kw_words) == 1 and len(kw_words[0]) >= 4:
        # Expand with partial name for fuzzy retrieval (e.g. "weslin" → "weslin wesley")
        name_prefix = kw_words[0][:4].lower()
        keywords = f"{keywords} {name_prefix} faculty staff"
        logger.debug(f"[PersonSearch] Single-name query — expanded keywords: '{keywords}'")
    p_usage   = prep.get("usage", {})
    category  = prep.get("category")
    cat_conf  = float(prep.get("category_confidence", 0))

    # Only use category filter if confidence meets threshold
    if cat_conf < CATEGORY_CONFIDENCE_THRESHOLD:
        category = None

    # Greetings/goodbyes/compliments/developer: return instantly, skip cache entirely
    if intent in ("greeting", "goodbye", "compliment", "developer_query"):
        ans = prep.get("direct_response", "Hello!")
        msg_id = save_message(req.session_id, "assistant", ans, {"intent": intent})
        return ChatResponse(
            answer=ans,
            citations=[], modelUsed="intent-classifier", isCached=False,
            tokenUsage=TokenUsage(**{k: p_usage.get(k,0) for k in ("prompt_tokens","completion_tokens","total_tokens")}),
            message_id=msg_id,
        )

    # ── Guidance query: career advice + general knowledge + MSAJCE context ────
    if intent == "guidance_query":
        # Still retrieve MSAJCE-relevant chunks to supplement the answer
        try:
            if hybrid_retriever:
                candidates = hybrid_retriever.retrieve(active_query, keywords, category=None)
            else:
                q_vec = get_nvidia_embedding(keywords or active_query, input_type="query")
                if hasattr(qdrant_client, "query_points"):
                    r_pts = qdrant_client.query_points(collection_name=COLLECTION_NAME, query=q_vec, limit=10, with_payload=True)
                    hits = r_pts.points
                else:
                    hits = qdrant_client.search(collection_name=COLLECTION_NAME, query_vector=q_vec, limit=10)
                candidates = [{"text": h.payload.get("text",""), "payload": h.payload} for h in hits if h.payload.get("text","")]
        except Exception as e:
            logger.warning(f"[Guidance] Retrieval failed: {e}")
            candidates = []

        # Build context blocks from top candidates (no reranking needed for guidance)
        context_blocks = []
        citations_list = []
        seen = set()
        for c in candidates[:6]:
            text = clean_chunk(c.get("text","") or c["payload"].get("text",""))
            if not text or len(text) < 30:
                continue
            th = hashlib.md5(text.encode()).hexdigest()
            if th in seen: continue
            seen.add(th)
            payload = c.get("payload", {})
            context_blocks.append({"text": text, "section_title": payload.get("section_title",""), "category": payload.get("category","")})
            citations_list.append({"source": payload.get("source_file","MSAJCE"), "page": str(payload.get("page_number","")), "section": payload.get("section_title","")})

        answer, g_usage = generate_guidance_answer(active_query, context_blocks)
        followups = generate_followup_questions(active_query, answer, context_blocks)
        msg_id = save_message(req.session_id, "assistant", answer, {"intent": "guidance_query", "followups": followups})

        total_p = p_usage.get("prompt_tokens",0) + g_usage.get("prompt_tokens",0)
        total_c = p_usage.get("completion_tokens",0) + g_usage.get("completion_tokens",0)
        total_t = p_usage.get("total_tokens",0) + g_usage.get("total_tokens",0)

        return ChatResponse(
            answer=answer,
            citations=[Citation(**c) for c in citations_list],
            modelUsed="meta/llama-3.1-8b-instruct",
            isCached=False,
            tokenUsage=TokenUsage(prompt_tokens=total_p, completion_tokens=total_c, total_tokens=total_t),
            message_id=msg_id,
            followups=followups,
        )

    retrieval_query = active_query  # use rewritten active_query for embedding/BM25

    # Transport Query Booster: If user asks about buses, routes, timings, or Chennai stops, force category to null & enrich search terms
    transport_keywords = [
        "bus", "route", "stop", "timing", "velachery", "guindy", "kathipara", "tharamani", "medavakkam", 
        "pallikaranai", "thoraipakkam", "ennore", "porur", "nemilichery", "uthiramerur", "moolakadai", 
        "icf", "chunambedu", "tambaram", "adyar", "saidapet", "broadway", "central", "parrys", 
        "perambur", "retteri", "padi", "ashok pillar", "poonnamalle", "sholinganallur", "kelambakkam", 
        "sipcot", "maraimalai nagar", "guduvanchery", "perungalathur", "vandalur", "chrompet", 
        "pallavaram", "thiruvanmiyur", "neelankarai", "akkarai", "perumpakkam", "kilkattalai", 
        "madipakkam", "kovilampakkam", "transport", "travel"
    ]
    is_transport_q = any(k in active_query.lower() for k in transport_keywords)
    if is_transport_q:
        category = None
        keywords = f"{keywords} college bus route transport timings stops"

    # Entity Resolution (Req 2.9)
    # If the user is asking about a person, attempt to resolve them to an entity_id
    entity_id = None
    if intent == "college_query":
        # Check the extracted keywords (which have honorifics stripped) against our Supabase entity registry
        matched_entity = match_entity_in_db(keywords)
        if matched_entity:
            entity_id = matched_entity
            # If we matched a specific person, force category to None so we don't accidentally filter out their cross-department chunks
            category = None

    # ── Step 4: Hybrid retrieval (BM25 + dense + RRF) ────────────────────────
    try:
        if hybrid_retriever is None:
            raise RuntimeError("HybridRetriever not initialised")
        candidates = hybrid_retriever.retrieve(retrieval_query, keywords, category, entity_id)
        candidates = [c for c in candidates if c.get("payload", {}).get("source_file") != "msajce_all_resource_links.md"]
        passages   = [c["text"] for c in candidates]
        payloads   = [c["payload"] for c in candidates]
    except Exception as e:
        logger.warning(f"[HybridRetriever] Failed, using dense-only fallback: {e}")
        try:
            q_vec = get_nvidia_embedding(keywords, input_type="query")
            if hasattr(qdrant_client, "query_points"):
                r = qdrant_client.query_points(collection_name=COLLECTION_NAME, query=q_vec, limit=25, with_payload=True)
                hits = r.points
            else:
                hits = qdrant_client.search(collection_name=COLLECTION_NAME, query_vector=q_vec, limit=25)
            hits = [h for h in hits if h.payload.get("source_file") != "msajce_all_resource_links.md"]
            passages = [h.payload.get("text","") for h in hits]
            payloads = [h.payload for h in hits]
            candidates = [{"text": p, "payload": pl} for p, pl in zip(passages, payloads)]
        except Exception as e2:
            logger.error(f"[Dense] Fallback failed: {e2}")
            return ChatResponse(
                answer="I couldn't find relevant information. Please contact MSAJCE at +91 99400 04500.",
                citations=[], modelUsed="rag", isCached=False,
                tokenUsage=TokenUsage(**{k: p_usage.get(k,0) for k in ("prompt_tokens","completion_tokens","total_tokens")}),
            )

    if not passages:
        return ChatResponse(
            answer="I couldn't find relevant information. Please contact MSAJCE at +91 99400 04500.",
            citations=[], modelUsed="rag", isCached=False,
            tokenUsage=TokenUsage(**{k: p_usage.get(k,0) for k in ("prompt_tokens","completion_tokens","total_tokens")}),
        )

    # ── Step 5: Re-rank ───────────────────────────────────────────────────────
    rerank_query = active_query
    rankings, rerank_used = rerank_nvidia(rerank_query, passages)

    # Filter by score threshold; if all below threshold, keep context empty so LLM doesn't see irrelevant noise
    top = [r for r in rankings[:RERANK_TOP_N * 2] if r.get("logit", r.get("score", 1.0)) >= RERANK_SCORE_THRESHOLD][:RERANK_TOP_N]
    if not top:
        logger.info(f"[Reranker] All candidates below threshold ({RERANK_SCORE_THRESHOLD}) — passing empty context to prevent noise fallback.")

    max_logit = max((r.get("logit", r.get("score", 0)) for r in top), default=0.0)

    # ── Step 5b: Build context blocks ─────────────────────────────────────────
    context_blocks = []
    citations_list = []
    context_str_parts = []
    seen_hashes = set()

    for rank in top:
        idx = rank["index"]
        if idx >= len(payloads):
            continue
        payload = payloads[idx]
        text = clean_chunk(payload.get("text", ""))
        if not text or len(text) < 30:
            continue
        th = hashlib.md5(text.encode()).hexdigest()
        if th in seen_hashes:
            continue
        seen_hashes.add(th)

        context_blocks.append({
            "text":          text,
            "section_title": payload.get("section_title", ""),
            "category":      payload.get("category", ""),
        })
        context_str_parts.append(text)
        citations_list.append({
            "source":  payload.get("source_file", "College Handbook"),
            "page":    str(payload.get("page_number", "")),
            "section": payload.get("section_title", ""),
        })

    if not top:
        citations_list = []

    # ── Step 6: LLM generation ────────────────────────────────────────────────
    
    if getattr(req, "stream", False):
        # Define the streaming generator
        def event_stream():
            try:
                answer_text = ""
                g_usage = {}
                for chunk in generate_answer_stream(user_query, context_blocks):
                    if chunk["type"] == "content":
                        answer_text += chunk["content"]
                        yield f"data: {json.dumps({'type': 'content', 'text': chunk['content']})}\n\n"
                    elif chunk["type"] == "usage":
                        g_usage = chunk["usage"]

                # Now that generation is done, generate followups and save to DB
                followups_val = generate_followup_questions(user_query, answer_text, context_blocks=None)
                
                total_p = p_usage.get("prompt_tokens",0) + g_usage.get("prompt_tokens",0)
                total_c = p_usage.get("completion_tokens",0) + g_usage.get("completion_tokens",0)
                
                msg_id_val = save_message(req.session_id, "assistant", answer_text, trace, prompt_tokens=total_p, completion_tokens=total_c, citations=citations_list)
                
                # Cache it
                try:
                    conn = db_connect(); conn.autocommit = True; cur = conn.cursor()
                    cur.execute("""
                        INSERT INTO query_cache (query_hash, query_text, response_text, citations)
                        VALUES (%s,%s,%s,%s) ON CONFLICT (query_hash) DO NOTHING
                    """, (q_hash, corrected_query, answer_text, json.dumps(citations_list)))
                    cur.close(); conn.close()
                except Exception:
                    pass
                
                # Send final metadata
                yield f"data: {json.dumps({'type': 'metadata', 'citations': citations_list, 'followups': followups_val, 'message_id': msg_id_val, 'tokenUsage': {'prompt_tokens': total_p, 'completion_tokens': total_c, 'total_tokens': total_p + total_c}})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")
    answer, g_usage = generate_answer(user_query, context_blocks, session_id=req.session_id)

    # ── Step 6b: Faithfulness check (conditional on low confidence) ───────────
    context_for_check = "\n\n".join(context_str_parts)
    should_replace, faith_invoked, faith_passed = faithfulness_checker.check(
        answer, context_for_check, max_logit
    )
    if (should_replace and not top) or not context_blocks:
        answer = faithfulness_checker.fallback_message
        citations_list = []

    # ── Step 7: Save assistant message + trace ────────────────────────────────
    followups = generate_followup_questions(user_query, answer, context_blocks=None)
    trace = {
        "spell_corrections":         corrections,
        "was_rewritten":             was_rewritten,
        "original_query":            corrected_query,
        "rewritten_query":           rewritten_query if was_rewritten else None,
        "category_filter":           category,
        "category_confidence":       cat_conf,
        "rrf_count":                 len(candidates),
        "max_rerank_logit":          max_logit,
        "rerank_used":               rerank_used,
        "faithfulness_check_invoked": faith_invoked,
        "faithfulness_passed":        faith_passed,
        "bypass_cache":              req.bypass_cache,
        "followups":                 followups,
    }
    total_p = p_usage.get("prompt_tokens",0) + g_usage.get("prompt_tokens",0)
    total_c = p_usage.get("completion_tokens",0) + g_usage.get("completion_tokens",0)
    total_t = p_usage.get("total_tokens",0) + g_usage.get("total_tokens",0)

    if not top or answer == faithfulness_checker.fallback_message:
        citations_list = []

    msg_id = save_message(req.session_id, "assistant", answer, trace, prompt_tokens=total_p, completion_tokens=total_c, citations=citations_list)

    # ── Step 8: Cache result ──────────────────────────────────────────────────
    try:
        conn = db_connect(); conn.autocommit = True; cur = conn.cursor()
        cur.execute("""
            INSERT INTO query_cache (query_hash, query_text, response_text, citations)
            VALUES (%s,%s,%s,%s) ON CONFLICT (query_hash) DO NOTHING
        """, (q_hash, corrected_query, answer, json.dumps(citations_list)))
        cur.close(); conn.close()
    except Exception as e:
        logger.warning(f"[Cache] Save failed: {e}")

    return ChatResponse(
        answer=answer,
        citations=[Citation(**c) for c in citations_list],
        modelUsed="meta/llama-3.1-8b-instruct",
        isCached=False,
        tokenUsage=TokenUsage(prompt_tokens=total_p, completion_tokens=total_c, total_tokens=total_t),
        message_id=msg_id,
        followups=followups,
    )


if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("api_server:app", host="::", port=port, reload=False)
