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

*   **Placement Percentage:** Average placement rate of 90% for outgoing students.
*   **Top Recruiters:** TCS, Infosys, Wipro, CTS (Cognizant), Hexaware, L&T, IBM, Sutherland, and more.
*   **Industry Collaborations:** MoUs signed with various tech companies to provide internships and in-plant training.

The cell conducts extensive soft-skills, aptitude, and technical training from the first year to make students corporate-ready.
""",
        "citations": [{"source": "Placement Record", "page": "1", "section": "Placements"}]
    },
    {
        "query": "What are the hostel facilities, room capacity, mess, and rules for the Boys Hostel at MSAJCE?",
        "answer": """**Boys Hostel Facilities at MSAJCE**

The Boys Hostel is located inside the campus, providing a comfortable, secure, and serene living environment.

*   **Accommodation & Capacity:** 3 blocks accommodating up to 480 boy students. There are 233 Non-AC rooms and 6 AC rooms, with 2 persons accommodated per room.
*   **Room Amenities:** Well furnished with modern amenities including cot, mattress with pillows, bedspreads, individual cupboards, study table-chair with lamp, fan, water heater, and wall hangers.
*   **Facilities:**
    *   Hygienic canteen/dining within the premises serving vegetarian and non-vegetarian meals.
    *   Entertainment hall with LCD-TV, TV hall, and indoor game facilities.
    *   Reading room with newspapers and magazines.
    *   Land-line telephone and high-speed Wi-Fi internet access.
    *   Main Library and Computer Centre open till 7:00 PM for hostellers.
""",
        "citations": [{"source": "Hostel Facilities", "page": "1", "section": "Boys Hostel"}]
    },
    {
        "query": "What are the hostel facilities, room capacity, and details for the Girls Hostel at MSAJCE?",
        "answer": """**Girls Hostel Facilities at MSAJCE**

The MSAJCE Girls Hostel is situated at Sholinganallur, which is 5 KM away from the campus. It is located in a main posh area with high safety and security.

*   **Accommodation & Capacity:** 1 block containing 71 Non-AC rooms, accommodating 3 girl students per room, with a total capacity of 210 girl students.
*   **Room Amenities:** Well-furnished with cot, mattress with pillows, bedspreads, individual cupboards, study table-chair with lamp, and wall hangers. Each room has bath/toilet facilities, wash basin, and mirror.
*   **Facilities:**
    *   Quality, hygienic vegetarian and non-vegetarian meals served in a spacious mess hall with separate seating.
    *   Entertainment hall with LCD-TV, TV hall, and indoor game facilities.
    *   Reading room with newspapers and magazines.
    *   RO drinking water on all floors and uninterrupted power supply.
    *   Land-line telephone and high-speed Wi-Fi internet access.
    *   Library and computer facilities available till 9:00 PM for hostellers.
""",
        "citations": [{"source": "Hostel Facilities", "page": "1", "section": "Girls Hostel"}]
    },
    {
        "query": "Give an overview of college bus routes, route numbers, boarding points, and timings at MSAJCE.",
        "answer": """**College Transport & Bus Routes**

MSAJCE provides transportation for students and staff residing in and around Chennai. The Institute has a fleet of 22 buses, one Tata ACE, and one Ambulance.

*   **Coverage:** Buses cover various routes across Chennai, Chengalpattu, Kanchipuram, and Tiruvallur districts.
*   **Timings:** All buses arrive at the MSAJCE campus at 8:00 AM. Earliest departure starts at 5:25 AM (Route AR 7 from Chunambedu) and latest at 6:25 AM (Route AR 10 from Porur).
*   **Safety & Coordination:** Buses are operated by experienced drivers, and smooth operation is managed by a dedicated transport committee headed by the Transport Convener Dr. K. P. Santhosh Nathan.
*   **Other Uses:** The transport facilities are also utilized for social service activities, Sports, NCC/NSS activities, Placement and Training activities, industrial visits, and educational trips.
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

The college and the management facilitate various scholarships to support deserving and meritorious students:

**1. Government Scholarships**
*   **Pragati Scholarship Scheme for Girl Students (AICTE):** Rs. 50,000 per year (for up to 2 girl children per family with family income < 8 Lakhs).
*   **Saksham Scholarship Scheme for Specially Abled Students (AICTE):** Rs. 50,000 per year (for students with disability >= 40% and family income < 8 Lakhs).
*   **Merit-cum-Means Scholarship (Ministry of Minority Affairs):** Rs. 20,000 per year (+ Rs. 12,000 for hostellers / Rs. 6,000 for day scholars) for minority community students with >= 50% marks and income < 2.5 Lakhs.
*   **Central Sector Scheme (MHRD):** Rs. 10,000 per year for students with >= 80% marks and income < 8 Lakhs.
*   **Financial Assistance for Beedi, Mine, and Cine Workers (Ministry of Labour & Employment):** Rs. 15,000 per year for wards of workers with family income < Rs. 10,000/month.

**2. Management & Trust Scholarships**
*   **Mohamed Sathak Educational Trust Scholarship:** Merit scholarship provided throughout the course of study for students joining MSAJCE with a TNEA cutoff of 180/200 and above (requires approval before counseling).
*   **Financial Assistance:** Provided to students from underprivileged backgrounds based on income certificate validation.
*   **Special Consideration for Girls:** Up to 10% tuition fee waiver for female students.
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
