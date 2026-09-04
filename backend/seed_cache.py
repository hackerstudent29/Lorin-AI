import os
import re
import json
import hashlib
import psycopg2
from dotenv import load_dotenv

load_dotenv()
db_url = os.environ.get('DATABASE_URL')

def normalize_query_for_hash(query: str) -> str:
    """Normalize query: strip whitespace, ALL punctuation (!, ?, ., ,, ;, :, -, /), lowercase, collapse spaces."""
    if not query:
        return ""
    q = query.strip().lower()
    q = re.sub(r"[!?.,'\"();:\-/]+", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q

# Predefined answers for the 12 hero suggestion cards aligned with the frontend and enriched with verified dataset facts.
PREDEFINED_CACHE = [
    {
        "query": "What is the admission procedure and eligibility criteria for B.E / B.Tech at MSAJCE?",
        "aliases": [
            "What is the admission procedure, eligibility, and TNEA cutoff for B.E / B.Tech at MSAJCE?",
            "What is the admission procedure and eligibility for B.E / B.Tech at MSAJCE?",
            "What is the admission procedure for MSAJCE?",
            "admission procedure for be btech msajce",
            "eligibility criteria for be btech at msajce",
            "how to get admission in msajce"
        ],
        "answer": """**Admission & Eligibility Guide for B.E / B.Tech at MSAJCE**

Mohamed Sathak A.J. College of Engineering offers undergraduate B.E. and B.Tech programmes. The counseling code for TNEA is **1108**.

### 1. Admission Pathways
*   **Government Quota (TNEA):** Admissions are through the single-window online counseling system of Tamil Nadu Engineering Admissions (TNEA) conducted by DOTE Chennai based on HSC (+2) cutoffs.
*   **Management Quota:** Direct merit-based admissions. Candidates can apply directly at the college office or register online.
*   **Other States Quota:** Direct admissions based on +2 / Intermediate qualifying marks in Mathematics, Physics, and Chemistry.

### 2. Category-Wise Eligibility Criteria
Candidates must obtain the following minimum average marks in Mathematics, Physics, and Chemistry (MPC) combined in HSC (Academic or Vocational):

| Category | Minimum Average Marks (MPC) |
| :--- | :--- |
| **General Category (OC)** | **45%** |
| **Backward Class (BC) / BC Muslim (BCM)** | **40%** |
| **Most Backward Class (MBC) / DNC** | **40%** |
| **SC / SCA / ST Categories** | **40%** |

### 3. Lateral Entry (Direct 2nd Year B.E / B.Tech)
*   **Diploma / B.Sc. Candidates:** OC: 55%, BC/BCM: 50%, MBC/DNC: 45%, SC/ST: Pass.

### 4. Admission Contacts
For seat availability, counseling guidance, or application forms:
*   👤 **Head of Admission (Dr. K. P. Santhosh Nathan):** ped.santhosh@msajce-edu.in
*   👤 **Coordinator for Other States (Dr. Vamsi Naga Mohan A):** cse.vamsi@msajce-edu.in
*   📞 **Admission Helpline:** +91 99400 04500 / 044 - 2747 0021 (Office Helpdesk)
*   ✉️ **Email:** msajce.office@gmail.com
*   🌐 **Online Application:** [https://enrollonline.co.in/Registration/Apply/msajce](https://enrollonline.co.in/Registration/Apply/msajce)
""",
        "citations": [{"source": "msajce_admission.md", "page": "1", "section": "Under Graduate Programmes"}]
    },
    {
        "query": "Tell me about the Central Library facilities, books stack, and working hours at MSAJCE.",
        "aliases": [
            "Central Library facilities, books stack, and working hours at MSAJCE",
            "library facilities at msajce",
            "library working hours msajce",
            "central library books and timings msajce"
        ],
        "answer": """**Central Campus Library (Learning Centre) at MSAJCE**

The MSAJCE Central Library is a premier learning resource housed in a spacious area of **8,978 Square Feet** covering the Ground Floor and the First Floor.

### 1. Library Resources and Stack Collection Details

| Resource Type | Quantity / Details |
| :--- | :--- |
| **Total Book Volumes** | 29,853 volumes |
| **Unique Titles** | 5,628 titles |
| **Reference Volumes** | 1,885 reference books |
| **E-books Collection** | 3,790 e-books |
| **Print Journals & Magazines** | 35 specialized print journals, 20 magazines, 5 daily newspapers |
| **Digital Library Subscriptions** | DELNET (1,379 e-journals), J-Gate subscription, Gale Database (1,800 international journals) |
| **Library Management** | Fully computerized with Bar-coded Technology and Koha open-source software |

### 2. Library Working Hours

| Day | Working Hours |
| :--- | :--- |
| **Monday to Saturday** | 8:00 A.M. to 7:00 P.M. |
| **Sunday** | 10:00 A.M. to 4:00 P.M. |

*Note: The library and computer systems remain open until late hours for hostellers (till 7:00 PM for boys, 9:00 PM for girls).*
""",
        "citations": [{"source": "msajce_library.md", "page": "1", "section": "Overview"}]
    },
    {
        "query": "List all UG and PG degree courses offered at Mohamed Sathak A.J. College of Engineering.",
        "aliases": [
            "List all courses offered at MSAJCE",
            "What courses are available in MSAJCE?",
            "UG and PG degree courses at MSAJCE",
            "departments and programmes in msajce"
        ],
        "answer": """**Degree Programmes Offered at MSAJCE**

MSAJCE offers 12 Undergraduate (B.E. / B.Tech) courses and 2 Postgraduate (M.E.) courses. Sanctioned intake seats are divided equally (50-50) between Government Quota (TNEA) and Management Quota.

### 1. Undergraduate Programmes (4 Years)

| S.No | Course Name | Course Code / Type | Sanctioned Intake |
| :--- | :--- | :--- | :--- |
| 1 | **B.E. Computer Science and Engineering** | B.E. (Permanent Affiliation) | 60 Seats |
| 2 | **B.Tech. Information Technology** | B.Tech. | 60 Seats |
| 3 | **B.Tech. Artificial Intelligence and Data Science** | B.Tech. (AI & DS) | 60 Seats |
| 4 | **B.Tech. Artificial Intelligence and Machine Learning** | B.Tech. (AI & ML) | 60 Seats |
| 5 | **B.E. Computer Science and Engineering (Cyber Security)** | B.E. | 30 Seats |
| 6 | **B.Tech. Computer Science and Business Systems** | B.Tech. (CSBS) | 30 Seats |
| 7 | **B.E. Electronics and Communication Engineering** | B.E. (NBA Accredited) | 60 Seats |
| 8 | **B.E. Electrical and Electronics Engineering** | B.E. | 30 Seats |
| 9 | **B.E. Mechanical Engineering** | B.E. (Permanent Affiliation) | 30 Seats |
| 10 | **B.E. Civil Engineering** | B.E. | 30 Seats |
| 11 | **B.Tech. ECE (Advanced Communication Technology)** | B.Tech. (ACT) | 30 Seats |
| 12 | **B.Tech. Electronics Engineering (VLSI Design & Tech)** | B.Tech. (VLSI) | 30 Seats |
| 13 | **Bachelor of Architecture (B.Arch)** | B.Arch (5 Years) | 40 Seats |
| 14 | **Bachelor of Design (B.Des)** | B.Des (4 Years) | 30 Seats |

### 2. Postgraduate Programmes (2 Years)

| S.No | Course Name | Course Type | Sanctioned Intake |
| :--- | :--- | :--- | :--- |
| 1 | **M.E. Computer Science and Engineering** | M.E. | 9 Seats |
| 2 | **M.E. Structural Engineering** | M.E. (Civil Dept) | 18 Seats |
| 3 | **Master of Architecture (M.Arch)** | M.Arch | 15 Seats |
""",
        "citations": [{"source": "msajce_admission.md", "page": "1", "section": "Under Graduate Programmes"}]
    },
    {
        "query": "What are the placement statistics, highest package, and top recruiting companies at MSAJCE?",
        "aliases": [
            "placement statistics highest package and top companies msajce",
            "placements in msajce",
            "highest salary package msajce",
            "top recruiters at msajce"
        ],
        "answer": """**Campus Placements & Internships at MSAJCE**

The Training and Placement Cell at MSAJCE runs comprehensive training (aptitude, communication, coding bootcamps, and foreign language training) starting from the first year.

### 1. Key Statistics
*   **Average Placement Rate:** Over **90%+** of outgoing eligible students secure placements.
*   **Highest Package:** **₹12.0 LPA**
*   **Average Package:** **₹4.5 LPA**
*   **Internship Partners:** Key organizations where our students completed extensive internships:
    *   **Lenovo:** 75 students
    *   **Zoho Tech:** 51 students
    *   **Green Valleys Shelters:** 45 students
    *   **Thermodyn:** 39 students
    *   **Precision Instruments & Electronics:** 9 students

### 2. Top Recruiting Corporate Partners
MSAJCE graduates are regularly placed with leading technology and engineering firms:
*   *TCS, Infosys, Wipro, CTS (Cognizant), Hexaware, IBM, L&T, Sutherland, Disenosys, Openwave, Preethi Engineering.*

### 3. Training & Placement Cell Contacts
*   👤 **Mr. S.V. Vinodh (Placement Officer):** placement@msajce-edu.in
*   👤 **Mr. Ajin Sijo John (Assistant Placement Officer)**
*   📞 **Helpline:** +91 99400 04500
""",
        "citations": [{"source": "msajce_placement.md", "page": "1", "section": "Overview"}]
    },
    {
        "query": "What are the hostel facilities, room capacity, mess, and rules for the Boys Hostel at MSAJCE?",
        "aliases": [
            "boys hostel facilities room capacity mess and rules msajce",
            "boys hostel in msajce",
            "hostel details for boys msajce",
            "boys hostel rooms and fee msajce"
        ],
        "answer": """**Boys Hostel Facilities at MSAJCE**

The Boys Hostel is located directly inside the campus, providing a safe and convenient residential experience.

### 1. Hostel Accommodation Details

| Facility | Details |
| :--- | :--- |
| **Total Blocks** | 3 Residential Blocks |
| **Total Capacity** | 480 Students |
| **Non-AC Rooms** | 233 Rooms (2 occupants per room) |
| **AC Rooms** | 6 Rooms (2 occupants per room) |
| **In-Room Amenities** | Furnished with cots, mattresses, study tables & chairs, reading lamps, individual cupboards, fans, and water heaters |

### 2. General Facilities & Amenities
*   **Hygienic Mess & Canteen:** Located inside the hostel premises, serving high-quality vegetarian and non-vegetarian meals.
*   **Recreation Room:** Equipped with LCD-TV, indoor games (table tennis, chess, carrom), and a reading room.
*   **Connectivity:** High-speed Wi-Fi internet access throughout all hostel blocks.
*   **Study Access:** Hostellers can utilize the Main Campus Library and Computer Centre, which remain open until 7:00 PM.
*   **Rules:** Check-in curfew at 7:00 PM; resident warden supervision; biometric register.
""",
        "citations": [{"source": "msajce_hostel.md", "page": "1", "section": "Boys Hostel"}]
    },
    {
        "query": "What are the hostel facilities, room capacity, and details for the Girls Hostel at MSAJCE?",
        "aliases": [
            "girls hostel facilities room capacity and details msajce",
            "girls hostel in msajce",
            "ladies hostel facilities msajce",
            "safety in girls hostel msajce"
        ],
        "answer": """**Girls Hostel Facilities at MSAJCE**

The MSAJCE Girls Hostel is situated in Sholinganallur (5 KM from the college), placed in a posh area with high security. The college provides dedicated transport to commute between the hostel and the campus.

### 1. Accommodation Details

| Facility | Details |
| :--- | :--- |
| **Total Blocks** | 1 Secure Block |
| **Total Capacity** | 210 Students |
| **Rooms** | 71 Non-AC Rooms (3 occupants per room) |
| **In-Room Amenities** | Cots, mattresses, study tables with lamps, individual cupboards, attached bath/toilet, washbasins, and vanity mirrors |

### 2. Safety, Security & Amenities
*   **Mess Facility:** Hygienic vegetarian and non-vegetarian meals served in a spacious dining hall.
*   **Safety & Surveillance:** 24/7 lady security guards, CCTV surveillance, and resident warden.
*   **Water & Power:** RO purified drinking water on all floors and uninterrupted power backup.
*   **Extended Study Hours:** High-speed Wi-Fi; campus library and computing facilities remain open until **9:00 PM** for girls hostel students.
*   **Rules:** Strict curfew at 6:30 PM; gatepass authorization from parents and warden required.
""",
        "citations": [{"source": "msajce_hostel.md", "page": "1", "section": "Girls Hostel"}]
    },
    {
        "query": "Give an overview of college bus routes, route numbers, boarding points, and timings at MSAJCE.",
        "aliases": [
            "overview of college bus routes route numbers and timings msajce",
            "bus routes in msajce",
            "college transport routes and timings msajce",
            "bus stops and timings msajce"
        ],
        "answer": """**College Transport & Bus Routes**

MSAJCE operates a fleet of **22 college buses**, one Tata ACE, and one 24/7 Ambulance. Transport covers Chennai, Chengalpattu, Kanchipuram, and Tiruvallur districts. All buses arrive at the campus by 8:00 AM.

### 1. Key College Bus Routes

| Route Number | Source / Start Location | Departure Time | Key Stops En Route |
| :--- | :--- | :--- | :--- |
| **Route AR 3** | Uthiramerur | 6:00 AM | Paranur Tollgate, Guduvanchery, Vandalur Zoo, Kandigai, Kelambakkam, SIPCOT |
| **Route AR 4** | Moolakadai | 6:10 AM | Perambur, Dowton, Central, Marina Beach, Adyar, Sholinganallur |
| **Route N/3** | MMDA School | 6:15 AM | Anna Nagar, Skywalk, Loyola College, T. Nagar, Saidapet, Velachery, OMR |
| **Route AR 6** | MMDA School / ICF | 6:10 AM | Egmore, Triplicane, Madhyakailash, SRP Tools, Perungudi, Karapakkam |
| **Route AR 7** | Chunambedu | 5:25 AM | Kalpakkam, Thirukazhukundram, Paiyanur, Thirupporur, Kelambakkam |
| **Route AR 8** | Manjambakkam | 5:50 AM | Retteri, Padi, Ashok Pillar, Adambakkam, Pallikaranai, Medavakkam |
| **Route AR 9** | Ennore | 6:15 AM | Broadway, Central, Mylapore, Mandaveli, Adyar, Thiruvanmiyur |
| **Route AR 10** | Porur | 6:25 AM | Kundrathur, Pallavaram, Chrompet, Tambaram, Camp Road, Medavakkam |
| **Route R 22** | Nemilichery | 5:50 AM | Poonamallee, Ramachandra Hospital, Porur, Kathipara, Velachery |

### 2. Transport Office Contacts
*   👤 **Transport Convener:** Dr. K. P. Santhosh Nathan (ped.santhosh@msajce-edu.in)
*   👤 **Assistant Transport Convener:** Mr. A. Abdul Gafoor
*   📞 **General Helpline:** +91 99400 04500 / 044 - 2747 0021
""",
        "citations": [{"source": "msajce_transport.md", "page": "1", "section": "College Bus Facility"}]
    },
    {
        "query": "Tell me about the laboratory facilities, technology centres, and practical learning infrastructure at MSAJCE.",
        "aliases": [
            "laboratory facilities technology centres and practical learning msajce",
            "labs and technology centres msajce",
            "practical labs infrastructure msajce",
            "centre of excellence at msajce"
        ],
        "answer": """**Practical Learning Labs & Technology Centres**

MSAJCE features state-of-the-art laboratory infrastructure and specialized Centres of Excellence (CoE) to build industry-ready skills.

### 1. Specialized Technology Centres (CoEs)

| Centre Name | Focus Area / Training Partners |
| :--- | :--- |
| **Apple iOS Lab** | Mobile Application Development with Swift & iOS SDK |
| **Red Hat Academy** | Linux Enterprise Administration & Open Source Technologies |
| **CISCO Networking Academy** | Network Routing, Switching (CCNA) & Cyber Security |
| **Texas Instruments Lab** | Embedded Systems, Microcontrollers & Internet of Things (IoT) |
| **E-Yantra Robotics Lab** | Robotics Design and Automation (supported by IIT Bombay) |

### 2. Infrastructure & Computing
*   **Computing Facilities:** Over **1,000+ high-end computers** deployed across dedicated department labs.
*   **Network:** Connected via high-speed optical fiber backbone with **100 Mbps dedicated leased-line internet** and Wi-Fi access.
*   **Core Labs:** Advanced engineering laboratories (CAD/CAM Labs, VLSI design systems, Soil mechanics, Structural engineering, CNC Machining, and Thermal labs).
""",
        "citations": [{"source": "msajce_placement.md", "page": "1", "section": "Facilities"}]
    },
    {
        "query": "What scholarships are available for students at MSAJCE?",
        "aliases": [
            "scholarships available for students at msajce",
            "scholarships in msajce",
            "government scholarship schemes msajce",
            "pragati and saksham scholarship msajce"
        ],
        "answer": """**Scholarships & Financial Aid at MSAJCE**

Deserving and meritorious students joining MSAJCE can apply for government schemes or trust-based scholarships.

### 1. Government Scholarship Schemes

| Scholarship Name | Eligibility Criteria | Financial Assistance / Amount |
| :--- | :--- | :--- |
| **Pragati Scholarship (AICTE)** | Girl students (up to 2 per family), Income < 8 Lakhs | **Rs. 50,000 / Year** |
| **Saksham Scholarship (AICTE)** | Specially abled students (disability >= 40%), Income < 8 Lakhs | **Rs. 50,000 / Year** |
| **Merit-cum-Means (MOMA)** | Minority community students with >= 50% marks in +2, Income < 2.5 Lakhs | **Rs. 20,000 / Year** (+ Hosteller/Day Scholar allowances) |
| **Central Sector Scheme (MHRD)** | Students scoring >= 80th percentile in board exams, Income < 8 Lakhs | **Rs. 10,000 / Year** |
| **Labour Welfare Scheme** | Wards of Beedi, Mine, and Cine Workers, family income < 10,000/month | **Rs. 15,000 / Year** |

### 2. Mohamed Sathak Trust & Merit Aid
*   **Management Scholarships:** Students joining MSAJCE via TNEA with cutoffs of **180/200 and above** are eligible for educational merit scholarships covering tuition fees.
*   **Special Consideration for Girls:** A dedicated **10% tuition fee waiver** is provided for girl students by the Trust.
*   **Need-Based Financial Assistance:** Concessions for economically weaker sections upon validation.
""",
        "citations": [{"source": "msajce_admission.md", "page": "1", "section": "Under Graduate Programmes"}]
    },
    {
        "query": "Tell me about MSAJCE's affiliation, accreditation, NAAC grade, and history.",
        "aliases": [
            "about msajce affiliation accreditation naac grade and history",
            "about msajce",
            "naac grade of msajce",
            "is msajce affiliated to anna university",
            "history of msajce"
        ],
        "answer": """**About Mohamed Sathak A.J. College of Engineering (MSAJCE)**

MSAJCE was established in **2001** by the Mohamed Sathak Trust (founded in 1973), a pioneer in technical and medical educational institutions.

### 1. Affiliations & Approvals
*   **Anna University:** Affiliated to Anna University, Chennai.
*   **AICTE:** Approved by the All India Council for Technical Education, New Delhi.
*   **TNEA Counseling Code:** **1108**

### 2. Quality Accreditations

| Metric / Body | Accreditation Status |
| :--- | :--- |
| **NAAC Rating** | Accredited with an **'A' Grade** |
| **NBA Accreditation** | Accredited departments (Mechanical Engineering, Electronics & Communication) |
| **NIRF Participation** | Participates annually in the National Institutional Ranking Framework |

### 3. Campus Location
*   **Address:** 34, Rajiv Gandhi Salai (OMR), Inside SIPCOT IT Park, Siruseri, Egattur, Chennai, Tamil Nadu 603103.
*   **Coordinates:** 12.8358° N, 80.2186° E
*   📍 **Google Maps Location:** [Mohamed Sathak A.J. College of Engineering on Google Maps](https://maps.app.goo.gl/nrTgXSwx1h76SjdSA)
""",
        "citations": [{"source": "msajce_about.md", "page": "1", "section": "Overview"}]
    },
    {
        "query": "What sports facilities, athletic infrastructure, and student clubs are active at MSAJCE?",
        "aliases": [
            "sports facilities athletic infrastructure and student clubs at msajce",
            "campus life in msajce",
            "sports and games in msajce",
            "student clubs and societies msajce"
        ],
        "answer": """**Campus Life: Sports, Athletics & Student Clubs at MSAJCE**

MSAJCE encourages active participation in athletic tournaments, technology groups, and volunteer activities.

### 1. Sports & Athletics Infrastructure
*   **Outdoor Courts:** Volley ball court, Basket ball court, and Tennis court.
*   **Grounds:** Cricket ground, Football field, and a standard **400m Athletic Track**.
*   **Gymnasium:** A fully equipped, modern fitness gym is available inside the campus.
*   **Indoor Sports:** Table tennis room, carrom boards, chess tables.

### 2. Extracurricular Student Clubs & Societies

| Category | Active Clubs & Student Chapters |
| :--- | :--- |
| **Technical & Robotics** | Coding Club, e-Yantra Robotics (supported by IIT Bombay), Google Developer Student Club (GDSC) |
| **Professional Chapters** | IEEE Student Branch, CSI (Computer Society), ISTE, IEI, and SAE chapters |
| **Social Service Cells** | National Service Scheme (NSS), Youth Red Cross (YRC), Rotaract Club |
| **Creative Clubs** | Fine Arts Club, Eco Club, Photography Club |
| **Flagship Fest** | **SATHAKOTSAV** — the annual intra- and inter-collegiate cultural festival |
""",
        "citations": [{"source": "msajce_sports.md", "page": "1", "section": "Overview"}]
    },
    {
        "query": "What are the official contact numbers, email addresses, and location details for visiting MSAJCE campus?",
        "aliases": [
            "official contact numbers email addresses and location details msajce",
            "contact info for msajce",
            "how to contact msajce",
            "msajce phone number and email address",
            "location of msajce"
        ],
        "answer": """**Contact Information & Location**

### 1. Campus Address
**Mohamed Sathak A.J. College of Engineering**
34, Rajiv Gandhi Salai (OMR), Inside SIPCOT IT Park, Siruseri, Egattur, Chennai, Tamil Nadu 603103, India.

*   **Coordinates:** 12.8358° N, 80.2186° E
*   **Plus Code:** R6P9+8C Egattur, Tamil Nadu
*   📍 **Google Maps Location:** [Mohamed Sathak A.J. College of Engineering on Google Maps](https://maps.app.goo.gl/nrTgXSwx1h76SjdSA)

### 2. Key Office Contacts

| Department / Query | Phone Number / Contact | Email / Website |
| :--- | :--- | :--- |
| **Admission Helpline** | +91 99400 04500 | msajce.office@gmail.com |
| **Head of Admission** | Dr. K. P. Santhosh Nathan | ped.santhosh@msajce-edu.in |
| **Administrative Landline** | 044 - 2747 0021 / 23 / 24 / 25 | admin@msajce-edu.in / msajce.office@gmail.com |
| **Principal's Office** | Dr. K.S. Srinivasan | principal@msajce-edu.in |
| **Placement Cell** | Mr. S.V. Vinodh | placement@msajce-edu.in |
| **Official Website** | — | [www.msajce-edu.in](https://www.msajce-edu.in) |
""",
        "citations": [{"source": "msajce_about.md", "page": "1", "section": "Overview"}]
    },
    {
        "query": "who is ram",
        "aliases": [
            "who is the developer",
            "who is the creator",
            "who developed you",
            "who created you",
            "who built you",
            "tell me about ram",
            "tell me about the developer",
            "about the developer",
            "developer of lorin ai",
            "creator of lorin ai",
            "ram",
            "ramanathan",
            "ramanathan s",
            "who is ramanathan",
            "who made you",
            "tell me about ramanathan",
            "ur host",
            "your host",
            "know more about ram",
            "know more about the developer"
        ],
        "answer": """### 👨‍💻 Developer Profile — Ramanathan S.
**Creator & Architect of Lorin AI | Software Engineer**

Ramanathan S. is the creator, architect, and lead developer of the **Lorin AI** Campus Assistant for Mohamed Sathak A.J. College of Engineering (MSAJCE).

---

### 🎓 Academic Background
* **Degree:** Bachelor of Technology (B.Tech) in Information Technology
* **Institution:** Mohamed Sathak A.J. College of Engineering (MSAJCE), Chennai
* **Batch:** 2024 – 2028 | **CGPA:** 7.75

---

### 💼 Professional Experience & Internships
* **CodeAlpha** — *Backend Development Intern* (Remote | July 2026 – August 2026)
  * Designed production-grade REST APIs, structured relational data models, and implemented robust server-side validation and error handling for distributed services.
* **Apollo Computer Education Ltd** — *Java Full-Stack Intern* (Chennai, India | January 2026)
  * Engineered end-to-end full-stack web modules using Spring Boot, Spring Data JPA, and PostgreSQL, converting technical specifications into deployable microservices.

---

### 🛠️ Technical Stack & Core Expertise
| Domain | Technologies & Frameworks |
| :--- | :--- |
| **Backend & APIs** | Java, Spring Boot, Spring Data JPA, Hibernate, RESTful APIs, Microservices |
| **AI & RAG Systems** | Qdrant Vector DB, NVIDIA NIM, Hybrid Search (Dense + BM25), Self-Healing LLM Pipelines, Llama 3.1 |
| **Databases** | PostgreSQL, Supabase Cloud, Relational Schema Design |
| **Frontend & 3D** | React, TypeScript, Tailwind CSS, Motion, WebSockets, Three.js / React Three Fiber, WebGL |
| **DevOps & Cloud** | Docker, Git, Vercel, Railway, AWS, Vite |

---

### 🚀 Shipped Software & Featured Projects
* **🤖 Lorin AI**: Enterprise RAG Assistant for MSAJCE with sub-second semantic caching, Qdrant hybrid retrieval, and automated feedback self-correction.
* **🎵 Listen Zenify**: Full-stack music streaming platform with audio streaming, custom playlists, user library synchronization, and real-time playback (Java Spring Boot, PostgreSQL, React).
* **🏟️ ZenDrum Booking**: Real-time sports turf & venue reservation platform with instant slot locking via WebSockets, dynamic pricing, and automated receipts (Java Spring Boot, WebSockets, PostgreSQL, React).
* **🏢 Zen Hostel**: Digital hostel operations platform streamlining room allocations, warden dashboards, student gatepass processing, and maintenance ticketing (Java, Spring Boot, PostgreSQL, React).

---

### 🎯 Career Availability
* Actively seeking remote software engineering internships and full-time backend development positions available starting in **Q1 2026**.

---

### 🌐 Connect & Developer Links
* 🔗 **Personal 3D Portfolio:** [https://ram3d-portfolio.vercel.app](https://ram3d-portfolio.vercel.app)
* 💻 **GitHub Profile:** [https://github.com/hackerstudent29](https://github.com/hackerstudent29)
* 📦 **Lorin AI GitHub Repository:** [https://github.com/hackerstudent29/Lorin-AI](https://github.com/hackerstudent29/Lorin-AI)
* 🏫 **College Official Website:** [https://www.msajce-edu.in](https://www.msajce-edu.in)
""",
        "citations": [{"source": "msajce_developer_ramanathan.md", "page": "1", "section": "Developer Profile"}]
    }
]

def main():
    if not db_url:
        print("No DATABASE_URL provided. Skipping DB seeding.")
        return
    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cur = conn.cursor()
        print(f"Seeding {len(PREDEFINED_CACHE)} predefined answers and aliases into query_cache...")
        
        count = 0
        for item in PREDEFINED_CACHE:
            q_text = item["query"]
            a_text = item["answer"]
            cits = item["citations"]
            
            queries_to_seed = [q_text] + item.get("aliases", [])
            for q in queries_to_seed:
                q_hash = hashlib.sha256(normalize_query_for_hash(q).encode()).hexdigest()
                cur.execute('''
                    INSERT INTO query_cache (query_hash, query_text, response_text, citations, hit_count)
                    VALUES (%s, %s, %s, %s, 1000)
                    ON CONFLICT (query_hash) DO UPDATE 
                    SET response_text = EXCLUDED.response_text,
                        citations = EXCLUDED.citations,
                        hit_count = query_cache.hit_count + 1,
                        last_accessed = CURRENT_TIMESTAMP;
                ''', (q_hash, q, a_text, json.dumps(cits)))
                count += 1
                
        cur.close()
        conn.close()
        print(f"Successfully seeded {count} query variants into cache!")
    except Exception as e:
        print(f"DB seed error: {e}")

if __name__ == "__main__":
    main()
