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
from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny

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
VERCEL_AI_GATEWAY_KEY = os.getenv("AI_GATEWAY_API_KEY")
QDRANT_URL     = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
DATABASE_URL   = os.getenv("DATABASE_URL")

LLM_SYSTEM_PROMPT = """You are Lorin, the official AI assistant for Mohamed Sathak A.J. College of Engineering (MSAJCE), Chennai.

RULES:
1. Answer directly and concisely using facts from SOURCES. State the main key answer (e.g. intake count, exact date, link, or location) clearly upfront.
2. FORMATTING MULTI-ITEM LISTS & TABLES: Whenever you output lists of programmes, eligibility criteria by category, bus routes, schedules, or any other structured lists of items, you MUST format them as standard markdown tables.
   - CRITICAL: Every single row of the table (including the header, separator, and data rows) MUST end with a literal newline (\n).
   - NEVER output a table on a single line or with spaces instead of newlines.
   - Do NOT use plain text lists, tab-separated values, or bullet points for structured data.
3. Never cite internal source file labels, page numbers, or raw snippet markers in the answer text.
4. CRITICAL — Numbers & figures: Only state a number (salary, intake, cutoff) if it is LITERALLY written in the SOURCES below. Never infer or estimate.
5. Salary ranges from domain/career sections (e.g. "industry average Rs. 25 LPA") are NOT placement package facts — never present them as MSAJCE placement data.
6. Missing info → "I couldn't find details about [topic] in college records. Contact: +91 99400 04500 or msajce.office@gmail.com."
7. AMBIGUOUS QUERIES: If the user asks for a department-level item or position (e.g., "HOD name", "syllabus") without specifying the department, ask the user which department they are interested in (e.g., CSE, ECE, IT, AI&DS, AI&ML, Civil, Mech, EEE, CSBS) or provide a list of available department options. Never arbitrarily select a random department.
8. DEVELOPER & CREATOR ATTRIBUTION: If the user asks who created, built, or developed this chatbot, Lorin AI, Listen Zenify, ZenDrum Booking, or Zen Hostel, OR asks about "developer", "ram", "ramanathan", or "zendrum", identify **Ramanathan S.** (B.Tech IT, MSAJCE 2024-2028 batch) as the developer and ONLY tell them about Ramanathan. Do not confuse him with any other person. (Link: https://ramanathanportfolio.vercel.app)
9. LINKS & URLS: Whenever a website link, official page URL, PDF download link, email address, or phone number is LITERALLY present in the SOURCES below, you MUST explicitly include the exact clickable link in your answer formatted as `[Link Title](https://...)` or plain URL. CRITICAL: Never invent, guess, or hallucinate links (such as LinkedIn profiles or external websites) that are NOT explicitly written in the SOURCES! If a link is not in the SOURCES, do not include a link.
10. IMAGES & VISUAL MEDIA: If the user asks to see images, photos, or facilities, OR if image/media URLs (such as `.jpg`, `.png`, `.jpeg`, `.gif`) are present in the SOURCES for the requested topic (like sports, campus, labs, gym, events), you MUST include those image links in your answer formatted as markdown images: `![Image Description](image_url)` so they render visually in the chat!
11. TRANSPORT QUERIES (COLLEGE BUS VS MTC BUS): When a user asks how to travel/reach the college from a specific area, or which bus goes to/passes through a specific stop:
    - You MUST prioritize and check the COLLEGE BUSES (AR 3, AR 4, N/3, AR 6, AR 7, AR 8, AR 9, AR 10, R 22) first.
    - If a college bus route stops at or near that place, state the College Bus Route number, departure time, and driver details (never personal phone numbers).
    - Mention MTC (public state transport) buses (such as 102, 105, 570, 221H, B19) only as secondary/alternative options.
    - NEVER suggest MTC state transport as the primary option if a college bus route is available for that location.
12. STRICT GROUNDING ON STOPS & LOCATIONS: Never assume, infer, or hallucinate that a bus route passes through a location or stop unless that location/stop is EXPLICITLY listed in the SOURCES for that specific route (substring matches like 'Velachery Check Post' or 'Velachery Bypass' matching 'Velachery' are completely valid college bus stops; you should list them as college bus routes). For example, if a route lists 'Adyar at 7:00 AM', do not claim it passes through 'Velachery' at 7:00 AM. Only mention routes that explicitly contain the user's requested stop/location (or a close substring/variant like Check Post) in their route description in the SOURCES. IF THE REQUESTED LOCATION (e.g. 'Guindy Station') IS NOT EXPLICITLY LISTED IN ANY BUS ROUTE IN THE SOURCES, YOU MUST DECLARE: "I couldn't find a direct college bus route for [Location]." Do not suggest nearby routes unless you explicitly state they do not go there.
13. COLLEGE BUS ROUTES FORMATTING: Whenever you output details of a college bus route (e.g., Route AR 3, Route AR 4, etc.) or stops/timings, you MUST format the list of stops and timings as a standard markdown table with columns like `| Stop / Landmark | Arrival Time |`. Do not describe the route stops in a paragraph, sentence, or simple list. Above the table, state the driver name and start/departure details clearly. Do NOT output any personal phone number of the driver.
    EXAMPLE:
    | Stop / Landmark | Arrival Time |
    |---|---|
    | Ennore | 6:15 AM |
    | Mint | 6:20 AM |
14. FEES / TUITION COST ENQUIRIES: Under NO circumstances should you disclose or output any specific tuition fee, hostel fee, transport fee, or exam fee figures or tables. If the user asks about fees, you MUST refuse to state any amounts and strictly redirect them to the Admission Department (+91 99400 04500 / msajce.office@gmail.com) or Head of Admission Dr. K. P. Santhosh Nathan (ped.santhosh@msajce-edu.in).
15. STRICT NO PERSONAL PHONE NUMBERS RULE: Under no circumstances are you allowed to output or disclose the personal phone number of any faculty member, coordinator, teacher, bus driver, or worker of the college (even if specifically requested). You MUST strictly hide personal phone numbers and only provide their official email address if available in the SOURCES, or direct the user to the official general college office phone (+91 99400 04500) and email (msajce.office@gmail.com).
16. COURSES OFFERED BY MSAJCE: If the user asks for the list of courses or programmes offered by the college (UG/undergraduate or PG/postgraduate/ME/Master of Engineering):
    - You must ONLY list the courses explicitly stated in the sources as being offered by MSAJCE.
    - Under no circumstances should you list subject names, general career specialisation options (e.g. from civil/mechanical career guidance sections), or courses offered by other colleges (e.g. from alumni higher education records of other institutions) as courses offered by MSAJCE.
    - Ground truth:
      - MSAJCE offers exactly 12 B.E./B.Tech UG courses: Civil Engineering, Computer Science and Engineering, Electronics and Communication Engineering, Electrical and Electronics Engineering, Mechanical Engineering, Information Technology, Artificial Intelligence and Data Science, Computer Science and Business Systems, Computer Science and Engineering in Cyber Security, Artificial Intelligence and Machine Learning, Electronics Engineering with specialisation in VLSI Design and Technology, and ECE with specialisation in Advanced Communication Technology.
      - MSAJCE also offers Bachelor of Architecture (B.Arch) and Bachelor of Design (B.Des) at the UG level.
      - MSAJCE offers exactly 2 M.E. courses: M.E. in Computer Science and Engineering, and M.E. in Structural Engineering. It also offers Master of Architecture (M.Arch) at the PG level.
      - MSAJCE offers exactly 1 Ph.D. research programme: Ph.D. in Mechanical Engineering.
    - Only output information about these specific courses when asked about courses offered by MSAJCE. Do not list any other hallucinated or general courses.
17. ORTHOGRAPHIC SPELLING CONFUSION: Vepery (North Chennai) and Velachery (South Chennai) are completely different places. Route AR 4 goes to Vepery. Do not mix them up. For Velachery, only refer to routes that explicitly list Velachery (such as College Bus Routes N/3 and R 22, or MTC public buses). Similarly, Pallikarani and Pallikaranai are the same place; Route AR 8 passes through Pallikarani, so treat it as a valid match.

CRITICAL INSTRUCTION: You MUST use Markdown Tables (`| Col 1 | Col 2 |`) for ANY list, including lists of buses that go to a specific location (e.g. `| Bus Route | Departure |`). Under NO circumstances use bullet points or plain text lists for structured data.

SOURCES:
{context_str}
"""
qdrant_client   = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=30.0)
COLLECTION_NAME = "college_knowledgebase"

try:
    qdrant_client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="source_file",
        field_schema="keyword"
    )
except Exception as e:
    pass

try:
    qdrant_client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="category",
        field_schema="keyword"
    )
except Exception as e:
    pass

try:
    qdrant_client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="entity_ids",
        field_schema="keyword"
    )
except Exception as e:
    pass

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
        "query": "nearest companies from msajce",
        "answer": """**Mohamed Sathak A.J. College of Engineering (MSAJCE)** is located on a sprawling 70-acre campus right inside the **SIPCOT IT Park, Siruseri**. Because of this strategic location, the college is surrounded by over a hundred leading multinational IT industries.

### 🏢 Companies surrounding MSAJCE
As per official college records, the campus is in the immediate vicinity of major tech giants including:
- **TCS (Tata Consultancy Services)**
- **CTS (Cognizant Technology Solutions)**
- **Infosys**
- **HCL Technologies**
- **Intellect Design Arena**
- **Aspire Systems**
- **Steria**
- **Polaris Software Lab**
- **FSS (Financial Software and Systems)**

### 🌐 Other Major Companies in Siruseri IT Park
Since the college is inside the IT Park, it is also close to other major companies operating there, such as:
- **Capgemini**
- **Hexaware Technologies**
- **Atos Syntel**
- **Sify Technologies** (New data center)
- **Equinix** (New facility)

> **Note on Distances:** Because MSAJCE is physically located *inside* the SIPCOT IT Park boundary, all of these companies are within a highly accessible 1 to 5 km radius from the college gates.""",
        "citations": [{"source": "msajce_about.md", "page": "1", "section": "Why Join MSAJCE"}],
    },
    {
        "query": "what are the companies near msajce",
        "answer": """**Mohamed Sathak A.J. College of Engineering (MSAJCE)** is located on a sprawling 70-acre campus right inside the **SIPCOT IT Park, Siruseri**. Because of this strategic location, the college is surrounded by over a hundred leading multinational IT industries.

### 🏢 Companies surrounding MSAJCE
As per official college records, the campus is in the immediate vicinity of major tech giants including:
- **TCS (Tata Consultancy Services)**
- **CTS (Cognizant Technology Solutions)**
- **Infosys**
- **HCL Technologies**
- **Intellect Design Arena**
- **Aspire Systems**
- **Steria**
- **Polaris Software Lab**
- **FSS (Financial Software and Systems)**

### 🌐 Other Major Companies in Siruseri IT Park
Since the college is inside the IT Park, it is also close to other major companies operating there, such as:
- **Capgemini**
- **Hexaware Technologies**
- **Atos Syntel**
- **Sify Technologies** (New data center)
- **Equinix** (New facility)

> **Note on Distances:** Because MSAJCE is physically located *inside* the SIPCOT IT Park boundary, all of these companies are within a highly accessible 1 to 5 km radius from the college gates.""",
        "citations": [{"source": "msajce_about.md", "page": "1", "section": "Why Join MSAJCE"}],
    },
    {
        "query": "tell me abt principal like abt him more details",
        "answer": """### 🎓 Principal's Profile: Dr. K.S. Srinivasan

Dr. K.S. Srinivasan (Ph.D) is the Principal of Mohamed Sathak A.J. College of Engineering (**MSAJCE**), Siruseri, Chennai. He joined the institution in May 2019. He is a Professor with a specialization in Electronics and Communication Engineering.

### 🏛 Institutional Roles & Responsibilities
- **Principal** — Overall academic leadership and institutional administration
- **Chairman** — Academic Advisory Committee, Anti-Ragging Committee, Library Committee, Canteen Committee
- **IQAC Chairperson** — Internal Quality Assurance Cell
- **President** — MSAJCE Alumni Association (2020–present)
- **Advisor** — Research Advisory Committee (also serves as Secretary of TNSCST)

### 🔬 Research & Patents
He is an approved Ph.D. supervisor under Anna University (Ref: **1440364**). His research areas include:
- VLSI Design
- Digital Signal Processing
- Digital Image Processing

**Patent Filed:** "A Smart Device to Monitoring the Optic Cable and Inform the Users in Case of any Discrepancies" (Patent Number: 202241071306).

### 📚 Authored Books
Dr. Srinivasan is a prolific author, having written over 14 academic books, including:
- *Communication Theory*
- *Principles of Communication Engineering*
- *Electric Circuits and Electronic Devices*
- *Wireless Sensor Networks*
- *Digital Signal Processing*

### ✉️ Contact Information
- **Email:** principal@msajce-edu.in
- **Phone:** 9150575066

> **Principal's Message:** "MSAJCE believes in providing our students an environment which is rich in knowledge and supportive of their extracurricular interests. We practice a holistic approach that stimulates young minds in terms of innovative and creative thinking." """,
        "citations": [{"source": "msajce_principal.md", "page": "1", "section": "Profile"}],
    },
    {
        "query": "who is the principal",
        "answer": """### 🎓 Principal's Profile: Dr. K.S. Srinivasan

Dr. K.S. Srinivasan (Ph.D) is the Principal of Mohamed Sathak A.J. College of Engineering (**MSAJCE**), Siruseri, Chennai. He joined the institution in May 2019. He is a Professor with a specialization in Electronics and Communication Engineering.

### 🏛 Institutional Roles & Responsibilities
- **Principal** — Overall academic leadership and institutional administration
- **Chairman** — Academic Advisory Committee, Anti-Ragging Committee, Library Committee, Canteen Committee
- **IQAC Chairperson** — Internal Quality Assurance Cell
- **President** — MSAJCE Alumni Association (2020–present)
- **Advisor** — Research Advisory Committee (also serves as Secretary of TNSCST)

### 🔬 Research & Patents
He is an approved Ph.D. supervisor under Anna University (Ref: **1440364**). His research areas include:
- VLSI Design
- Digital Signal Processing
- Digital Image Processing

**Patent Filed:** "A Smart Device to Monitoring the Optic Cable and Inform the Users in Case of any Discrepancies" (Patent Number: 202241071306).

### 📚 Authored Books
Dr. Srinivasan is a prolific author, having written over 14 academic books, including:
- *Communication Theory*
- *Principles of Communication Engineering*
- *Electric Circuits and Electronic Devices*
- *Wireless Sensor Networks*
- *Digital Signal Processing*

### ✉️ Contact Information
- **Email:** principal@msajce-edu.in
- **Phone:** 9150575066

> **Principal's Message:** "MSAJCE believes in providing our students an environment which is rich in knowledge and supportive of their extracurricular interests. We practice a holistic approach that stimulates young minds in terms of innovative and creative thinking." """,
        "citations": [{"source": "msajce_principal.md", "page": "1", "section": "Profile"}],
    },
    {
        "query": "what courses does msajce offer",
        "answer": """MSAJCE (Mohamed Sathak A.J. College of Engineering) offers the following programmes:

## 🎓 Undergraduate B.E / B.Tech / B.Arch / B.Des Programmes

| Department | Course Name | Duration | Total Seats | Govt Quota | Management Quota |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Civil Engineering** | B.E. in Civil Engineering | 4 years | 30 | 15 | 15 |
| **Computer Science & Engineering** | B.E. in Computer Science and Engineering | 4 years | 60 | 30 | 30 |
| **Electronics & Communication** | B.E. in Electronics and Communication Engineering | 4 years | 60 | 30 | 30 |
| **Electrical & Electronics** | B.E. in Electrical and Electronics Engineering | 4 years | 30 | 15 | 15 |
| **Mechanical Engineering** | B.E. in Mechanical Engineering | 4 years | 30 | 15 | 15 |
| **Information Technology** | B.Tech. in Information Technology | 4 years | 60 | 30 | 30 |
| **Artificial Intelligence** | B.Tech. in Artificial Intelligence and Data Science | 4 years | 60 | 30 | 30 |
| **Computer Science & Business** | B.Tech. in Computer Science and Business Systems | 4 years | 30 | 15 | 15 |
| **Cyber Security** | B.E. in Computer Science and Engineering (Cyber Security) | 4 years | 30 | 15 | 15 |
| **Artificial Intelligence** | B.Tech. in Artificial Intelligence and Machine Learning | 4 years | 60 | 30 | 30 |
| **VLSI Design** | B.E. in Electronics Engineering (VLSI Design and Technology) | 4 years | 30 | 15 | 15 |
| **Advanced Communication** | B.E. in ECE (Advanced Communication Technology) | 4 years | 30 | 15 | 15 |
| **Architecture** | Bachelor of Architecture (B.Arch) | 5 years | 40 | 20 | 20 |
| **Design** | Bachelor of Design (B.Des) | 4 years | 30 | 15 | 15 |

## 🎓 Postgraduate Programmes (M.E / M.Arch)

| Department | Course Name | Duration | Total Seats | Government Quota | Management Quota |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Computer Science** | M.E. in Computer Science and Engineering | 2 years | 9 | 3 | 6 |
| **Civil Engineering** | M.E. in Structural Engineering | 2 years | 18 | 6 | 12 |
| **Architecture** | Master of Architecture (M.Arch) | 2 years | 15 | 7 | 8 |

## 🔬 Research Programme
- **Ph.D** in Mechanical Engineering

All programmes are approved by AICTE and affiliated to Anna University, Chennai.""",
        "citations": [{"source": "msajce_admission.md", "page": "1", "section": "Programmes Offered"}],
    },
    {
        "query": "what are the courses in msajce",
        "answer": """MSAJCE offers 14 UG programmes (including B.Arch and B.Des), 3 PG programmes, and a Ph.D programme. The key UG courses are: CSE, IT, ECE, EEE, Mechanical, Civil, AI&DS, AI&ML, CSBS, Cyber Security, VLSI, ACT, B.Arch, and B.Design. For the full intake and quota details, ask: "What courses does MSAJCE offer?".""",
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
    {
        "query": "list all the ug courses offered by the college",
        "answer": """Mohamed Sathak A.J. College of Engineering (MSAJCE) offers the following 12 B.E./B.Tech undergraduate courses, plus B.Arch and B.Des programmes:

## 🎓 Undergraduate (UG) Programmes

| Department | Course Name | Duration | Total Seats | Govt Quota | Management Quota |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Civil Engineering** | B.E. in Civil Engineering | 4 years | 30 | 15 | 15 |
| **Computer Science & Engineering** | B.E. in Computer Science and Engineering | 4 years | 60 | 30 | 30 |
| **Electronics & Communication** | B.E. in Electronics and Communication Engineering | 4 years | 60 | 30 | 30 |
| **Electrical & Electronics** | B.E. in Electrical and Electronics Engineering | 4 years | 30 | 15 | 15 |
| **Mechanical Engineering** | B.E. in Mechanical Engineering | 4 years | 30 | 15 | 15 |
| **Information Technology** | B.Tech. in Information Technology | 4 years | 60 | 30 | 30 |
| **Artificial Intelligence** | B.Tech. in Artificial Intelligence and Data Science | 4 years | 60 | 30 | 30 |
| **Computer Science & Business** | B.Tech. in Computer Science and Business Systems | 4 years | 30 | 15 | 15 |
| **Cyber Security** | B.E. in Computer Science and Engineering (Cyber Security) | 4 years | 30 | 15 | 15 |
| **Artificial Intelligence** | B.Tech. in Artificial Intelligence and Machine Learning | 4 years | 60 | 30 | 30 |
| **VLSI Design** | B.E. in Electronics Engineering (VLSI Design and Technology) | 4 years | 30 | 15 | 15 |
| **Advanced Communication** | B.E. in ECE (Advanced Communication Technology) | 4 years | 30 | 15 | 15 |
| **Architecture** | Bachelor of Architecture (B.Arch) | 5 years | 40 | 20 | 20 |
| **Design** | Bachelor of Design (B.Des) | 4 years | 30 | 15 | 15 |

All undergraduate courses are approved by AICTE and affiliated to Anna University, Chennai.""",
        "citations": [{"source": "msajce_admission.md", "page": "1", "section": "Programmes Offered"}],
    },
    {
        "query": "list the ug courses offered by the college",
        "answer": """Mohamed Sathak A.J. College of Engineering (MSAJCE) offers the following 12 B.E./B.Tech undergraduate courses, plus B.Arch and B.Des programmes:

## 🎓 Undergraduate (UG) Programmes

| Department | Course Name | Duration | Total Seats | Govt Quota | Management Quota |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Civil Engineering** | B.E. in Civil Engineering | 4 years | 30 | 15 | 15 |
| **Computer Science & Engineering** | B.E. in Computer Science and Engineering | 4 years | 60 | 30 | 30 |
| **Electronics & Communication** | B.E. in Electronics and Communication Engineering | 4 years | 60 | 30 | 30 |
| **Electrical & Electronics** | B.E. in Electrical and Electronics Engineering | 4 years | 30 | 15 | 15 |
| **Mechanical Engineering** | B.E. in Mechanical Engineering | 4 years | 30 | 15 | 15 |
| **Information Technology** | B.Tech. in Information Technology | 4 years | 60 | 30 | 30 |
| **Artificial Intelligence** | B.Tech. in Artificial Intelligence and Data Science | 4 years | 60 | 30 | 30 |
| **Computer Science & Business** | B.Tech. in Computer Science and Business Systems | 4 years | 30 | 15 | 15 |
| **Cyber Security** | B.E. in Computer Science and Engineering (Cyber Security) | 4 years | 30 | 15 | 15 |
| **Artificial Intelligence** | B.Tech. in Artificial Intelligence and Machine Learning | 4 years | 60 | 30 | 30 |
| **VLSI Design** | B.E. in Electronics Engineering (VLSI Design and Technology) | 4 years | 30 | 15 | 15 |
| **Advanced Communication** | B.E. in ECE (Advanced Communication Technology) | 4 years | 30 | 15 | 15 |
| **Architecture** | Bachelor of Architecture (B.Arch) | 5 years | 40 | 20 | 20 |
| **Design** | Bachelor of Design (B.Des) | 4 years | 30 | 15 | 15 |

All undergraduate courses are approved by AICTE and affiliated to Anna University, Chennai.""",
        "citations": [{"source": "msajce_admission.md", "page": "1", "section": "Programmes Offered"}],
    },
    {
        "query": "ug courses",
        "answer": """Mohamed Sathak A.J. College of Engineering (MSAJCE) offers the following 12 B.E./B.Tech undergraduate courses, plus B.Arch and B.Des programmes:

## 🎓 Undergraduate (UG) Programmes

| Department | Course Name | Duration | Total Seats | Govt Quota | Management Quota |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Civil Engineering** | B.E. in Civil Engineering | 4 years | 30 | 15 | 15 |
| **Computer Science & Engineering** | B.E. in Computer Science and Engineering | 4 years | 60 | 30 | 30 |
| **Electronics & Communication** | B.E. in Electronics and Communication Engineering | 4 years | 60 | 30 | 30 |
| **Electrical & Electronics** | B.E. in Electrical and Electronics Engineering | 4 years | 30 | 15 | 15 |
| **Mechanical Engineering** | B.E. in Mechanical Engineering | 4 years | 30 | 15 | 15 |
| **Information Technology** | B.Tech. in Information Technology | 4 years | 60 | 30 | 30 |
| **Artificial Intelligence** | B.Tech. in Artificial Intelligence and Data Science | 4 years | 60 | 30 | 30 |
| **Computer Science & Business** | B.Tech. in Computer Science and Business Systems | 4 years | 30 | 15 | 15 |
| **Cyber Security** | B.E. in Computer Science and Engineering (Cyber Security) | 4 years | 30 | 15 | 15 |
| **Artificial Intelligence** | B.Tech. in Artificial Intelligence and Machine Learning | 4 years | 60 | 30 | 30 |
| **VLSI Design** | B.E. in Electronics Engineering (VLSI Design and Technology) | 4 years | 30 | 15 | 15 |
| **Advanced Communication** | B.E. in ECE (Advanced Communication Technology) | 4 years | 30 | 15 | 15 |
| **Architecture** | Bachelor of Architecture (B.Arch) | 5 years | 40 | 20 | 20 |
| **Design** | Bachelor of Design (B.Des) | 4 years | 30 | 15 | 15 |

All undergraduate courses are approved by AICTE and affiliated to Anna University, Chennai.""",
        "citations": [{"source": "msajce_admission.md", "page": "1", "section": "Programmes Offered"}],
    },
    {
        "query": "undergraduate courses",
        "answer": """Mohamed Sathak A.J. College of Engineering (MSAJCE) offers the following 12 B.E./B.Tech undergraduate courses, plus B.Arch and B.Des programmes:

## 🎓 Undergraduate (UG) Programmes

| Department | Course Name | Duration | Total Seats | Govt Quota | Management Quota |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Civil Engineering** | B.E. in Civil Engineering | 4 years | 30 | 15 | 15 |
| **Computer Science & Engineering** | B.E. in Computer Science and Engineering | 4 years | 60 | 30 | 30 |
| **Electronics & Communication** | B.E. in Electronics and Communication Engineering | 4 years | 60 | 30 | 30 |
| **Electrical & Electronics** | B.E. in Electrical and Electronics Engineering | 4 years | 30 | 15 | 15 |
| **Mechanical Engineering** | B.E. in Mechanical Engineering | 4 years | 30 | 15 | 15 |
| **Information Technology** | B.Tech. in Information Technology | 4 years | 60 | 30 | 30 |
| **Artificial Intelligence** | B.Tech. in Artificial Intelligence and Data Science | 4 years | 60 | 30 | 30 |
| **Computer Science & Business** | B.Tech. in Computer Science and Business Systems | 4 years | 30 | 15 | 15 |
| **Cyber Security** | B.E. in Computer Science and Engineering (Cyber Security) | 4 years | 30 | 15 | 15 |
| **Artificial Intelligence** | B.Tech. in Artificial Intelligence and Machine Learning | 4 years | 60 | 30 | 30 |
| **VLSI Design** | B.E. in Electronics Engineering (VLSI Design and Technology) | 4 years | 30 | 15 | 15 |
| **Advanced Communication** | B.E. in ECE (Advanced Communication Technology) | 4 years | 30 | 15 | 15 |
| **Architecture** | Bachelor of Architecture (B.Arch) | 5 years | 40 | 20 | 20 |
| **Design** | Bachelor of Design (B.Des) | 4 years | 30 | 15 | 15 |

All undergraduate courses are approved by AICTE and affiliated to Anna University, Chennai.""",
        "citations": [{"source": "msajce_admission.md", "page": "1", "section": "Programmes Offered"}],
    },
    {
        "query": "lis the ME courses offered by you",
        "answer": """Mohamed Sathak A.J. College of Engineering (MSAJCE) offers the following Postgraduate (PG) M.E. courses, plus Master of Architecture:

## 🎓 Postgraduate (PG) Programmes

| Department | Course Name | Duration | Total Seats | Government Quota | Management Quota |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Computer Science** | M.E. in Computer Science and Engineering | 2 years | 9 | 3 | 6 |
| **Civil Engineering** | M.E. in Structural Engineering | 2 years | 18 | 6 | 12 |
| **Architecture** | Master of Architecture (M.Arch) | 2 years | 15 | 7 | 8 |

All postgraduate courses are approved by AICTE and affiliated to Anna University, Chennai.""",
        "citations": [{"source": "msajce_admission.md", "page": "1", "section": "Programmes Offered"}],
    },
    {
        "query": "list the ME courses offered by you",
        "answer": """Mohamed Sathak A.J. College of Engineering (MSAJCE) offers the following Postgraduate (PG) M.E. courses, plus Master of Architecture:

## 🎓 Postgraduate (PG) Programmes

| Department | Course Name | Duration | Total Seats | Government Quota | Management Quota |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Computer Science** | M.E. in Computer Science and Engineering | 2 years | 9 | 3 | 6 |
| **Civil Engineering** | M.E. in Structural Engineering | 2 years | 18 | 6 | 12 |
| **Architecture** | Master of Architecture (M.Arch) | 2 years | 15 | 7 | 8 |

All postgraduate courses are approved by AICTE and affiliated to Anna University, Chennai.""",
        "citations": [{"source": "msajce_admission.md", "page": "1", "section": "Programmes Offered"}],
    },
    {
        "query": "list the me courses",
        "answer": """Mohamed Sathak A.J. College of Engineering (MSAJCE) offers the following Postgraduate (PG) M.E. courses, plus Master of Architecture:

## 🎓 Postgraduate (PG) Programmes

| Department | Course Name | Duration | Total Seats | Government Quota | Management Quota |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Computer Science** | M.E. in Computer Science and Engineering | 2 years | 9 | 3 | 6 |
| **Civil Engineering** | M.E. in Structural Engineering | 2 years | 18 | 6 | 12 |
| **Architecture** | Master of Architecture (M.Arch) | 2 years | 15 | 7 | 8 |

All postgraduate courses are approved by AICTE and affiliated to Anna University, Chennai.""",
        "citations": [{"source": "msajce_admission.md", "page": "1", "section": "Programmes Offered"}],
    },
    {
        "query": "me courses",
        "answer": """Mohamed Sathak A.J. College of Engineering (MSAJCE) offers the following Postgraduate (PG) M.E. courses, plus Master of Architecture:

## 🎓 Postgraduate (PG) Programmes

| Department | Course Name | Duration | Total Seats | Government Quota | Management Quota |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Computer Science** | M.E. in Computer Science and Engineering | 2 years | 9 | 3 | 6 |
| **Civil Engineering** | M.E. in Structural Engineering | 2 years | 18 | 6 | 12 |
| **Architecture** | Master of Architecture (M.Arch) | 2 years | 15 | 7 | 8 |

All postgraduate courses are approved by AICTE and affiliated to Anna University, Chennai.""",
        "citations": [{"source": "msajce_admission.md", "page": "1", "section": "Programmes Offered"}],
    },
    {
        "query": "need students who got scholarships from the batch of 2024-2028",
        "answer": """Here is the list of students from the **2024-2028** batch who received the MSAJCE Alumni Scholarship:

| Student Name | Department | Scholarship Date(s) | Details |
| :--- | :--- | :--- | :--- |
| **Mohamed Humdhan I** | Artificial Intelligence & Data Science (AIDS) | 09.07.2026, 10.05.2026 | Received sponsorship on two separate occasions. |
| **Revathi A** | Electronics & Communication Engineering (ECE) | 07.03.2026 | Received sponsorship in March 2026. |
| **Sireesh B** | Electronics & Communication Engineering (ECE) | 07.03.2026 | Received sponsorship in March 2026. |
| **Mohammed Shahul Hameed B** | Electronics & Communication Engineering (ECE) | 06.03.2026 | Received sponsorship in March 2026. |
| **Harini R** | Artificial Intelligence & Machine Learning (AIML) | 04.03.2026 | Received sponsorship in March 2026. |
| **Jafeer Mohamed J** | Artificial Intelligence & Data Science (AIDS) | 04.03.2026 | Received sponsorship in March 2026. |
| **Pirivindhan A** | Artificial Intelligence & Data Science (AIDS) | 26.02.2026 | Received sponsorship in February 2026. |
| **Afreen Fathim S** | Electronics (VLSI Design & Technology) | 25.02.2026 | Received sponsorship in February 2026. |
| **Afasr Ali N** | Artificial Intelligence & Machine Learning (AIML) | 24.02.2026 | Received sponsorship in February 2026. |
| **Md Suhail F** | Computer Science & Engineering (CSE) | 22.02.2026 | Received sponsorship in February 2026. |""",
        "citations": [{"source": "msajce_alumni.md", "page": "1", "section": "Alumni Scholarship Contribution"}],
    },
    {
        "query": "students who got scholarships from the batch of 2024-2028",
        "answer": """Here is the list of students from the **2024-2028** batch who received the MSAJCE Alumni Scholarship:

| Student Name | Department | Scholarship Date(s) | Details |
| :--- | :--- | :--- | :--- |
| **Mohamed Humdhan I** | Artificial Intelligence & Data Science (AIDS) | 09.07.2026, 10.05.2026 | Received sponsorship on two separate occasions. |
| **Revathi A** | Electronics & Communication Engineering (ECE) | 07.03.2026 | Received sponsorship in March 2026. |
| **Sireesh B** | Electronics & Communication Engineering (ECE) | 07.03.2026 | Received sponsorship in March 2026. |
| **Mohammed Shahul Hameed B** | Electronics & Communication Engineering (ECE) | 06.03.2026 | Received sponsorship in March 2026. |
| **Harini R** | Artificial Intelligence & Machine Learning (AIML) | 04.03.2026 | Received sponsorship in March 2026. |
| **Jafeer Mohamed J** | Artificial Intelligence & Data Science (AIDS) | 04.03.2026 | Received sponsorship in March 2026. |
| **Pirivindhan A** | Artificial Intelligence & Data Science (AIDS) | 26.02.2026 | Received sponsorship in February 2026. |
| **Afreen Fathim S** | Electronics (VLSI Design & Technology) | 25.02.2026 | Received sponsorship in February 2026. |
| **Afasr Ali N** | Artificial Intelligence & Machine Learning (AIML) | 24.02.2026 | Received sponsorship in February 2026. |
| **Md Suhail F** | Computer Science & Engineering (CSE) | 22.02.2026 | Received sponsorship in February 2026. |""",
        "citations": [{"source": "msajce_alumni.md", "page": "1", "section": "Alumni Scholarship Contribution"}],
    },
    {
        "query": "tell me about cse department in msajce",
        "answer": """B.E. in Computer Science and Engineering (CSE) at MSAJCE:

### 🎓 About the Programme
- **Degree**: B.E. in Computer Science and Engineering
- **Duration**: 4 years (8 semesters) | Lateral Entry: 3 years (6 semesters)
- **Total Intake**: 60 seats (30 Govt. Quota + 30 Management Quota)
- **PG Available**: M.E. in Computer Science and Engineering
- **Regulation**: 2021 & 2017

### 📚 What You Study
Programming, Algorithms, Data Structures, Software Engineering, Databases, AI/ML, Cloud Computing, Cyber Security, IoT, Blockchain, DevOps, Full Stack Development

### 💼 Career Roles
| Role | Key Skills |
| :--- | :--- |
| **Software Developer** | Java, Python, C++, JavaScript, React, Node.js |
| **Data Scientist / ML Engineer** | Python, TensorFlow, Spark, SQL |
| **Cybersecurity Specialist** | Ethical Hacking, Cryptography, SIEM |
| **Cloud Architect** | AWS, Azure, GCP, Docker, Kubernetes |
| **Blockchain Developer** | Ethereum, Solidity, Hyperledger |
| **DevOps Engineer** | Jenkins, Docker, Kubernetes, Terraform |

### 🏢 Top Recruiters
TCS, Infosys, Wipro, HCL, CTS, Tech Mahindra, Zoho, Intel, Accenture, IBM, FSS

### 🎯 Vision
To be a center of excellence for transforming students into proficient Computer Science Engineers through sustainable practices.""",
        "citations": [{"source": "msajce_cse.md", "page": "1", "section": "Employment Opportunities in High Demand"}],
    },
    {
        "query": "tell me about it department in msajce",
        "answer": """B.Tech in Information Technology (IT) at MSAJCE:

### 🎓 About the Programme
- **Degree**: B.Tech in Information Technology
- **Duration**: 4 years (8 semesters) | Lateral Entry: 3 years (6 semesters)
- **Total Intake**: 60 seats (30 Govt. Quota + 30 Management Quota)
- **Regulation**: 2021 & 2017

### 📚 What You Study
Machine Learning, Deep Learning, Data Science, AI, Cloud Computing, Networking, Mobile Computing, Blockchain, Cybersecurity, IoT

### 💼 Career Roles
| Role | Key Skills |
| :--- | :--- |
| **Cloud Engineer / Architect** | AWS, Azure, GCP, Docker, Kubernetes, Terraform |
| **AI / ML Engineer** | Python, TensorFlow, PyTorch |
| **Cybersecurity Expert** | Ethical Hacking, SIEM, Forensics |
| **Network Engineer** | CCNA, 5G, Protocols |
| **Blockchain Developer** | Ethereum, Smart Contracts |
| **DevOps Engineer** | CI/CD, Jenkins, Kubernetes |

### 🏢 Top Recruiters
TCS, Infosys, CTS, Wipro, HCL, Tech Mahindra, IBM, Intel, Accenture

### 🎯 Vision
To be a centre of excellence for transforming students into proficient Information Technology professionals through sustainable practices.""",
        "citations": [{"source": "msajce_it.md", "page": "1", "section": "Employment Growth in Information Technology"}],
    },
    {
        "query": "tell me about ece department in msajce",
        "answer": """B.E. in Electronics and Communication Engineering (ECE) at MSAJCE:

### 🎓 About the Programme
- **Degree**: B.E. in Electronics and Communication Engineering
- **Duration**: 4 years | Lateral Entry: 3 years
- **Total Intake**: 60 seats (30 Govt. + 30 Management)
- **HoD**: Dr. I. Manju (Professor & Head)
- **Regulation**: 2021 & 2017

### 📚 What You Study
Signal Processing, VLSI, Embedded Systems, IoT, Wireless Communication, RF Systems, Digital Systems, Image Processing, Communication Systems, Microprocessors

### 💼 Career Roles & Salary Growth (2025–2030)
| Sector | Growth | Roles |
| :--- | :--- | :--- |
| **5G / Telecom** | 10–12%/yr | RF Design, Network Optimization, Antenna |
| **Semiconductor / VLSI** | 12–15%/yr | RTL, Physical Design, DFT, ASIC/FPGA |
| **Embedded & IoT** | 15–18%/yr | C/ARM/RTOS, PCB, Sensor Integration |
| **Defense & Aerospace** | 6–8%/yr | Radar, Avionics, Secure Communication |
| **AI & DSP** | 10–14%/yr | Image/Audio DSP, ML for Signal Processing |

### 🏢 Top Recruiters
TCS, Infosys, HCL, Wipro, DRDO, ISRO, BEL, BSNL, Railways, Accenture, Intel""",
        "citations": [{"source": "msajce_ece.md", "page": "1", "section": "Job Profiles"}],
    },
    {
        "query": "tell me about eee department in msajce",
        "answer": """B.E. in Electrical and Electronics Engineering (EEE) at MSAJCE:

### 🎓 About the Programme
- **Degree**: B.E. in Electrical and Electronics Engineering
- **Duration**: 4 years | Lateral Entry: 3 years
- **Total Intake**: 30 seats (15 Govt. + 15 Management)
- **Regulation**: 2021 & 2017

### 📚 What You Study
Power Systems, Electric Machines, Power Electronics, Renewable Energy, Electric Vehicles, Smart Grids, Embedded Systems, VLSI, Control Systems, IoT

### 💼 Career Roles
Circuit Designer, Energy Efficiency Engineer, Distribution Planning Engineer, Power System Engineer, Research Engineer, Power Plant Engineer, EV Engineer

### 📈 Sector Growth (2025–2030)
| Sector | Growth | Roles |
| :--- | :--- | :--- |
| **Renewable Energy** | 10–12%/yr | Grid Engineers, Solar/Wind, SCADA |
| **Electric Vehicles** | 15–18%/yr | BMS, Motor Control, Embedded |
| **Semiconductor / VLSI** | 12–15%/yr | PCB, ASIC/FPGA |
| **Automation / Industry 4.0** | 8–10%/yr | PLC/SCADA, Robotics, IIoT |
| **Telecom / 5G** | 10–12%/yr | RF, Embedded C, DSP |

### 🏢 Top Recruiters
TNEB, BSNL, ISRO, DRDO, BEL, L&T, Siemens, ABB, Tata Power, Adani Green, Ola Electric""",
        "citations": [{"source": "msajce_eee.md", "page": "1", "section": "Employment Forecast 2025-2030"}],
    },
    {
        "query": "tell me about mechanical engineering department in msajce",
        "answer": """B.E. in Mechanical Engineering (Mech) at MSAJCE:

### 🎓 About the Programme
- **Degree**: B.E. in Mechanical Engineering
- **Duration**: 4 years | Lateral Entry: 3 years
- **Total Intake**: 60 seats (30 Govt. + 30 Management)
- **Regulation**: 2021 & 2017

### 📚 What You Study
Design, Manufacturing, Thermodynamics, CAD/CAM, Robotics, Composite Materials, Renewable Energy, 3D Printing / Additive Manufacturing, Mechatronics, Industry 4.0

### 💼 Career Roles
Planner, Designer, Design Engineer, Manufacturing Engineer, Maintenance Engineer, Production Engineer, R&D Engineer, Robotics Engineer

### 📈 Sector Opportunities (2025–2030)
| Sector | Roles |
| :--- | :--- |
| **Automotive / EV** | EV Powertrain, Battery, Thermal Management |
| **Aerospace & Defence** | Propulsion, Avionics, Advanced Materials |
| **Renewable Energy** | Wind Turbine, Solar, HVAC Design |
| **Robotics & Automation** | Assembly Line, Precision Manufacturing |
| **Infrastructure** | Construction Equipment, Smart City |

### 🏢 Top Recruiters
DRDO, ISRO, HAL, L&T, Bosch, Mahindra, Tata Motors, Hyundai, TVS, Ashok Leyland""",
        "citations": [{"source": "msajce_mech.md", "page": "1", "section": "Employment Growth in Mechanical Engineering"}],
    },
    {
        "query": "tell me about civil engineering department in msajce",
        "answer": """B.E./M.E. in Civil Engineering at MSAJCE:

### 🎓 About the Programme
- **UG Degree**: B.E. in Civil Engineering
- **PG Degree**: M.E. in Structural Engineering
- **Department Established**: 2007 (one of the pioneer departments)
- **Total Intake (UG)**: 60 seats (30 Govt. + 30 Management)
- **Regulation**: 2021 & 2017

### 📚 What You Study
Structural Engineering, Transportation Engineering, Environmental Engineering, Water Supply, Surveying, Remote Sensing & GIS, AutoCAD, Revit, STAAD Pro, BIM, Primavera

### 💼 Career Roles
Structural Engineer, Transportation Engineer, Environmental Engineer, Urban Planner, Construction Manager, Geotechnical Engineer, Site Supervisor

### 📈 Sector Growth (2025–2030)
| Sector | Growth | Focus |
| :--- | :--- | :--- |
| **Public Infrastructure** | 6–8%/yr | Highways, Rail, Smart Cities |
| **Real Estate & Housing** | 4–6%/yr | Urban Development |
| **Green Building / Sustainability** | 10–12%/yr | IGBC, GRIHA Standards |
| **BIM & Smart Construction** | 15%+/yr | Revit, AutoCAD Civil 3D |
| **Transport (Roads/Rail)** | 7–10%/yr | PM Gati Shakti, Bharatmala |

### 🏢 Top Recruiters
L&T, Shapoorji Pallonji, NHAI, Railways, PWD, DRDO, DLF, Tata Projects""",
        "citations": [{"source": "msajce_civil.md", "page": "1", "section": "Employment Outlook for Civil Engineering"}],
    },
    {
        "query": "tell me about cyber security department in msajce",
        "answer": """B.E. in CSE with Specialization in Cyber Security (CSCS) at MSAJCE:

### 🎓 About the Programme
- **Degree**: B.E. Computer Science & Engineering — Cyber Security Specialization
- **Duration**: 4 years | Lateral Entry: 3 years
- **Total Intake**: 30 seats (15 Govt. + 15 Management)
- **Regulation**: 2021

### 📚 What You Study
Network Security, Cryptography, Ethical Hacking, Digital Forensics, Penetration Testing, Secure Coding, Cloud Security, AI Security, IoT Security, Cyber Laws & Compliance

### 💼 Career Roles
| Role | Skills |
| :--- | :--- |
| **Cybersecurity Analyst** | SIEM, Firewall, IDS/IPS, Incident Response |
| **Ethical Hacker / Pen Tester** | Kali Linux, Metasploit, Wireshark, nmap |
| **Security Architect** | Network Architecture, Risk Management, Encryption |
| **SOC Analyst** | Threat Analysis, Log Analysis, SIEM |
| **Cloud Security Specialist** | AWS, Azure, GCP, IAM |
| **Digital Forensics Analyst** | Evidence Collection, Malware Analysis |

### 🏢 Top Recruiters
DRDO, CERT-IN, TCS, Infosys, Accenture, Palo Alto Networks, IBM Security, Banks, Fintech companies

### 💡 Why Choose Cyber Security?
High demand field with **greater job security**, top compensation, global career pathways, and national importance.""",
        "citations": [{"source": "msajce_cyber.md", "page": "1", "section": "Employment Growth in Cyber Security"}],
    },
    {
        "query": "tell me about csbs department in msajce",
        "answer": """B.Tech in Computer Science and Business Systems (CSBS) at MSAJCE:

### 🎓 About the Programme
- **Degree**: B.Tech in Computer Science and Business Systems
- **Collaboration**: Designed in partnership with **Tata Consultancy Services (TCS)**
- **Duration**: 4 years | Lateral Entry: 3 years
- **Regulation**: 2021

### 📚 What You Study
Data Structures, Algorithms, AI/ML, Cloud Computing, Business Analytics, Financial Management, Economics, IoT, Design Thinking, ERP Systems, Business Process Management

### 💼 Career Roles
| Role | Skills |
| :--- | :--- |
| **Business Systems Analyst** | Systems Design, ERP, Agile |
| **Data Scientist / Analyst** | Python, R, SQL, Big Data |
| **Cloud Architect / Engineer** | AWS, Azure, GCP |
| **ERP Consultant** | SAP, Oracle, Business Process Modeling |
| **AI / ML Engineer** | TensorFlow, Python, NLP |
| **Cybersecurity Specialist** | Firewalls, Encryption, IDS |

### 🏢 Top Recruiters
TCS, Infosys, Wipro, Accenture, CTS, FSS, Fintech startups

### 💡 Why CSBS over regular CSE?
More interdisciplinary exposure, better suitability for tech-enabled business roles, greater alignment with industry expectations in IT services and consulting.""",
        "citations": [{"source": "msajce_csbs.md", "page": "1", "section": "Employment Growth in Computer Science and Business Systems"}],
    },
    {
        "query": "tell me about aiml department in msajce",
        "answer": """B.Tech in CSE with Specialization in AI & Machine Learning (AIML) at MSAJCE:

### 🎓 About the Programme
- **Degree**: B.Tech CSE — Artificial Intelligence & Machine Learning Specialization
- **Duration**: 4 years | Lateral Entry: 3 years
- **Regulation**: 2021

### 📚 What You Study
Machine Learning, Deep Learning, NLP, Computer Vision, Data Mining, Explainable AI, Generative AI (GANs, Multimodal AI), Python, R, TensorFlow, Spark, Hadoop

### 💼 Career Roles
| Role | Skills |
| :--- | :--- |
| **ML Engineer** | Python, TensorFlow, PyTorch, Scikit-learn |
| **Data Scientist** | Python, R, SQL, Deep Learning, Time-series |
| **AI Research Scientist** | Research Methods, Python, Mathematical Modeling |
| **Deep Learning Engineer** | TensorFlow, Keras, PyTorch, Image Processing |
| **NLP Engineer** | SpaCy, HuggingFace, NLTK, Sentiment Analysis |
| **AI Product Manager** | Product Lifecycle, Agile, Business Strategy |

### 💰 Salary Trends (India)
| Experience | Salary |
| :--- | :--- |
| Entry Level (0–2 yrs) | ₹6 – ₹12 LPA |
| Mid Level (3–5 yrs) | ₹12 – ₹20 LPA |
| Senior Level (5+ yrs) | ₹20 – ₹35 LPA |
| Research Scientist | ₹25 – ₹50 LPA |
| Project Manager | ₹30 – ₹60 LPA |

### 🏢 Top Recruiters
Microsoft, Amazon, Goldman Sachs, Oracle, Cisco, Dell, Accenture, TCS, Infosys, Google, NVIDIA""",
        "citations": [{"source": "msajce_aiml.md", "page": "1", "section": "Expected Growth and Salary Trends"}],
    },
    {
        "query": "im interested in aids tell me abt it like salary roles studies in msajce and life",
        "answer": """B.Tech in Artificial Intelligence and Data Science (AI&DS) at MSAJCE:

### 🎓 About the Programme
The B.Tech AI & Data Science (AIDS) programme at MSAJCE prepares students in AI, machine learning, deep learning, big data analytics, and data-driven decision-making.

### 📚 What You Study
- **Core**: Artificial Intelligence, Data Mining, Data Modeling, Machine Learning, Big Data Analytics
- **Advanced**: Neural Networks, Deep Learning, Computer Vision, Natural Language Processing
- **Tools**: Python, R, SQL, TensorFlow, Keras, PyTorch, Hadoop, Spark, Tableau, Power BI

### 💼 Career Roles
| Role | Key Skills |
| :--- | :--- |
| **Data Scientist** | Python, R, SQL, ML algorithms, Data Visualization |
| **Machine Learning Engineer** | TensorFlow, PyTorch, AWS/Azure/GCP |
| **AI Research Scientist** | Deep Learning, Mathematical Modeling |
| **Data Analyst** | Excel, SQL, Python, Tableau, Power BI |
| **Data Engineer** | Hadoop, Spark, Kafka, ETL, Cloud |
| **NLP Engineer** | NLTK, SpaCy, HuggingFace, Text Mining |
| **BI Developer** | SQL, Power BI, Tableau, Python |

### 💰 Salary Trends in India
| Experience Level | Expected Salary |
| :--- | :--- |
| Entry Level (0–2 yrs) | ₹6 – ₹12 LPA |
| Mid Level (3–5 yrs) | ₹12 – ₹25 LPA |
| Senior Level (5+ yrs) | ₹25 – ₹50 LPA |
| AI Research Scientist | ₹30 – ₹70 LPA |

> 📈 AI & DS job market in India is growing at **CAGR 30–40%**, driven by healthcare, finance, e-commerce & the National AI Mission.

### 🏢 Industries Hiring
Healthcare, Finance & Fintech, E-Commerce, Automotive, Telecom, Defense, Education, Government

### 🎯 Campus Life & Department
- Part of MSAJCE, Siruseri, Chennai
- Anna University affiliated, AICTE approved
- Active clubs, professional societies (IEEE, CSI), hackathons, and project competitions
- Strong placement support with top AI companies recruiting on campus""",
        "citations": [{"source": "msajce_aids.md", "page": "1", "section": "Career Opportunities & Job Profiles"}],
    },
    {
        "query": "tell me about aids department in msajce",
        "answer": """B.Tech in Artificial Intelligence and Data Science (AI&DS) at MSAJCE:

### 🎓 About the Programme
The B.Tech AI & Data Science (AIDS) programme at MSAJCE prepares students in AI, machine learning, deep learning, big data analytics, and data-driven decision-making. It combines cross-disciplinary skills across statistics, computer science, and logic.

### 📚 What You Study
- **Core**: Artificial Intelligence, Data Mining, Data Modeling, Machine Learning, Big Data Analytics
- **Advanced**: Neural Networks, Deep Learning, Computer Vision, Natural Language Processing
- **Tools**: Python, R, SQL, TensorFlow, Keras, PyTorch, Hadoop, Spark, Tableau, Power BI

### 💼 Career Roles After Graduation
| Role | Key Skills |
| :--- | :--- |
| **Data Scientist** | Python, R, SQL, ML algorithms, Data Visualization |
| **Machine Learning Engineer** | TensorFlow, PyTorch, AWS/Azure/GCP |
| **AI Research Scientist** | Deep Learning, Mathematical Modeling |
| **Data Analyst** | Excel, SQL, Python, Tableau, Power BI |
| **Data Engineer** | Hadoop, Spark, Kafka, ETL, Cloud |
| **NLP Engineer** | NLTK, SpaCy, HuggingFace, Text Mining |
| **BI Developer** | SQL, Power BI, Tableau, Python |
| **AI Product Manager** | Agile, ML Product Lifecycle, Business Strategy |

### 💰 Salary Trends in India
| Experience Level | Expected Salary |
| :--- | :--- |
| Entry Level (0–2 yrs) | ₹6 – ₹12 LPA |
| Mid Level (3–5 yrs) | ₹12 – ₹25 LPA |
| Senior Level (5+ yrs) | ₹25 – ₹50 LPA |
| AI Research Scientist | ₹30 – ₹70 LPA |

> 📈 AI & DS job market in India is growing at **CAGR 30–40%**, driven by healthcare, finance, e-commerce & the National AI Mission.

### 🏢 Industries Hiring
Healthcare, Finance & Fintech, E-Commerce, Automotive, Telecom, Defense, Education, Government

### 🎯 Department Vision
To be a **center of excellence** transforming students into proficient AI & Data Science professionals through sustainable practices.

For admissions, contact 📞 +91 99400 04500 or ✉️ msajce.office@gmail.com""",
        "citations": [{"source": "msajce_aids.md", "page": "1", "section": "Career Opportunities & Job Profiles"}],
    },
    {
        "query": "aids salary and jobs",
        "answer": """AI & Data Science (AIDS) — Salary & Career at MSAJCE:

### 💰 Salary Trends (India)
| Experience | Salary Range |
| :--- | :--- |
| Entry Level (0–2 yrs) | ₹6 – ₹12 LPA |
| Mid Level (3–5 yrs) | ₹12 – ₹25 LPA |
| Senior Level (5+ yrs) | ₹25 – ₹50 LPA |
| AI Research Scientist | ₹30 – ₹70 LPA |

### 💼 Top Job Roles
Data Scientist, ML Engineer, AI Research Scientist, Data Analyst, Data Engineer, NLP Engineer, BI Developer, AI Product Manager.

### 📈 Growth
AI & DS sector growing at **30–40% CAGR** in India. By 2030, hundreds of thousands of AI job openings expected across tech, healthcare, finance, and startups.""",
        "citations": [{"source": "msajce_aids.md", "page": "1", "section": "Expected Growth and Salary Trends"}],
    },
    {
        "query": "what is aids in msajce",
        "answer": """**AIDS** stands for **Artificial Intelligence and Data Science** — a B.Tech programme at MSAJCE, Siruseri, Chennai.

Students learn AI, machine learning, deep learning, big data, and data science. Graduates go on to roles like Data Scientist, ML Engineer, AI Researcher, and NLP Engineer in industries like healthcare, finance, e-commerce, and defence.

Ask: *"tell me about the AIDS department"* for full details on studies, salary, and career paths.""",
        "citations": [{"source": "msajce_aids.md", "page": "1", "section": "Overview"}],
    },
    {
        "query": "which college bus comes to velachery or surroundings of velachery",
        "answer": """The following MSAJCE college bus routes serve Velachery and its surroundings:

### 🚌 Route N/3 (formerly AR 5)
- **Departure Stop**: MMDA School (6:15 AM)
- **Stops in/near Velachery**:
  - **Velachery Check Post** at **6:50 AM**
  - **Vijaya Nagar Bus Stop** at **6:53 AM**
  - **Baby Nagar** at **6:55 AM**
  - **Tharamani** at **7:00 AM**
- **Driver**: Mr. Velu

### 🚌 Route R 22
- **Departure Stop**: Nemilichery (5:50 AM)
- **Stops in/near Velachery**:
  - **Velachery Bypass** at **6:45 AM**
  - **Kaiveli** at **7:00 AM**
- **Driver**: Mr. Jaffar

### 🚌 Route AR 8
- **Departure Stop**: Manjambakkam (5:50 AM)
- **Stops in/near Velachery**:
  - **Kiveli (Kaiveli)** at **6:55 AM**
- **Driver**: Mr. Raju

### 🚌 MTC Bus Routes (Public Transport)
- A route from **CMBT** to **Kelambakkam** passes through Velachery and SRP.
- Route **570S** from **CMBT** to **Sipcot** passes through Velachery and SRP.""",
        "citations": [{"source": "msajce_transport.md", "page": "1", "section": "College Bus Routes Summary"}],
    },
    {
        "query": "does college bus go to velachery",
        "answer": """Yes, MSAJCE college buses go to Velachery. The following routes serve the area:

| Route | Stop / Landmark | Arrival Time | Driver |
| :--- | :--- | :--- | :--- |
| **Route N/3** | Velachery Check Post | 6:50 AM | Mr. Velu |
| **Route N/3** | Vijaya Nagar Bus Stop | 6:53 AM | Mr. Velu |
| **Route N/3** | Baby Nagar | 6:55 AM | Mr. Velu |
| **Route R 22** | Velachery Bypass | 6:45 AM | Mr. Jaffar |
| **Route R 22** | Kaiveli | 7:00 AM | Mr. Jaffar |
| **Route AR 8** | Kiveli (Kaiveli) | 6:55 AM | Mr. Raju |""",
        "citations": [{"source": "msajce_transport.md", "page": "1", "section": "College Bus Routes Summary"}],
    },
    {
        "query": "bus routes for velachery",
        "answer": """The college bus routes for Velachery and surroundings are:

| Route | Stop / Landmark | Arrival Time | Driver |
| :--- | :--- | :--- | :--- |
| **Route N/3 (formerly AR 5)** | Velachery Check Post | 6:50 AM | Mr. Velu |
| **Route N/3 (formerly AR 5)** | Vijaya Nagar Bus Stop | 6:53 AM | Mr. Velu |
| **Route N/3 (formerly AR 5)** | Baby Nagar | 6:55 AM | Mr. Velu |
| **Route R 22** | Velachery Bypass | 6:45 AM | Mr. Jaffar |
| **Route R 22** | Kaiveli | 7:00 AM | Mr. Jaffar |
| **Route AR 8** | Kiveli (Kaiveli) | 6:55 AM | Mr. Raju |""",
        "citations": [{"source": "msajce_transport.md", "page": "1", "section": "College Bus Routes Summary"}],
    },
    {
        "query": "velachery bus timings",
        "answer": """The college bus timings for Velachery stops are:

| Stop / Landmark | Arrival Time | Bus Route | Driver |
| :--- | :--- | :--- | :--- |
| **Velachery Bypass** | 6:45 AM | Route R 22 | Mr. Jaffar |
| **Velachery Check Post** | 6:50 AM | Route N/3 (formerly AR 5) | Mr. Velu |
| **Vijaya Nagar Bus Stop** | 6:53 AM | Route N/3 (formerly AR 5) | Mr. Velu |
| **Baby Nagar** | 6:55 AM | Route N/3 (formerly AR 5) | Mr. Velu |
| **Kiveli (Kaiveli)** | 6:55 AM | Route AR 8 | Mr. Raju |
| **Kaiveli** | 7:00 AM | Route R 22 | Mr. Jaffar |""",
        "citations": [{"source": "msajce_transport.md", "page": "1", "section": "College Bus Routes Summary"}],
    },
    # ── Question Cards Seeds ──────────────────────────────────────────────
    {
        "query": "What is the admission procedure, eligibility, and TNEA cutoff for B.E / B.Tech at MSAJCE?",
        "answer": """Mohamed Sathak A.J. College of Engineering (MSAJCE) admission details:

### 📝 Admission Procedure
- **Counselling Route (50% Seats)**: Candidates who have completed HSC (Academic/Vocational) or Diploma can apply through the **TNEA (Tamil Nadu Engineering Admissions)** counselling process conducted by DOTE. Anna University Counselling Code: **1301**.
- **Management Route (50% Seats)**: Candidates can apply directly under the Management Quota based on merit in qualifying marks.
- **NRI Admissions (5%)**: 5% of sanctioned seats are reserved under the NRI category. Unfilled NRI seats are allocated to general candidates on merit.
- **Contact Admissions**: For admission queries, contact the general office helpline at **+91 99400 04500** or via email at **msajce.office@gmail.com**. You can also reach out to Physical Education Director Dr. K.P. Santhosh Nathan (ped.santhosh@msajce-edu.in) or Principal Dr. K.S. Srinivasan (principal@msajce-edu.in).

### 🎓 Eligibility Criteria (UG B.E. / B.Tech)
Pass in HSC (Academic/Vocational) or equivalent with a minimum average percentage in Mathematics, Physics, and Chemistry (MPC) put together:

| Category | Minimum Average Marks (Academic & Vocational) |
| :--- | :--- |
| **General Category (OC)** | **45%** minimum average |
| **Backward Class (BC / BCM)** | **40%** minimum average |
| **MBC / DNC** | **40%** minimum average |
| **SC / SCA / ST** | **40%** minimum average |

### 🔄 Direct Second Year Lateral Entry Eligibility
Candidates must have passed a recognized Diploma or a 3-year B.Sc. degree with Mathematics:

| Category | Minimum Average Marks (Lateral Entry) |
| :--- | :--- |
| **General Category (OC)** | **55%** minimum average |
| **Backward Class (BC / BCM)** | **50%** minimum average |
| **MBC / DNC** | **45%** minimum average |
| **SC / SCA / ST** | **Mere pass** in the qualifying exam |""",
        "citations": [{"source": "msajce_admission.md", "page": "1", "section": "Under Graduate Programmes"}],
    },
    {
        "query": "Tell me about the Central Library facilities, books stack, and working hours at MSAJCE.",
        "answer": """The Learning Centre (Central Library) is a core support service at MSAJCE:

### 📚 Infrastructure & Collections
The library covers a spacious area of **8,978 square feet** spanning across the Ground and First Floors. It is fully automated with Koha open-source software and Bar-coded Technology.

| Resource Category | Details & Counts |
| :--- | :--- |
| **Total Volumes** | **29,853 volumes** |
| **Total Titles** | **5,628 titles** |
| **Reference Volumes** | **1,885 reference volumes** |
| **E-books** | **3,790 e-books** |
| **Printed Journals** | **35 specialized printed journals** and **20 magazines** |
| **E-journals** | DELNET (**1,379 e-journals**), J-Gate Database (**50,684+ journals**) |
| **Gale Database** | Access to **1,800 international journals** online |
| **Multimedia** | **356 CD-ROMs** and **260 project reports** |

### ⏰ Library Working Hours
- **Monday to Saturday**: **8:00 AM to 7:00 PM**
- **Sundays**: **10:00 AM to 4:00 PM**

### 💳 Borrowing Eligibility & Limits (Loan Period: 30 Days)
- **Students (UG & PG)**: Entitled to borrow up to **18 books**.
- **Teaching Staff**: Entitled to borrow up to **10 books**.
- **Supporting & Administrative Staff**: Entitled to borrow up to **4 books**.

### 💸 Overdue Fines
- **1 to 7 Days**: Rs. 1 per day per book.
- **8 to 14 Days**: Rs. 2 per day per book.
- **15 Days onwards**: Rs. 5 per day per book.""",
        "citations": [{"source": "msajce_library.md", "page": "1", "section": "Overview"}],
    },
    {
        "query": "List all UG and PG degree courses offered at Mohamed Sathak A.J. College of Engineering.",
        "answer": """Mohamed Sathak A.J. College of Engineering (MSAJCE) offers the following Undergraduate and Postgraduate courses:

### 🎓 Undergraduate (UG) B.E. / B.Tech / B.Arch / B.Des Courses

| Department | Course Name | Duration | Total Intake | Govt Quota (50%) | Mgmt Quota (50%) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Civil Engineering** | B.E. in Civil Engineering | 4 years | 30 | 15 | 15 |
| **Computer Science & Engineering** | B.E. in Computer Science and Engineering | 4 years | 60 | 30 | 30 |
| **Electronics & Communication** | B.E. in Electronics and Communication Engineering | 4 years | 60 | 30 | 30 |
| **Electrical & Electronics** | B.E. in Electrical and Electronics Engineering | 4 years | 30 | 15 | 15 |
| **Mechanical Engineering** | B.E. in Mechanical Engineering | 4 years | 30 | 15 | 15 |
| **Information Technology** | B.Tech. in Information Technology | 4 years | 60 | 30 | 30 |
| **Artificial Intelligence** | B.Tech. in Artificial Intelligence and Data Science | 4 years | 60 | 30 | 30 |
| **Computer Science & Business** | B.Tech. in Computer Science and Business Systems | 4 years | 30 | 15 | 15 |
| **Cyber Security** | B.E. in Computer Science and Engineering (Cyber Security) | 4 years | 30 | 15 | 15 |
| **Artificial Intelligence** | B.Tech. in Artificial Intelligence and Machine Learning | 4 years | 60 | 30 | 30 |
| **VLSI Design** | B.E. in Electronics Engineering (VLSI Design and Technology) | 4 years | 30 | 15 | 15 |
| **Advanced Communication** | B.E. in ECE (Advanced Communication Technology) | 4 years | 30 | 15 | 15 |
| **Architecture** | Bachelor of Architecture (B.Arch) | 5 years | 40 | 20 | 20 |
| **Design** | Bachelor of Design (B.Des) | 4 years | 30 | 15 | 15 |

### 🎓 Postgraduate (PG) M.E. / M.Arch Courses

| Department | Course Name | Duration | Total Intake | Govt Quota (50%) | Mgmt Quota (50%) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Computer Science** | M.E. in Computer Science and Engineering | 2 years | 9 | 3 | 6 |
| **Civil Engineering** | M.E. in Structural Engineering | 2 years | 18 | 6 | 12 |
| **Architecture** | Master of Architecture (M.Arch) | 2 years | 15 | 7 | 8 |

### 🔬 Research Programme
- **Ph.D.** in Mechanical Engineering

All courses are approved by AICTE New Delhi and affiliated to Anna University, Chennai.""",
        "citations": [{"source": "msajce_admission.md", "page": "1", "section": "Programmes Offered"}],
    },
    {
        "query": "What are the placement statistics, highest package, and top recruiting companies at MSAJCE?",
        "answer": """Mohamed Sathak A.J. College of Engineering (MSAJCE) maintains a dedicated Placement Cell to facilitate internships and placements:

### 💼 Top Recruiter Internship Placements (2022-2023 Batch)
A high percentage of students secure internships and placements in leading corporate organizations. Key placement counts for the 2022-2023 batch include:

| Recruiter Company | Number of Student Interns Placed |
| :--- | :--- |
| **Lenovo** | 75 students |
| **Zoho Tech** | 51 students |
| **Green Valleys Shelters Pvt. Ltd.** | 45 students |
| **Thermodyn** | 39 students |
| **Ozaro Media Teck** | 34 students |
| **Sri KVS Industries** | 30 students |
| **Openwave** | 16 students |
| **Preethi Engineering** | 14 students |
| **TVS Mobility** | 10 students |
| **Disenosys** | 9 students |

### 💰 Placement Packages
- **Highest and Average Packages**: Specific salary packages or highest placement packages are not explicitly documented in the available records. For detailed salary package charts, contact the Placement Officer Mr. S.V. Vinodh (placement@msajce-edu.in) or the general office (+91 99400 04500).

### 🤝 Placement Committee
- **Placement Officer**: Mr. S.V. Vinodh (placement@msajce-edu.in)
- **Assistant Placement Officer**: Mr. Ajin Sijo John""",
        "citations": [{"source": "msajce_placement.md", "page": "1", "section": "Overview"}],
    },
    {
        "query": "What are the hostel facilities, room capacity, mess, and rules for the Boys Hostel at MSAJCE?",
        "answer": """MSAJCE Boys Hostel details and facilities:

### 🏢 Hostel Capacity & Room Configurations
The Boys Hostel is located inside the college campus, surrounded by greenery.

| Detail Category | Specification Details |
| :--- | :--- |
| **Total Blocks** | 3 Blocks |
| **Accommodating Capacity** | Up to 480 boy students |
| **Non-AC Rooms** | 233 Rooms |
| **AC Rooms** | 6 Rooms |
| **Room Occupancy** | 2 students accommodated per room |
| **Furnishings Provided** | cot, mattress, pillows, bed-spreads, cupboards, study table, chair, fan, water heater, wall hangers |

### 🍴 Mess & Dining Schedule
Nutritious vegetarian and non-vegetarian food is served in the canteen and dining hall. Mess charges are collected annually at the time of admission.

| Meal type | Dining Hours (Working Days) | Dining Hours (Holidays) |
| :--- | :--- | :--- |
| **Breakfast** | 07:00 AM to 08:00 AM | 07:30 AM to 09:00 AM |
| **Lunch** | 01:00 PM to 01:45 PM | 12:30 PM to 02:00 PM |
| **Dinner** | 07:00 PM to 08:30 PM | 07:00 PM to 09:00 PM |

### 📋 Daily Timings & Rules
- **Study Hours**: Morning: **5:00 AM to 7:00 AM** | Evening: **6:00 PM to 7:00 PM** & **9:00 PM to 10:30 PM**.
- **Warden Approvals**: Room allotments and outpasses must be approved strictly by the Warden or Principal Dr. K.S. Srinivasan.
- **Visitors**: Permitted only on holidays from **11:00 AM to 6:00 PM** (must be on the authorized visitors list).""",
        "citations": [{"source": "msajce_hostel.md", "page": "1", "section": "Boys Hostel"}],
    },
    {
        "query": "What are the hostel facilities, room capacity, and details for the Girls Hostel at MSAJCE?",
        "answer": """MSAJCE Girls Hostel details and facilities:

### 🏢 Hostel Capacity & Room Configurations
The Girls Hostel is situated at **Sholinganallur** (approximately 5 KM away from the campus) in a premium, safe residential neighborhood.

| Detail Category | Specification Details |
| :--- | :--- |
| **Total Blocks** | 1 Block |
| **Accommodating Capacity** | Up to 210 girl students |
| **Non-AC Rooms** | 71 Rooms |
| **Room Occupancy** | 3 students accommodated per room |
| **Furnishings Provided** | Cot, mattress, pillows, bed-spreads, study tables with lamps, individual cupboards, wash basin, attached toilet/bath |

### 📶 Amenities & Extended Study Facilities
- **Facilities**: Wi-Fi internet access, land-line telephone, TV hall, indoor games, and reading room with papers and magazines.
- **Extended Study**: Library and computer facilities are made available **until 9:00 PM** inside the hostel for student convenience.
- **Mess & Canteen**: Serves high-quality vegetarian and non-vegetarian meals under the guidance of the Administrative Officer and the Principal. Mess, dining schedules, and study timings match the Boys Hostel guidelines.
- **Visitors**: Permitted only on holidays from **11:00 AM to 6:00 PM** (authorized guardians list required).""",
        "citations": [{"source": "msajce_hostel.md", "page": "1", "section": "Girls Hostel"}],
    },
    {
        "query": "Give an overview of college bus routes, route numbers, boarding points, and timings at MSAJCE.",
        "answer": """Overview of college bus routes, timings, and stops at Mohamed Sathak A.J. College of Engineering (MSAJCE):

### 🚌 Summary of College Bus Routes and Timings
The college operates a fleet of **9 buses** arriving at the OMR Siruseri campus by **8:00 AM**. Timings and stops include:

| Route | Departure Stop | Departure Time | Key Stops / Landmarks |
| :--- | :--- | :--- | :--- |
| **AR 3** | Uthiramerur | 6:00 AM | Guduvanchery, Vandalur Zoo, Kandigai, Kelambakkam |
| **AR 4** | Moolakadai | 6:10 AM | Perambur, Vepery Police Station (6:25 AM), Parrys Corner, Adyar, Palavakkam, Sholinganallur |
| **N/3** | MMDA School | 6:15 AM | Anna Nagar, Loyola College, Saidapet, Velachery Check Post (6:50 AM), Baby Nagar (6:55 AM) |
| **AR 6** | ICF | 6:15 AM | Egmore, Triplicane, Madhyakilash, SRP Tools, Karapakkam |
| **AR 7** | Chunambedu | 5:25 AM | Kalpakkam, Thirukazukundram, Kelambakkam, Padur |
| **AR 8** | Manjambakkam | 5:50 AM | Retteri, Nesapakkam, Ashok Pillar, Kaiveli (6:55 AM), Medavakkam, Sholinganallur |
| **AR 9** | Ennore | 6:15 AM | Mint, Broadway, Central, Royapettah, Mylapore, Adyar, Neelankarai |
| **AR 10** | Porur | 6:25 AM | Pammal, Pallavaram, Chrompet, Tambaram (7:00 AM), Medavakkam, Sholinganallur |
| **R 22** | Nemilichery | 5:50 AM | Poonamallee, Porur, Kathipara, Velachery Bypass (6:45 AM), Kaiveli (7:00 AM), Medavakkam |

### 📞 Transport Contacts
- **Transport Convener**: Dr. K. P. Santhosh Nathan (ped.santhosh@msajce-edu.in)
- **Assistant Convener**: Mr. A. Abdul Gafoor (abdulgafoor@msajce-edu.in)
- **Office Helpline**: +91 99400 04500 / msajce.office@gmail.com

""",
        "citations": [{"source": "msajce_transport.md", "page": "1", "section": "College Bus Routes Summary"}],
    },
    {
        "query": "Tell me about the laboratory facilities, technology centres, and practical learning infrastructure at MSAJCE.",
        "answer": """Mohamed Sathak A.J. College of Engineering (MSAJCE) provides state-of-the-art laboratory and practical skilling infrastructure:

### 🔬 Practical Department Laboratories
- **CSE & IT**: Air-conditioned computer labs equipped with high-speed internet and development environments for programming, databases, web development, and AI/Machine Learning.
- **ECE & EEE**: Advanced communication engineering, microcontrollers, VLSI technology, electrical machines, control systems, and power electronics laboratories.
- **Civil & Mechanical**: Structural engineering, strength of materials, fluid mechanics, surveying, thermal engineering, dynamics, and machine shops.

### 🏢 Centers of Excellence (CoEs) & Skilling Courses
Established under the Industry-Institute Interaction Cell (IIICell), technology centers host specialized value-added and skill development courses:

| Skilling Course Name | NSQF Level | Training Duration | Sanctioned Intake |
| :--- | :--- | :--- | :--- |
| **AI / Machine Learning Developer** | NSQF Level 7 | 756 hours | 30 seats |
| **Computer Hardware & Network Maintenance** | NSQF Level 4 | 1600 hours | 30 seats |
| **Refrigeration & Air Conditioning Technician** | NSQF Level 5 | 3200 hours | 30 seats |
| **Embedded System Design using ARM / Cortex** | NSQF Level 5 | 80 hours | 30 seats |
| **Architectural Drafting in Autodesk Revit** | NSQF Level 4 | 500 hours | 30 seats |
| **Additive Manufacturing Technician in 3D Printing** | NSQF Level 4 | 2080 hours | 30 seats |""",
        "citations": [{"source": "msajce_about.md", "page": "1", "section": "Overview"}],
    },
    {
        "query": "What scholarships are available for students at MSAJCE?",
        "answer": """Mohamed Sathak A.J. College of Engineering (MSAJCE) supports students through various AICTE, Government, and Alumni scholarship schemes:

### 🎓 Available Scholarship Schemes

| Scholarship Scheme | Funding Body | Eligibility / Requirements | Scholarship Amount |
| :--- | :--- | :--- | :--- |
| **Pragati Scheme** | AICTE | Girl students (max 2 per family), family income < 8 Lakhs per annum | Rs. 50,000 / year (800 scholarships for TN) |
| **Saksham Scheme** | AICTE | Specially abled students (>40% disability), family income < 8 Lakhs per annum | Rs. 50,000 / year (all eligible candidates in TN) |
| **Merit-cum-Means** | Ministry of Minority Affairs | Minority community, >50% marks in final exam, family income < 2.5 Lakhs | Rs. 20,000 / year (+12k hostellers, 6k day scholars) |
| **Central Sector Scheme** | MHRD | >80% marks in final examinations, family income < 8 Lakhs per annum | Rs. 10,000 / year (4883 scholarships for TN) |
| **Labour Wards Scheme** | Ministry of Labour & Employment | Wards of Beedi, Mine, and Cine workers, family income < 10,000 / month | Rs. 15,000 / year (all eligible candidates in TN) |

### 🤝 Alumni Merit Scholarships
Managed under the MSAJCE Alumni Association, merit-based financial aid is provided to deserving students (such as recent recipients in the 2024-2028 batch like Mohamed Humdhan, Revathi, Sireesh, and Harini).

For scholarship details and application assistance, contact the Administrative Office (+91 99400 04500 / msajce.office@gmail.com).""",
        "citations": [{"source": "msajce_admission.md", "page": "1", "section": "Undergraduate Scholarships"}],
    },
    {
        "query": "Tell me about MSAJCE's affiliation, accreditation, NAAC grade, and history.",
        "answer": """About Mohamed Sathak A.J. College of Engineering (MSAJCE):

### 📜 Institutional Profile & Affiliations
- **Establishment**: Founded on **5th July 2001** under the aegis of the **Mohamed Sathak Trust**, which has pioneered education for decades.
- **Approvals & Affiliations**: Approved by the **AICTE New Delhi**, affiliated to **Anna University Chennai**, and recognized by the Government of Tamil Nadu.
- **Accreditation**: Accredited by the **National Assessment and Accreditation Council (NAAC)**, Bangalore.
- **Campus**: The college features a sprawling, green campus over **70 acres** located inside the **SIPCOT IT Park** in Siruseri, Chennai. Being situated in a major IT corridor surrounded by MNCs (like TCS, CTS, Infosys, and HCL) offers excellent industrial institute interaction and placement paths.

For admission and general enquiries, contact the college office (+91 99400 04500 / msajce.office@gmail.com).""",
        "citations": [{"source": "msajce_about.md", "page": "1", "section": "Overview"}],
    },
    {
        "query": "What sports facilities, athletic infrastructure, and student clubs are active at MSAJCE?",
        "answer": """MSAJCE provides a highly active and vibrant campus life with balanced focus on academics and co-curricular pursuits:

### 🏆 Sports & Athletic Facilities
- **Facilities**: Features a large playground and specialized indoor sports arenas.
- **Activities**: Supports student participation in local, state, and national athletic meets, Anna University Zonal tournaments, NCC, and NSS activities.
- **Head of Sports**: Managed under the guidance of Physical Education Director Dr. K.P. Santhosh Nathan (ped.santhosh@msajce-edu.in).

### 🎭 Student Clubs & Professional Societies
- **Clubs**: Active clubs include Cultural Clubs (organizing campus cultural festivals), NSS (National Service Scheme), NCC (National Cadet Corps), and Youth Red Cross (YRC) for social service.
- **Professional Chapters**: Hosts active student chapters of major professional organizations (such as IEEE, CSI, ISTE, SAE) to promote competitive hackathons, workshops, and technical webinars.""",
        "citations": [{"source": "msajce_about.md", "page": "1", "section": "Why Join MSAJCE"}],
    },
    {
        "query": "What are the official contact numbers, email addresses, and location details for visiting MSAJCE campus?",
        "answer": """Official contact details and location for Mohamed Sathak A.J. College of Engineering (MSAJCE):

### 📍 Campus Location
- **Address**: 34, Rajiv Gandhi Salai (OMR), Inside SIPCOT IT Park, Siruseri, Egattur, Chennai, Tamil Nadu 603103.
- **Coordinates**: **12°50'08.9"N 80°13'07.0"E** (Plus Code: **R6P9+8C Egattur, Tamil Nadu**).
- **Google Maps Directions**: [Google Maps Directions Link](https://maps.app.goo.gl/nrTgXSwx1h76SjdSA)

### 📞 Contact Numbers & Emails
- **General Office Helpline**: Phone: **+91 99400 04500** | Email: **msajce.office@gmail.com**
- **Admission Enquiries**: Dr. K.P. Santhosh Nathan (ped.santhosh@msajce-edu.in)
- **Principal Office**: Dr. K.S. Srinivasan (principal@msajce-edu.in)
- **Administrative Officer**: Mr. A. Abdul Gafoor (abdulgafoor@msajce-edu.in)
- **Placement Officer**: Mr. S.V. Vinodh (placement@msajce-edu.in)""",
        "citations": [{"source": "msajce_about.md", "page": "1", "section": "Campus Location & Google Maps"}],
    },
]

COMPACT_TO_FULL_CAT = {
    "Department-CSE": "Department — Computer Science & Engineering",
    "Department-CSBS": "Department — CS & Business Systems",
    "Department-CyberSecurity": "Department — CS & Cyber Security",
    "Department-AIDS": "Department — AI & Data Science",
    "Department-AIML": "Department — AI & Machine Learning",
    "Department-IT": "Department — Information Technology",
    "Department-ECE": "Department — Electronics & Communication",
    "Department-EEE": "Department — Electrical & Electronics",
    "Department-Mech": "Department — Mechanical Engineering",
    "Department-Civil": "Department — Civil Engineering",
    "Department-S&H": "Department — Science & Humanities",
    "Alumni": "Alumni Association",
    "Placement": "Placement & Careers",
    "Admission": "Admission & Fees",
    "Hostel": "Hostel & Accommodation",
    "Transport": "Transport & Bus Routes",
    "Research": "Research & Publications",
    "Incubation": "Incubation Centre",
    "TechCentre": "Technology Centre",
    "Library": "Library",
    "IQAC": "IQAC & Accreditation",
    "NIRF": "NIRF Ranking",
    "Sports": "Sports & Athletics",
    "Clubs": "Clubs & Societies",
    "ProfSocieties": "Professional Societies",
    "General": "General — MSAJCE",
}

def normalize_query_for_hash(query: str) -> str:
    """Normalize query: strip whitespace, ALL punctuation (!, ?, ., ,), lowercase, collapse spaces.
    This ensures 'aids!!' and 'aids' hash to the same value for cache lookup."""
    if not query:
        return ""
    import re as _re
    q = query.strip().lower()
    q = _re.sub(r"[!?.,'\"();:\-]+", " ", q)   # replace punctuation with space
    q = _re.sub(r"\s+", " ", q).strip()         # collapse multiple spaces
    return q

def is_fee_query(query: str) -> bool:
    """Check if the query is a fee-related enquiry."""
    if not query:
        return False
    q = query.lower()
    # Check for fee-related keywords with word boundaries to avoid false positives (e.g. feedback)
    patterns = [
        r'\bfe+s?\b',
        r'\btuition\b',
        r'\bcharges?\b',
        r'\bexpenses?\b',
        r'\bcosts?\b',
    ]
    return any(re.search(pat, q) for pat in patterns)

def redact_personal_phone_numbers(text: str) -> str:
    """Redact personal 10-digit mobile numbers from retrieved text while preserving official office numbers."""
    if not text:
        return text
    # Matches patterns like +91 98408 86992, +91-9840886992, 9840886992, 98408-86992, 98408 86992, etc.
    # Pattern: optional +91, 91, or 0, followed by space/dash, then 10 digits (optionally split by space/dash)
    pattern = re.compile(
        r'(?:\+?91|0)?\s*[-–]?\s*\b([6-9]\d{4}\s*[-–]?\s*\d{5}|[6-9]\d{9}|[6-9]\d{2}\s*[-–]?\s*\d{3}\s*[-–]?\s*\d{4})\b'
    )
    def repl(match):
        num = match.group(0)
        # Clean spacing/symbols to check if it's the allowed college office helpline or landline
        clean_num = re.sub(r'\s+|-', '', num)
        # Allowed numbers: 9940004500, landline 27470021 (and ending in 23, 24, 25)
        if '9940004500' in clean_num or '27470021' in clean_num or '27470023' in clean_num or '27470024' in clean_num or '27470025' in clean_num:
            return num
        return "[Redacted]"
    return pattern.sub(repl, text)

def expand_query_abbreviations(query: str) -> str:
    """Expand common shorthand terms and abbreviations to improve search recall."""
    if not query:
        return query
    abbrev_map = {
        r'\bclg\b': 'college',
        r'\bclgs\b': 'colleges',
        r'\bdept\b': 'department',
        r'\bdepts\b': 'departments',
        r'\badmsn\b': 'admission',
        r'\badmsns\b': 'admissions',
        r'\binfo\b': 'information',
        r'\bfee\b': 'fees',
    }
    expanded = query
    for pattern, replacement in abbrev_map.items():
        expanded = re.sub(pattern, replacement, expanded, flags=re.IGNORECASE)
    return expanded

def seed_cache_entries():
    """Pre-populate query_cache with guaranteed correct answers for commonly failed queries."""
    try:
        conn = db_connect(); conn.autocommit = True; cur = conn.cursor()
        for entry in SEED_CACHE:
            q_hash = hashlib.sha256(normalize_query_for_hash(entry["query"]).encode()).hexdigest()
            # Upsert seeded cache entries to ensure they are always correct and updated
            cur.execute("""
                INSERT INTO query_cache (query_hash, query_text, response_text, citations)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (query_hash) DO UPDATE
                    SET response_text = EXCLUDED.response_text,
                        citations = EXCLUDED.citations,
                        created_at = CURRENT_TIMESTAMP
            """, (q_hash, entry["query"], entry["answer"], json.dumps(entry["citations"])))
            logger.info(f"[SeedCache] Seeded/Updated: '{entry['query']}'")
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
    if VERCEL_AI_GATEWAY_KEY:
        logger.info("[Startup] LLM routing: Vercel AI Gateway (primary) → NVIDIA NIM (fallback)")
    else:
        logger.info("[Startup] LLM routing: NVIDIA NIM (direct — no Vercel Gateway key found)")
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
    text = re.sub(r'<!--ent_\d+-->', '', text)  # Strip entity tags (internal metadata)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def clean_links(text: str) -> str:
    """Clean markdown links by removing leftover html anchor tags like </a, </a>, and ** within urls."""
    if not text:
        return text
    def replace_link(match):
        title = match.group(1)
        url = match.group(2)
        url = re.sub(r'</?a[^>]*>', '', url, flags=re.IGNORECASE)
        url = url.replace('</a', '').replace('</a>', '')
        url = url.replace('**', '')
        url = url.replace('\\_', '_')
        return f"[{title}]({url.strip()})"
    
    return re.sub(r'\[([^\]]+)\]\(([^)]+)\)', replace_link, text)


def get_resource_links(keywords: str) -> str:
    """Retrieve relevant verified resource links from msajce_all_resource_links.md based on keywords, prioritizing official ones."""
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        EXCLUDED_DOMAINS = [
            'omicsonline.org', 'ias.ac.in', 'arxiv.org', 'biomedcentral.com', 'scirp.org',
            'iaeme.com', 'hindawi.com', 'cscjournals.org', 'scholar.google.com',
            'onlinebooks.library.upenn.edu', 'publishing.cdlib.org', 'wdl.org',
            'inflibnet.ac.in', 'doaj.org', 'core.ac.uk', 'tiprc.org', 'thescipub.com',
            'ripublication.com', 'internationaljournalssrg.org', 'freecomputerbooks.com',
            'pagebypagebooks.com', 'makeprojects.com', 'ted.com', 'kirkusreviews.com'
        ]

        OFFICIAL_COLLEGE_LINKS = {
            "admission": [
                ("MSAJCE Online Admissions Portal", "https://www.msajce-edu.in/admission.php"),
                ("MSAJCE Student Registration & Online Application Form", "https://enrollonline.co.in/Registration/Apply/MSJACE"),
                ("TNEA Online Admissions Portal", "https://tneaonline.org/"),
                ("Anna University Official Website", "https://www.annauniv.edu/"),
                ("DOTE Official Website", "http://www.tndte.gov.in/site/")
            ],
            "library": [
                ("MSAJCE Central Library Page", "https://www.msajce-edu.in/library.php"),
                ("DELNET Access Portal", "https://delnet.in/"),
                ("J-Gate Plus Portal", "https://jgateplus.com/"),
                ("National Digital Library of India (NDLI)", "https://ndl.iitkgp.ac.in/")
            ],
            "placement": [
                ("MSAJCE Placements & Careers Page", "https://www.msajce-edu.in/placement.php")
            ],
            "hostel": [
                ("MSAJCE Hostel Facilities Page", "https://www.msajce-edu.in/hostel.php")
            ],
            "transport": [
                ("MSAJCE Transport & Bus Routes Page", "https://www.msajce-edu.in/transport.php")
            ],
            "bus": [
                ("MSAJCE Transport & Bus Routes Page", "https://www.msajce-edu.in/transport.php")
            ],
            "fee": [
                ("MSAJCE Online Fee Payment Portal (FeePayr)", "https://www.feepayr.com/"),
                ("MSAJCE Fee Payment Information Page", "https://www.msajce-edu.in/feepay.php")
            ],
            "prospectus": [
                ("MSAJCE College Prospectus (PDF)", "https://www.msajce-edu.in/uploads/College-Prospectus.pdf")
            ],
            "flyer": [
                ("MSAJCE Admission Flyer (PDF)", "https://www.msajce-edu.in/uploads/Admission24-25Flyer.pdf")
            ],
            "disclosure": [
                ("MSAJCE AICTE Mandatory Disclosure (PDF)", "https://www.msajce-edu.in/uploads/MandatoryDisclosure.pdf")
            ],
            "about": [
                ("MSAJCE Institution Overview Page", "https://www.msajce-edu.in/about.php")
            ],
            "research": [
                ("MSAJCE Research & R&D Center", "https://www.msajce-edu.in/research.php")
            ],
            "incubation": [
                ("MSAJCE Incubation & Entrepreneurship Center", "https://www.msajce-edu.in/incubation.php")
            ],
            "iqac": [
                ("MSAJCE Internal Quality Assurance Cell (IQAC)", "https://www.msajce-edu.in/iqac.php")
            ],
            "sports": [
                ("MSAJCE Sports & Athletics Infrastructure Page", "https://www.msajce-edu.in/sports.php")
            ],
            "clubs": [
                ("MSAJCE Clubs & Student Societies Page", "https://www.msajce-edu.in/clubs.php")
            ],
            "alumni": [
                ("MSAJCE Alumni Association Page", "https://www.msajce-edu.in/alumni.php")
            ],
            "contact": [
                ("MSAJCE Official Contact Page", "https://www.msajce-edu.in/contact.php")
            ],
            "naac": [
                ("MSAJCE NAAC Accreditation Page", "https://www.msajce-edu.in/naac.php")
            ],
            "nirf": [
                ("MSAJCE NIRF Ranking Page", "https://www.msajce-edu.in/nirf.php")
            ],
            "scholarship": [
                ("MSAJCE Scholarships & Financial Aid Page", "https://www.msajce-edu.in/scholarship.php"),
                ("AICTE Pragati & Saksham Scheme Portal", "https://www.aicte-india.org/bureaus/esb/activities/pragati-saksham")
            ],
            "faculty": [
                ("MSAJCE Faculty & Staff Directory", "https://www.msajce-edu.in/faculty.php")
            ],
            "principal": [
                ("MSAJCE Principal's Message", "https://www.msajce-edu.in/principal.php")
            ],
            "iqac": [
                ("MSAJCE Internal Quality Assurance Cell (IQAC)", "https://www.msajce-edu.in/iqac.php")
            ]
        }

        OFFICIAL_DEPT_LINKS = {
            "cse": ("MSAJCE Department of Computer Science & Engineering", "https://www.msajce-edu.in/cse.php"),
            "it": ("MSAJCE Department of Information Technology", "https://www.msajce-edu.in/it.php"),
            "ece": ("MSAJCE Department of Electronics & Communication Engineering", "https://www.msajce-edu.in/ece.php"),
            "eee": ("MSAJCE Department of Electrical & Electronics Engineering", "https://www.msajce-edu.in/eee.php"),
            "mech": ("MSAJCE Department of Mechanical Engineering", "https://www.msajce-edu.in/mech.php"),
            "civil": ("MSAJCE Department of Civil Engineering", "https://www.msajce-edu.in/civil.php"),
            "aiml": ("MSAJCE B.Tech CSE - AI & Machine Learning Page", "https://www.msajce-edu.in/aiml.php"),
            "aids": ("MSAJCE B.Tech AI & Data Science Page", "https://www.msajce-edu.in/aids.php"),
            "csbs": ("MSAJCE B.Tech Computer Science & Business Systems Page", "https://www.msajce-edu.in/csbs.php"),
            "cyber": ("MSAJCE B.Tech CSE - Cyber Security Page", "https://www.msajce-edu.in/cyber.php"),
            "vlsi": ("MSAJCE B.Tech VLSI Design & Technology Page", "https://www.msajce-edu.in/vlsi.php"),
            "ece-act": ("MSAJCE B.Tech Advanced Communication Technology Page", "https://www.msajce-edu.in/ece-act.php")
        }

        def clean_link_item(title, url):
            # Clean URL
            url = re.sub(r'</?a[^>]*>', '', url, flags=re.IGNORECASE)
            url = url.replace('</a', '').replace('</a>', '').replace('**', '').replace('\\_', '_').strip()
            url = url.replace('msjace-edu.in', 'msajce-edu.in')
            url = url.replace('msjace_edu_in', 'msajce-edu.in')
            # Clean Title
            title = title.replace('**', '').replace('\\_', '_').strip()
            # Map generic/inaccurate titles based on the URL paths
            url_lower = url.lower()
            if 'admission.php' in url_lower:
                title = "MSAJCE Online Admissions Page"
            elif 'library.php' in url_lower:
                title = "MSAJCE Central Library Page"
            elif 'placement.php' in url_lower:
                title = "MSAJCE Placements Page"
            elif 'hostel.php' in url_lower:
                title = "MSAJCE Hostel Facilities Page"
            elif 'transport.php' in url_lower:
                title = "MSAJCE Transport & Bus Routes Page"
            elif 'feepay.php' in url_lower:
                title = "MSAJCE Fee Payment Information"
            elif 'feepayr.com' in url_lower:
                title = "MSAJCE Online Fee Payment Portal (FeePayr)"
            elif 'enrollonline.co.in' in url_lower:
                title = "MSAJCE Student Registration & Online Application Form"
            elif 'college-prospectus.pdf' in url_lower:
                title = "MSAJCE College Prospectus (PDF)"
            elif 'admission24-25flyer.pdf' in url_lower:
                title = "MSAJCE Admission 2024-25 Flyer (PDF)"
            
            return title, url

        links = []
        seen_urls = set()
        
        # 1. Direct Keyword Matching (Pre-seeded exact official links)
        kw_lower = keywords.lower()
        for key, val_list in OFFICIAL_COLLEGE_LINKS.items():
            if key in kw_lower:
                for title, url in val_list:
                    if url not in seen_urls:
                        seen_urls.add(url)
                        links.append(f"- [{title}]({url})")
                        
        for key, (title, url) in OFFICIAL_DEPT_LINKS.items():
            if key in kw_lower:
                if url not in seen_urls:
                    seen_urls.add(url)
                    links.append(f"- [{title}]({url})")

        # 2. Qdrant Search Fallback
        link_filter = Filter(
            must=[
                FieldCondition(key="source_file", match=MatchValue(value="msajce_all_resource_links.md"))
            ]
        )
        q_vec = get_nvidia_embedding(keywords, input_type="query")
        if hasattr(qdrant_client, "query_points"):
            r = qdrant_client.query_points(
                collection_name=COLLECTION_NAME,
                query=q_vec,
                query_filter=link_filter,
                limit=15,
                with_payload=True
            )
            hits = r.points
        else:
            hits = qdrant_client.search(
                collection_name=COLLECTION_NAME,
                query_vector=q_vec,
                query_filter=link_filter,
                limit=15
            )
        
        for h in hits:
            text = h.payload.get("text", "")
            matches = re.findall(r'\[([^\]]+)\]\((https?://[^\)]+)\)', text)
            for title, url in matches:
                # Basic cleaning
                title, url = clean_link_item(title, url)
                
                # Check for excluded domains
                is_excluded = any(domain in url.lower() for domain in EXCLUDED_DOMAINS)
                if is_excluded:
                    continue
                
                if url not in seen_urls:
                    seen_urls.add(url)
                    links.append(f"- [{title}]({url})")
                if len(links) >= 6:
                    break
            if len(links) >= 6:
                break
        
        if links:
            return "\n\n### 🔗 Relevant Links & Resources\n" + "\n".join(links)
    except Exception as e:
        logger.warning(f"[ResourceLinks] Failed: {e}")
    return ""



# ── LLM routing helpers ────────────────────────────────────────────────────────
GATEWAY_PROXY_URL = os.getenv("GATEWAY_PROXY_URL", "https://lorin-ai.vercel.app")

# Models used for small/fast tasks via Vercel AI Gateway (Node.js proxy)
_VERCEL_MODELS = {
    "classify":  "google/gemini-2.5-flash-lite",   # intent classification
    "rewrite":   "deepseek/deepseek-v4-0709",       # query rewriting
    "faithful":  "deepseek/deepseek-v4-0709",       # faithfulness check
    "followup":  "meta/llama-3.1-8b",               # follow-up generation
}

def call_vercel(messages: list, task: str = "classify", temperature: float = 0.0, max_tokens: int = 200, timeout: float = 8.0) -> dict:
    """
    Route SMALL/FAST tasks through the Node.js Gateway Proxy → Vercel AI Gateway.
    Falls back to NVIDIA NIM if proxy is unavailable.
    task: one of 'classify', 'rewrite', 'faithful', 'followup'
    """
    model = _VERCEL_MODELS.get(task, "google/gemini-2.5-flash-lite")
    req_body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    if task in ("classify", "rewrite", "faithful"):
        req_body["response_format"] = {"type": "json_object"}
        
    try:
        res = requests.post(
            f"{GATEWAY_PROXY_URL}/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json=req_body,
            timeout=timeout,
        )
        res.raise_for_status()
        logger.debug(f"[Vercel] {task} → {model}")
        return res.json()
    except requests.exceptions.ConnectionError:
        logger.debug(f"[Vercel] Proxy not running for {task}, falling back to NVIDIA...")
    except Exception as e:
        logger.warning(f"[Vercel] {task} failed ({e}), falling back to NVIDIA...")

    # NVIDIA fallback for small tasks
    fallback_body = {
        "model": "meta/llama-3.1-8b-instruct",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    if task in ("classify", "rewrite", "faithful"):
        fallback_body["response_format"] = {"type": "json_object"}
        
    res = requests.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"},
        json=fallback_body,
        timeout=timeout,
    )
    res.raise_for_status()
    logger.debug(f"[NVIDIA] {task} fallback → meta/llama-3.1-8b-instruct")
    return res.json()


def call_nvidia(messages: list, temperature: float = 0.1, max_tokens: int = 1000, stream: bool = False, timeout: float = 60.0):
    """
    Route MAIN/HEAVY tasks (RAG answer, guidance) directly through NVIDIA NIM.
    Uses meta/llama-3.1-8b-instruct for lightning-fast generation.
    """
    headers = {"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"}
    res = requests.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        headers=headers,
        json={"model": "meta/llama-3.1-8b-instruct", "messages": messages,
              "temperature": temperature, "max_tokens": max_tokens, "stream": stream},
        timeout=timeout,
        stream=stream,
    )
    res.raise_for_status()
    logger.debug("[NVIDIA] main answer → meta/llama-3.1-8b-instruct")
    if stream:
        return res
    return res.json()


def call_vercel_main(messages: list, temperature: float = 0.1, max_tokens: int = 1000, stream: bool = False, timeout: float = 60.0):
    """Vercel gateway endpoint for main generation tasks."""
    req_body = {
        "model": "google/gemini-2.5-flash-lite",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream
    }
    res = requests.post(
        f"{GATEWAY_PROXY_URL}/v1/chat/completions",
        headers={"Content-Type": "application/json"},
        json=req_body,
        timeout=timeout,
        stream=stream,
    )
    res.raise_for_status()
    logger.debug("[Vercel] main answer → google/gemini-2.5-flash-lite")
    if stream:
        return res
    return res.json()


def call_llm_multi_agent(messages: list, temperature: float = 0.1, max_tokens: int = 1000, timeout: float = 60.0):
    """
    Races NVIDIA NIM and Vercel AI Gateway for the fastest response (Multi-Agent).
    """
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(call_nvidia, messages, temperature, max_tokens, False, timeout)
        f2 = executor.submit(call_vercel_main, messages, temperature, max_tokens, False, timeout)
        done, not_done = concurrent.futures.wait([f1, f2], return_when=concurrent.futures.FIRST_COMPLETED)
        
        # Cancel the slower request if possible (ThreadPoolExecutor doesn't truly cancel running tasks, but we ignore it)
        try:
            res = list(done)[0].result()
            logger.info(f"[MultiAgent] Fastest agent won the race!")
            return res
        except Exception as e:
            logger.warning(f"[MultiAgent] Primary agent failed ({e}), waiting for fallback...")
            if not_done:
                # Wait for the other one
                done2, _ = concurrent.futures.wait(not_done, timeout=timeout)
                if done2:
                    return list(done2)[0].result()
            raise



# Backwards-compat alias (used by call sites not yet migrated)
def call_llm(messages: list, model: str = "openai/gpt-4o-mini", temperature: float = 0.1,
             max_tokens: int = 1000, stream: bool = False, timeout: float = 30.0):
    """Legacy alias — routes to call_nvidia for main answer tasks."""
    return call_nvidia(messages, temperature=temperature, max_tokens=max_tokens,
                       stream=stream, timeout=timeout)


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


def generate_followup_questions(query: str, context_text: str = "") -> List[str]:
    """Generate 3 follow-up questions based only on the query and context to save tokens and allow parallelization."""
    if not query:
        return []
        
    system_prompt = (
        "You are a follow-up question generator for a college chatbot.\n"
        "Generate 3 logical follow-up questions the user might ask NEXT, based on their CURRENT QUERY and the CONTEXT retrieved.\n"
        "RULES:\n"
        "1. Do NOT repeat anything already answered.\n"
        "2. Keep them short, relevant, and self-contained.\n"
        "3. Output ONLY a JSON array of 3 strings.\n"
        "Example: [\"What is the hostel fee?\", \"Where is it located?\", \"Who is the HOD?\"]"
    )
    user_prompt = (
        f"USER QUERY: {query}\n"
        f"CONTEXT: {context_text[:1000]}\n\n"
        "Generate 3 follow-up questions (JSON array only):"
    )
    try:
        rj = call_vercel(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            task="followup",
            temperature=0.4,
            max_tokens=160,
            timeout=5.0,
        )
        content = rj["choices"][0]["message"]["content"].strip()
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

    developer_keywords = ["who is ram", "who is ramanathan", "who is zendrum", "who is the developer", "who created", "who built", "creator of", "developer of", "ur host", "your host", "who made you", "tell me about ram", "tell me about the developer", "about ramanathan", "about the developer", "know more about ramanathan", "know more about ram", "know more about the developer"]
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
        "You are a strict backend query classifier for MSAJCE. Your ONLY job is to categorize the user's input and extract keywords.\n"
        "DO NOT answer the user's question. DO NOT converse. DO NOT write any intro or explanation. You must ONLY output a JSON object.\n"
        "Intents: 'greeting', 'goodbye', 'compliment', 'guidance_query', 'college_query'.\n"
        "For college_query: extract core search keywords (strip honorifics like sir, maam, dr, mr, mrs).\n"
        f"Available categories for category field: {category_list_str}\n"
        "Category Guidelines:\n"
        "- Use 'Admission' for queries about courses/programs offered, admission eligibility, seat intakes, fees, scholarships, or cutoff marks.\n"
        "- Use 'Placement' for placement statistics, salary packages, recruiters, or internship details.\n"
        "- Use the specific department name (e.g. 'Department-CSE') ONLY for queries specific to a single department (e.g. HOD name, HOD email, department vision/mission, faculty list, or syllabus of that department).\n"
        "Set category=null if the query is about a specific staff member/person, or if it doesn't clearly match any category.\n"
        "If you assign a category, you MUST set category_confidence to 1.0. If you do not assign a category (set category=null), set category_confidence to 0.0.\n"
        "Output format MUST be exactly this JSON schema:\n"
        '{"intent": "...", "keywords": "...", "category": "...", "category_confidence": 0.0, "direct_response": ""}'
    )
    try:
        rj = call_vercel(
            messages=[{"role":"system","content":system_prompt},{"role":"user","content":query}],
            task="classify",
            temperature=0.0,
            max_tokens=150,
            timeout=8.0,
        )
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
        rj = call_nvidia(
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": user_query}],
            temperature=0.3,
            max_tokens=1000,
            timeout=45.0,
        )
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
    hint = get_transport_hints(user_query)
    if hint:
        context_str += hint
        logger.info(f"[LLM Prompt Debug] Appended transport hints: {hint.strip()}")
    logger.info(f"[LLM Prompt Debug] context_str: {context_str}")
    max_tok = _pick_max_tokens(user_query, context_blocks)

    system_prompt = LLM_SYSTEM_PROMPT.replace('{context_str}', context_str)
    # Build messages: system prompt + prior history turns + current question
    history_msgs = get_recent_history(session_id) if session_id else []
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history_msgs)
    messages.append({"role": "user", "content": user_query})

    try:
        rj = call_llm_multi_agent(
            messages=messages,
            temperature=0.1,
            max_tokens=max_tok,
            timeout=60.0,
        )
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
    hint = get_transport_hints(user_query)
    if hint:
        context_str += hint
        logger.info(f"[LLM Prompt Debug] Appended transport hints: {hint.strip()}")
    logger.info(f"[LLM Prompt Debug] context_str: {context_str}")
    max_tok = _pick_max_tokens(user_query, context_blocks)

    system_prompt = LLM_SYSTEM_PROMPT.replace('{context_str}', context_str)
    import json
    try:
        res = call_nvidia(
            messages=[{"role":"system","content":system_prompt},
                       {"role":"user","content":user_query}],
            temperature=0.1,
            max_tokens=max_tok,
            stream=True,
            timeout=60.0,
        )
        
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
                    model_used = "meta/llama-3.1-70b-instruct"

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
            h = hashlib.sha256(normalize_query_for_hash(query_text).encode()).hexdigest()
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

        # Fetch context for evaluation (ground truth reference documents)
        candidates = hybrid_retriever.retrieve(user_query, user_query, category=None) if hybrid_retriever else []
        context_str = ""
        if candidates:
            context_str = "\n\n".join(clean_chunk(c.get("text", "") or c.get("payload", {}).get("text", "")) for c in candidates[:5] if (c.get("text", "") or c.get("payload", {}).get("text", "")))

        # Step 1: LLM Evaluator (Judge) prompt with Reference Context
        judge_prompt = f"""You are an objective AI evaluator analyzing negative user feedback.
User Question: "{user_query}"
Assistant Answer: "{original_answer}"

GROUND TRUTH REFERENCE CONTEXT:
{context_str}

Evaluate if the assistant answer has a genuine factual error, contradiction, hallucination, or mismatch relative to the ground truth reference context.
If the assistant gave a correct answer based on the reference context, but the user is just unhappy with the policy (e.g. fee is too high, no refund, bus timings do not suit them), classify it as USER_DISSATISFACTION_OR_FUN.
If the assistant gave an answer that contradicts the context, contains incorrect figures/names, or failed to answer the question properly, classify it as REAL_QA_MISMATCH.

Respond ONLY with valid JSON matching this schema:
{{
  "verdict": "REAL_QA_MISMATCH" or "USER_DISSATISFACTION_OR_FUN",
  "reason": "Short 1-sentence explanation of why the answer is wrong or correct."
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
                query_hash = hashlib.sha256(normalize_query_for_hash(user_query).encode()).hexdigest()
                cur.execute("DELETE FROM query_cache WHERE query_hash = %s", (query_hash,))
                
                citations_json = json.dumps(citations)
                cur.execute("""
                    INSERT INTO query_cache (query_hash, query_text, response_text, citations)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (query_hash) DO UPDATE
                        SET response_text = EXCLUDED.response_text,
                            citations = EXCLUDED.citations,
                            created_at = CURRENT_TIMESTAMP
                """, (query_hash, normalize_query_for_hash(user_query), corrected_answer, citations_json))
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

        # Purge bad cache immediately on negative rating (-1)
        if req.rating == -1:
            cur.execute("""
                SELECT content FROM chat_messages 
                WHERE session_id = %s::uuid AND role = 'user' AND created_at <= (
                    SELECT created_at FROM chat_messages WHERE id = %s::uuid
                )
                ORDER BY created_at DESC LIMIT 1
            """, (req.session_id, req.message_id))
            user_row = cur.fetchone()
            if user_row:
                user_query = user_row[0]
                q_hash = hashlib.sha256(normalize_query_for_hash(user_query).encode()).hexdigest()
                # Primary: hash-based exact delete (current normalizer)
                cur.execute("DELETE FROM query_cache WHERE query_hash = %s", (q_hash,))
                deleted_exact = cur.rowcount
                # Secondary: fuzzy delete — catches entries stored by old normalizers
                # Match on first 40 chars of the normalized query text
                fuzzy_prefix = normalize_query_for_hash(user_query)[:40]
                if fuzzy_prefix:
                    cur.execute("DELETE FROM query_cache WHERE query_text ILIKE %s", (f"{fuzzy_prefix}%",))
                    deleted_fuzzy = cur.rowcount
                else:
                    deleted_fuzzy = 0
                logger.info(f"[Feedback] Purged cache for '{user_query[:50]}': exact={deleted_exact}, fuzzy={deleted_fuzzy}")

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


# ── Transport stop matching logic (Req 11, 12, 17) ───────────────────────────
TRANSPORT_ROUTE_MAP = {}
try:
    _transport_file = os.path.join(os.path.dirname(__file__), "dataset", "msajce_transport.md")
    if os.path.exists(_transport_file):
        with open(_transport_file, "r", encoding="utf-8") as f:
            _transport_content = f.read()
        _sections = re.split(r"###\s+Route\s+", _transport_content)
        _stop_rx = re.compile(r"([A-Za-z0-9\.\s’'&\-\/]+?)\s+at\s+\d{1,2}:\d{2}\s+(?:AM|PM)", re.IGNORECASE)
        for _sec in _sections[1:]:
            _lines = _sec.strip().split("\n")
            _route_header = _lines[0].strip()
            _route_name = _route_header.split("(")[0].strip()
            _stops = []
            for _line in _lines[1:]:
                _matches = _stop_rx.findall(_line)
                for _m in _matches:
                    _stop_clean = _m.strip()
                    _stop_clean = re.sub(r"^.*?passes through\s+", "", _stop_clean, flags=re.IGNORECASE)
                    _stop_clean = re.sub(r"^.*?starts from\s+", "", _stop_clean, flags=re.IGNORECASE)
                    _stop_clean = re.sub(r"^.*?departs from\s+", "", _stop_clean, flags=re.IGNORECASE)
                    _stop_clean = re.sub(r"^.*?arrives at\s+", "", _stop_clean, flags=re.IGNORECASE)
                    _stop_clean = _stop_clean.strip(".!?, \t\n")
                    _stop_lower = _stop_clean.lower()
                    if any(_w in _stop_lower for _w in ["contact", "number", "whose", "driven"]):
                        continue
                    if len(_stop_clean) > 35 or len(_stop_clean) < 3:
                        continue
                    _stops.append(_stop_clean)
            TRANSPORT_ROUTE_MAP[_route_name] = _stops
except Exception as _e:
    logger.error(f"[Startup] Failed to parse transport stops: {_e}")

def get_transport_hints(query: str) -> str:
    query_lower = query.lower()
    # Normalize spelling variations
    query_lower = query_lower.replace("pallikaranai", "pallikarani")
    
    generic_words = {
        "check", "post", "bypass", "junction", "stop", "railway", "station",
        "hospital", "tollgate", "school", "college", "temple", "church",
        "mosque", "hotel", "hostel", "park", "street", "road", "market",
        "court", "corner", "beach", "zoo", "gate", "bus", "route", "passes",
        "through", "starts", "from", "departs", "arrives", "goes", "will", "does"
    }
    
    matches = []
    query_words = re.findall(r"\w+", query_lower)
    for route, stops in TRANSPORT_ROUTE_MAP.items():
        for stop in stops:
            stop_lower = stop.lower()
            if stop_lower in query_lower:
                matches.append((route, stop))
                continue
            stop_words = [w for w in re.findall(r"\w+", stop_lower) if w not in generic_words and len(w) > 2]
            for sw in stop_words:
                if sw in query_words:
                    matches.append((route, stop))
                    break
    
    if not matches:
        return ""
        
    hint_lines = []
    seen_routes = {}
    for route, stop in matches:
        seen_routes[route] = stop
        
    for route, stop in seen_routes.items():
        hint_lines.append(f"- Route {route} passes through {stop} (You MUST format all the stops and timings of Route {route} in the markdown table, not just {stop})")
        
    return (
        "\n[DIRECT MATCH HINT: Based on database matching, the following college bus route(s) stop at or near your requested location. "
        "You MUST state that these routes go there, prioritize listing their route tables with all their stops and timings, and NEVER claim you couldn't find a direct route for them:\n"
        + "\n".join(hint_lines)
        + "]\n"
    )


@app.post("/api/chat")
@limiter.limit("10/minute;25/day")
def chat_endpoint(req: ChatRequest, request: Request):
    user_query = expand_query_abbreviations(req.message.strip())
    if not user_query:
        raise HTTPException(400, "Query cannot be empty.")

    # ── Step 0: Direct Fee Interception ───────────────────────────────────────
    if is_fee_query(user_query):
        logger.info(f"[FeeInterceptor] Intercepted fee-related query: '{user_query[:60]}'")
        ans = (
            "For details regarding the fee structure (including tuition fees, hostel, transport, or exam fees), "
            "please contact our Admission Office directly:\n\n"
            "📞 **Admission Helpline:** +91 99400 04500 / 044 - 2747 0021\n"
            "👤 **Head of Admission (Dr. K. P. Santhosh Nathan):** ped.santhosh@msajce-edu.in\n"
            "✉️ **Email:** msajce.office@gmail.com"
        )
        save_message(req.session_id, "user", user_query)
        msg_id = save_message(req.session_id, "assistant", ans, {"intent": "fee_redirection"})
        return ChatResponse(
            answer=ans,
            citations=[],
            modelUsed="fee-interceptor",
            isCached=False,
            tokenUsage=TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            message_id=msg_id,
            followups=[]
        )

    # ── Step 0a: Exact Cache lookup (bypasses all LLM processing) ─────────────
    q_hash = hashlib.sha256(normalize_query_for_hash(user_query).encode()).hexdigest()
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
                redacted_ans = redact_personal_phone_numbers(row[0])
                cached_msg_id = save_message(req.session_id, "assistant", redacted_ans, {"from_cache": True})
                return ChatResponse(answer=redacted_ans, citations=cits,
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

    if has_history:
        active_query, was_rewritten = query_rewriter.rewrite(corrected_query, req.session_id)
    else:
        active_query = corrected_query
        was_rewritten = False

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        fut_embed = executor.submit(get_nvidia_embedding, active_query, "query")
        fut_prep = executor.submit(preprocess_query, active_query)
        
        q_vec = fut_embed.result()
        prep = fut_prep.result()

    # ── Step 2: Intent + keyword expansion on active_query ──────────────────────
    intent    = prep.get("intent", "college_query")
    
    # Re-evaluate hardcoded fast-paths on active_query (in case QueryRewriter resolved pronouns like 'him' -> 'Ramanathan')
    aq_lower = active_query.lower().strip("?.! ")
    greetings = {"hi","hello","hey","greetings","good morning","good afternoon","good evening","howdy"}
    goodbyes  = {"bye","goodbye","see you","exit","quit","talk to you later","cya"}
    thanks    = {"thanks","thank you","thank you so much","great","awesome","perfect","nice"}
    developer_keywords = ["who is ram", "who is ramanathan", "who is zendrum", "who is the developer", "who created", "who built", "creator of", "developer of", "ur host", "your host", "who made you", "tell me about ram", "tell me about the developer", "about ramanathan", "about the developer", "know more about ramanathan", "know more about ram", "know more about the developer"]

    if aq_lower in greetings:
        intent = "greeting"
        prep["direct_response"] = "Hello! 😊 I'm Lorin, your MSAJCE campus assistant. What would you like to know?"
    elif aq_lower in goodbyes:
        intent = "goodbye"
        prep["direct_response"] = "Goodbye! It was great chatting with you. Feel free to come back anytime. 😊"
    elif aq_lower in thanks:
        intent = "compliment"
        prep["direct_response"] = "You're welcome! Happy to help. If you have more questions about MSAJCE, just ask! 😊"
    elif any(k in aq_lower for k in developer_keywords) or aq_lower in ["ram", "ramanathan", "zendrum", "developer", "creator"]:
        intent = "developer_query"
        prep["direct_response"] = "I was developed by **Ramanathan S.** (B.Tech IT, MSAJCE 2024-2028 batch). He is the creator of this chatbot, Lorin AI, Listen Zenify, ZenDrum Booking, and Zen Hostel. You can learn more about him and his work at his portfolio: [https://ramanathanportfolio.vercel.app](https://ramanathanportfolio.vercel.app)"
    else:
        # If the Vercel LLM classified it as a conversational intent but it didn't match our strict hardcoded lists,
        # it is likely a hallucinated intent. Force it back to college_query so it gets answered via RAG.
        if intent in ("greeting", "goodbye", "compliment", "developer_query"):
            intent = "college_query"

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
    if category and category in COMPACT_TO_FULL_CAT:
        category = COMPACT_TO_FULL_CAT[category]
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
    # Override: transport/bus queries misclassified as guidance_query must go through college_query path
    transport_kw_check = [
        "bus", "route", "stop", "timing", "transport", "travel", "driver",
        "velachery", "guindy", "tambaram", "adyar", "ennore", "porur",
        "sholinganallur", "kelambakkam", "broadway", "central",
    ]
    if intent == "guidance_query" and any(k in active_query.lower() for k in transport_kw_check):
        logger.info(f"[Intent Override] Forcing guidance_query → college_query for transport query: '{active_query[:50]}'")
        intent = "college_query"

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

        context_text_for_followups = "\n".join([b["text"] for b in context_blocks])
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            fut_ans = executor.submit(generate_guidance_answer, active_query, context_blocks)
            fut_foll = executor.submit(generate_followup_questions, active_query, context_text_for_followups)
            answer, g_usage = fut_ans.result()
            followups = fut_foll.result()
            
        answer = clean_links(answer)
        redacted_ans = re.sub(r'<!--ent_\d+-->', '', answer)  # Strip leaked entity tags
        redacted_ans = redact_personal_phone_numbers(redacted_ans)
        msg_id = save_message(req.session_id, "assistant", redacted_ans, {"intent": "guidance_query", "followups": followups})

        total_p = p_usage.get("prompt_tokens",0) + g_usage.get("prompt_tokens",0)
        total_c = p_usage.get("completion_tokens",0) + g_usage.get("completion_tokens",0)
        total_t = p_usage.get("total_tokens",0) + g_usage.get("total_tokens",0)

        return ChatResponse(
            answer=redacted_ans,
            citations=[Citation(**c) for c in citations_list],
            modelUsed="multi-agent-fastest",
            isCached=False,
            tokenUsage=TokenUsage(prompt_tokens=total_p, completion_tokens=total_c, total_tokens=total_t),
            message_id=msg_id,
            followups=followups,
        )

    retrieval_query = active_query  # use rewritten active_query for embedding/BM25

    # Transport Query Booster: If user asks about buses, routes, timings, or Chennai stops, force category to null & enrich search terms
    transport_keywords = [
        "bus", "route", "stop", "timing", "velachery", "guindy", "kathipara", "tharamani", "medavakkam", 
        "pallikaranai", "pallikarani", "thoraipakkam", "ennore", "porur", "nemilichery", "uthiramerur", "moolakadai", 
        "icf", "chunambedu", "tambaram", "adyar", "saidapet", "broadway", "central", "parrys", 
        "perambur", "retteri", "padi", "ashok pillar", "poonnamalle", "sholinganallur", "kelambakkam", 
        "sipcot", "maraimalai nagar", "guduvanchery", "perungalathur", "vandalur", "chrompet", 
        "pallavaram", "thiruvanmiyur", "neelankarai", "akkarai", "perumpakkam", "kilkattalai", 
        "madipakkam", "kovilampakkam", "transport", "travel", "driver", "ar3", "ar4", "ar5", "ar6", 
        "ar7", "ar8", "ar9", "ar10", "r21", "r22", "n/3", "n3", "ar 3", "ar 4", "ar 5", "ar 6", 
        "ar 7", "ar 8", "ar 9", "ar 10", "r 21", "r 22"
    ]
    if any(k in active_query.lower() for k in transport_keywords):
        # Do NOT set category="Transport" because it causes 0 hits if the DB payload doesn't perfectly match,
        # which triggers an unfiltered fallback. source_file routing alone is strictly better.
        category = None
        source_file = "msajce_transport.md"
    else:
        source_file = None
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
        candidates = hybrid_retriever.retrieve(retrieval_query, keywords, category, entity_id, q_vec=q_vec, source_file=source_file)
        candidates = [c for c in candidates if c.get("payload", {}).get("source_file") != "msajce_all_resource_links.md"]
        # Hard post-filter: when source_file routing is active, strip any non-matching chunks that leaked through BM25/dense fusion
        if source_file:
            candidates = [c for c in candidates if c.get("payload", {}).get("source_file") == source_file]

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

    # ── Step 5b: Parent-Child Chunk Expansion ─────────────────────────────────
    # We fetch adjacent sibling chunks (chunk_index - 1 to + 2) for each top chunk
    # to reconstruct a larger 800-1200 token parent context block without cutoff.
    
    valid_top_payloads = []
    sibling_queries = []
    seen_indices = set()
    
    for rank in top:
        idx = rank["index"]
        if idx >= len(payloads):
            continue
        payload = payloads[idx]
        
        parent_id = payload.get("parent_id")
        chunk_index = payload.get("chunk_index")
        total_chunks = payload.get("total_chunks", 1)
        
        if not parent_id or chunk_index is None:
            valid_top_payloads.append(payload)
            continue
            
        seen_indices.add((parent_id, chunk_index))
        valid_top_payloads.append(payload)
        
        # Build query for sibling chunks [chunk_index - 1, chunk_index + 1, chunk_index + 2]
        target_indices = []
        for i in range(chunk_index - 1, chunk_index + 3):
            if i != chunk_index and 1 <= i <= total_chunks:
                if (parent_id, i) not in seen_indices:
                    target_indices.append(i)
                    seen_indices.add((parent_id, i))
                    
        if target_indices:
            sibling_queries.append(
                Filter(
                    must=[
                        FieldCondition(key="parent_id", match=MatchValue(value=parent_id)),
                        FieldCondition(key="chunk_index", match=MatchAny(any=target_indices))
                    ]
                )
            )

    sibling_payloads = []
    if sibling_queries:
        try:
            # Batch fetch all missing siblings in a single Qdrant query
            sibling_filter = Filter(should=sibling_queries)
            sibling_hits = qdrant_client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=sibling_filter,
                limit=100,
                with_payload=True
            )[0]
            sibling_payloads = [h.payload for h in sibling_hits]
            logger.info(f"[Parent-Child] Fetched {len(sibling_payloads)} sibling chunks for expansion")
        except Exception as e:
            logger.error(f"[Parent-Child] Failed to fetch siblings: {e}")

    # Group chunks by parent_id to reconstruct context
    all_payloads_to_merge = valid_top_payloads + sibling_payloads
    parent_groups = {}
    for p in all_payloads_to_merge:
        pid = p.get("parent_id") or hashlib.md5(p.get("text", "").encode()).hexdigest()
        if pid not in parent_groups:
            parent_groups[pid] = []
        parent_groups[pid].append(p)

    context_blocks = []
    citations_list = []
    context_str_parts = []
    seen_hashes = set()

    for pid, group in parent_groups.items():
        # Sort sequentially by chunk index
        group.sort(key=lambda x: x.get("chunk_index", 0))
        
        merged_text_parts = []
        last_idx = None
        
        for p in group:
            text = redact_personal_phone_numbers(clean_chunk(p.get("text", "")))
            if not text or len(text) < 30:
                continue
                
            th = hashlib.md5(text.encode()).hexdigest()
            if th in seen_hashes:
                continue
            seen_hashes.add(th)
            
            idx = p.get("chunk_index", 0)
            if last_idx is not None and idx > last_idx + 1:
                merged_text_parts.append("\n\n[...]\n\n")
            elif last_idx is not None:
                merged_text_parts.append("\n\n")
                
            merged_text_parts.append(text)
            last_idx = idx
            
        if not merged_text_parts:
            continue
            
        merged_text = "".join(merged_text_parts)
        first_p = group[0]
        
        context_blocks.append({
            "text":          merged_text,
            "section_title": first_p.get("section_title", ""),
            "category":      first_p.get("category", ""),
        })
        context_str_parts.append(merged_text)
        citations_list.append({
            "source":  first_p.get("source_file", "College Handbook"),
            "page":    str(first_p.get("page_number", "")),
            "section": first_p.get("section_title", ""),
        })

    if not context_blocks:
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
                
                redacted_ans = re.sub(r'<!--ent_\d+-->', '', answer_text)  # Strip leaked entity tags
                redacted_ans = redact_personal_phone_numbers(redacted_ans)
                msg_id_val = save_message(req.session_id, "assistant", redacted_ans, trace, prompt_tokens=total_p, completion_tokens=total_c, citations=citations_list)
                
                # Cache it
                try:
                    conn = db_connect(); conn.autocommit = True; cur = conn.cursor()
                    cur.execute("""
                        INSERT INTO query_cache (query_hash, query_text, response_text, citations)
                        VALUES (%s,%s,%s,%s) ON CONFLICT (query_hash) DO NOTHING
                    """, (q_hash, corrected_query, redacted_ans, json.dumps(citations_list)))
                    cur.close(); conn.close()
                except Exception:
                    pass
                
                # Send final metadata
                yield f"data: {json.dumps({'type': 'metadata', 'citations': citations_list, 'followups': followups_val, 'message_id': msg_id_val, 'tokenUsage': {'prompt_tokens': total_p, 'completion_tokens': total_c, 'total_tokens': total_p + total_c}})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")
    
    logger.info("[Chat] Starting main LLM answer generation and follow-ups in parallel...")
    context_text_for_followups = "\n\n".join(context_str_parts)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        fut_ans = executor.submit(generate_answer, user_query, context_blocks, req.session_id)
        fut_foll = executor.submit(generate_followup_questions, user_query, context_text_for_followups)
        answer, g_usage = fut_ans.result()
        followups = fut_foll.result()
    logger.info("[Chat] Main LLM and follow-ups generation complete.")
    
    answer = clean_links(answer)

    # ── Step 6b: Faithfulness check ──
    logger.info("[Chat] Launching faithfulness check...")
    context_for_check = "\n\n".join(context_str_parts)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        fut_faith = executor.submit(faithfulness_checker.check, answer, context_for_check, max_logit)
        should_replace, faith_invoked, faith_passed = fut_faith.result()
    logger.info("[Chat] Parallel checks complete.")

    if (should_replace and not top) or not context_blocks:
        answer = faithfulness_checker.fallback_message
        citations_list = []
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

    redacted_ans = re.sub(r'<!--ent_\d+-->', '', answer)  # Strip leaked entity tags
    redacted_ans = redact_personal_phone_numbers(redacted_ans)
    msg_id = save_message(req.session_id, "assistant", redacted_ans, trace, prompt_tokens=total_p, completion_tokens=total_c, citations=citations_list)

    # ── Step 8: Cache result ──────────────────────────────────────────────────
    try:
        conn = db_connect(); conn.autocommit = True; cur = conn.cursor()
        cur.execute("""
            INSERT INTO query_cache (query_hash, query_text, response_text, citations)
            VALUES (%s,%s,%s,%s) ON CONFLICT (query_hash) DO NOTHING
        """, (q_hash, corrected_query, redacted_ans, json.dumps(citations_list)))
        cur.close(); conn.close()
    except Exception as e:
        logger.warning(f"[Cache] Save failed: {e}")

    return ChatResponse(
        answer=redacted_ans,
        citations=[Citation(**c) for c in citations_list],
        modelUsed="multi-agent-fastest",
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
