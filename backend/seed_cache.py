import os
import json
import hashlib
import psycopg2
from dotenv import load_dotenv

load_dotenv()
db_url = os.environ.get('DATABASE_URL')
if not db_url:
    print("No DATABASE_URL found!")
    exit(1)

# Predefined answers for the 12 suggestion cards
PREDEFINED_CACHE = [
    {
        "query": "What is the admission procedure, eligibility, TNEA cutoff, and fee structure for B.E / B.Tech at MSAJCE?",
        "answer": """**Admission Guide for B.E / B.Tech at MSAJCE**

**1. Eligibility Criteria (HSC / +2 Academic or Vocational)**
*   **General Category (OC):** Minimum 45% average in Mathematics, Physics, and Chemistry.
*   **BC / BCM / MBC / DNC / SC / ST / SCA:** Minimum 40% average in Mathematics, Physics, and Chemistry.

**2. Admission Procedure**
*   **Government Quota (TNEA):** Admissions are handled through Tamil Nadu Engineering Admissions (TNEA) single-window counseling based on your +2 marks. Our Counseling Code is **1108**.
*   **Management Quota:** Admissions are based on merit. You must have passed the HSC examination. Candidates can approach the college directly or book their seats online at [msajce-edu.in](https://www.msajce-edu.in).

**3. Fee Structure (Per Year)**
| Quota | Category | Tuition Fee (Rs.) |
| :--- | :--- | :--- |
| **Government Quota** | Non-Accredited | 50,000 |
| | Accredited | 55,000 |
| **Management Quota** | Non-Accredited | 85,000 |
| | Accredited | 87,000 |
""",
        "citations": [{"source": "Admission Page", "page": "1", "section": "Admissions"}]
    },
    {
        "query": "What is the fee structure for B.E / B.Tech courses at MSAJCE?",
        "answer": """**Tuition Fee Structure for B.E / B.Tech (Per Year)**

The fee varies slightly depending on whether the specific course is NBA accredited and which quota you are admitted through.

| Admission Quota | Course Accreditation | Tuition Fee (Rs. / Year) |
| :--- | :--- | :--- |
| **Government Quota (TNEA)** | Non-Accredited | 50,000 |
| **Government Quota (TNEA)** | Accredited | 55,000 |
| **Management Quota** | Non-Accredited | 85,000 |
| **Management Quota** | Accredited | 87,000 |

*Note: This does not include hostel, transport, or exam fees.*
""",
        "citations": [{"source": "Fee Structure", "page": "1", "section": "Fees"}]
    },
    {
        "query": "List all UG and PG degree courses offered at Mohamed Sathak A.J. College of Engineering.",
        "answer": """**Degree Courses Offered at MSAJCE**

**Undergraduate (B.E / B.Tech)**
1.  Artificial Intelligence and Data Science (AI & DS)
2.  Artificial Intelligence and Machine Learning (AI & ML)
3.  Civil Engineering
4.  Computer Science and Business Systems (CSBS)
5.  Computer Science and Engineering (CSE)
6.  Computer Science and Engineering (Cyber Security)
7.  Electronics and Communication Engineering (ECE)
8.  Electrical and Electronics Engineering (EEE)
9.  Information Technology (IT)
10. Mechanical Engineering
11. B.E. Electronics and Communication (Advanced Communication Technology)
12. B.E. Electronics and Communication (VLSI Design)

**Postgraduate (M.E)**
1.  M.E. Computer Science and Engineering
2.  M.E. Structural Engineering
""",
        "citations": [{"source": "Academics", "page": "1", "section": "Courses"}]
    },
    {
        "query": "What are the placement statistics, highest package, and top recruiting companies at MSAJCE?",
        "answer": """**Campus Placements at MSAJCE**

Our Training and Placement Cell ensures high employability for students through rigorous training and industry partnerships.

*   **Placement Percentage:** 92% of students placed consistently over the last 3 years.
*   **Top Recruiters:** TCS, Infosys, Wipro, CTS (Cognizant), Hexaware, L&T, IBM, Sutherland, and more.
*   **Industry Collaborations:** MoUs signed with various tech companies to provide internships and in-plant training.

The cell conducts extensive soft-skills, aptitude, and technical training from the first year to make students corporate-ready.
""",
        "citations": [{"source": "Placement Record", "page": "1", "section": "Placements"}]
    },
    {
        "query": "What are the hostel facilities, room capacity, mess, and rules for the Boys Hostel at MSAJCE?",
        "answer": """**Boys Hostel Facilities at MSAJCE**

The Boys Hostel provides a comfortable and secure living environment on campus.

*   **Accommodation:** Well-ventilated and spacious rooms (shared occupancy).
*   **Mess Facilities:** Hygienic, wholesome, and nutritious vegetarian and non-vegetarian food is served.
*   **Amenities:**
    *   24/7 RO purified drinking water.
    *   Uninterrupted power supply with generator backup.
    *   Recreation hall with TV and indoor games.
    *   High-speed Wi-Fi connectivity.
*   **Security:** Round-the-clock security personnel and CCTV surveillance. 
*   **Medical Care:** A doctor is available on call for medical emergencies.
""",
        "citations": [{"source": "Hostel Facilities", "page": "1", "section": "Boys Hostel"}]
    },
    {
        "query": "What are the hostel facilities, room capacity, and details for the Girls Hostel at MSAJCE?",
        "answer": """**Girls Hostel Facilities at MSAJCE**

The Girls Hostel is located within the campus, designed specifically for safety, comfort, and academic focus.

*   **Accommodation:** Furnished, spacious, and well-ventilated sharing rooms.
*   **Safety & Security:** Highly secure environment with 24/7 female wardens, security guards, and CCTV surveillance.
*   **Mess Facilities:** Quality, hygienic vegetarian and non-vegetarian meals prepared in a modern kitchen.
*   **Amenities:**
    *   RO drinking water on all floors.
    *   Uninterrupted power supply.
    *   Wi-Fi access for academic purposes.
    *   Common room with TV and reading materials.
*   **Medical Care:** First-aid facilities and a doctor-on-call are always available.
""",
        "citations": [{"source": "Hostel Facilities", "page": "1", "section": "Girls Hostel"}]
    },
    {
        "query": "Give an overview of college bus routes, route numbers, boarding points, and timings at MSAJCE.",
        "answer": """**College Transport & Bus Routes**

MSAJCE operates a fleet of over **35 buses** to ensure safe and comfortable commuting for students and staff from various parts of Chennai and its suburbs.

*   **Coverage:** Buses cover almost all major routes across Chennai, Kancheepuram, Chengalpattu, and Tiruvallur districts.
*   **Timings:** Buses arrive at the campus by 8:30 AM and depart at 3:45 PM.
*   **Safety:** All buses are operated by experienced drivers and monitored by transport coordinators.
*   **Route Details:** Detailed route numbers and boarding points are updated every semester. Please contact the Transport Office at the campus for your specific boarding point and time.
""",
        "citations": [{"source": "Transport Policy", "page": "1", "section": "Transport"}]
    },
    {
        "query": "Tell me about the laboratory facilities, technology centres, and practical learning infrastructure at MSAJCE.",
        "answer": """**Laboratory & Technology Infrastructure**

MSAJCE focuses heavily on practical learning with state-of-the-art infrastructure.

**1. Department Laboratories**
Every engineering department is equipped with advanced laboratories matching industry standards (e.g., VLSI Labs, Thermal Engineering Labs, Concrete & Highway Engineering Labs).

**2. Technology Centres & Centres of Excellence**
*   **Apple iOS Lab:** For mobile app development.
*   **Red Hat Academy:** Open-source technology training.
*   **CISCO Networking Academy:** CCNA and network infrastructure training.
*   **Texas Instruments Innovation Centre:** Electronics and embedded systems.
*   **E-Yantra Robotics Lab:** Supported by IIT Bombay.

**3. Computing Infrastructure**
Over 1000+ high-end computers connected via optical fiber network with 100 Mbps dedicated leased line internet access.
""",
        "citations": [{"source": "Infrastructure", "page": "1", "section": "Labs & Tech Centres"}]
    },
    {
        "query": "What scholarships are available for students at MSAJCE?",
        "answer": """**Scholarships at MSAJCE**

The college and the management facilitate various scholarships to support deserving and meritorious students.

**1. Government Scholarships**
*   **First Generation Graduate Scholarship:** Tuition fee waiver for first-generation graduates admitted through TNEA.
*   **Post Matric Scholarship (SC/ST/SCA):** For SC/ST students with family income below Rs. 2.5 Lakhs.
*   **BC/MBC/DNC Scholarship:** State government scholarship for eligible students.
*   **7.5% Government School Quota:** Full fee waiver (tuition, hostel, transport) for students who studied in Govt schools from 6th to 12th standard.
*   **Moovalur Ramamirtham Ammaiyar Scheme (Pudhumai Penn):** Rs. 1000/month for female students who studied in Govt schools (6th-12th).

**2. Management Scholarships**
The Mohamed Sathak Trust provides merit scholarships and financial assistance to economically weaker students.
""",
        "citations": [{"source": "Scholarship Policy", "page": "1", "section": "Scholarships"}]
    },
    {
        "query": "Tell me about MSAJCE's affiliation, accreditation, NAAC grade, and history.",
        "answer": """**About Mohamed Sathak A.J. College of Engineering (MSAJCE)**

*   **Establishment:** Founded in 2001 by the Mohamed Sathak Trust.
*   **Location:** Inside the IT corridor at Siruseri IT Park, Chennai.
*   **Affiliation:** Affiliated to **Anna University**, Chennai.
*   **Approval:** Approved by the All India Council for Technical Education (**AICTE**), New Delhi.
*   **Accreditation:** 
    *   Accredited by **NAAC with an 'A' Grade**.
    *   Specific programs (like Mechanical, ECE) are accredited by **NBA**.
*   **Vision:** To provide quality technical education and create engineers with high ethical standards and professional competence.
""",
        "citations": [{"source": "About Us", "page": "1", "section": "Overview"}]
    },
    {
        "query": "What sports facilities, athletic infrastructure, and student clubs are active at MSAJCE?",
        "answer": """**Campus Life: Sports & Clubs at MSAJCE**

**1. Sports Infrastructure**
The college emphasizes physical fitness and sportsmanship. Facilities include:
*   Standard 400m Athletic Track
*   Cricket Ground & Football Field
*   Volleyball, Basketball, and Tennis Courts
*   Indoor games facility (Table Tennis, Carrom, Chess)
*   Fully equipped Gymnasium.

**2. Student Clubs & Societies**
Students actively participate in various co-curricular and extracurricular clubs:
*   **Technical:** Coding Club, Robotics Club (E-Yantra), Google Developer Student Club.
*   **Extracurricular:** Fine Arts Club, Photography Club, Eco Club.
*   **Social Service:** National Service Scheme (NSS), Youth Red Cross (YRC), Rotaract Club.
*   **Professional Chapters:** IEEE, ISTE, CSI, IEI, and SAE chapters are highly active.
""",
        "citations": [{"source": "Campus Life", "page": "1", "section": "Sports & Clubs"}]
    },
    {
        "query": "What are the official contact numbers, email addresses, and location details for visiting MSAJCE campus?",
        "answer": """**Contact Information & Location**

**Address:**
Mohamed Sathak A.J. College of Engineering,
34, Rajiv Gandhi Salai (OMR), 
Siruseri IT Park, Chennai - 603 103,
Tamil Nadu, India.

**Admission Enquiries:**
*   **Phone:** +91 99400 04500
*   **Landline:** 044 - 2747 0021 / 23 / 24 / 25

**General Administration:**
*   **Email:** msajce.office@gmail.com / admin@msajce-edu.in
*   **Website:** [www.msajce-edu.in](https://www.msajce-edu.in)
""",
        "citations": [{"source": "Contact Us", "page": "1", "section": "Contact"}]
    }
]

def main():
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()
    
    print(f"Seeding {len(PREDEFINED_CACHE)} predefined answers into query_cache...")
    
    for item in PREDEFINED_CACHE:
        q_text = item["query"]
        a_text = item["answer"]
        cits = item["citations"]
        
        # Hash must match the exact logic in api_server.py
        q_hash = hashlib.sha256(q_text.lower().encode()).hexdigest()
        
        # Upsert logic
        cur.execute('''
            INSERT INTO query_cache (query_hash, query_text, response_text, citations, hit_count)
            VALUES (%s, %s, %s, %s, 1000)
            ON CONFLICT (query_hash) DO UPDATE 
            SET response_text = EXCLUDED.response_text,
                citations = EXCLUDED.citations,
                hit_count = query_cache.hit_count + 1,
                last_accessed = CURRENT_TIMESTAMP;
        ''', (q_hash, q_text, a_text, json.dumps(cits)))
        
        print(f"Inserted: {q_text[:50]}...")
        
    cur.close()
    conn.close()
    print("Successfully seeded the cache!")

if __name__ == "__main__":
    main()
