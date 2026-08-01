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

# Predefined answers for the 12 suggestion cards aligned with the frontend and enriched with details
# STRICT RULE: No personal phone numbers are included. Wards must use emails or general office helpdesks.
PREDEFINED_CACHE = [
    {
        "query": "What is the admission procedure, eligibility, and TNEA cutoff for B.E / B.Tech at MSAJCE?",
        "answer": """**Admission & Eligibility Guide for B.E / B.Tech at MSAJCE**

Mohamed Sathak A.J. College of Engineering offers undergraduate B.E. and B.Tech programmes. The counseling code for TNEA is **1108**.

### 1. Admission Pathways
*   **Government Quota (TNEA):** Admissions are through the single-window online counseling system of Tamil Nadu Engineering Admissions (TNEA) based on HSC (+2) cutoffs.
*   **Management Quota:** Direct merit-based admissions. Candidates can apply directly at the college office or register online.

### 2. Category-Wise Eligibility Criteria
Wards must obtain the following minimum average marks in Mathematics, Physics, and Chemistry (MPC) combined in HSC (Academic or Vocational):

| Category | Minimum Average Mark |
| :--- | :--- |
| **General Category (OC)** | 45% |
| **Backward Class (BC) / BC Muslim (BCM)** | 40% |
| **MBC / DNC Categories** | 40% |
| **SC / SCA / ST Categories** | 40% |

### 3. Admission Contacts
For seat availability, counseling guidance, or application form queries, you can reach:
*   👤 **Head of Admission (Dr. K. P. Santhosh Nathan):** ped.santhosh@msajce-edu.in
*   📞 **Admission Helpline:** +91 99400 04500 / 044 - 2747 0021 (Office Helpdesk)
*   ✉️ **Email:** msajce.office@gmail.com (General Office)
""",
        "citations": [{"source": "msajce_admission.md", "page": "1", "section": "Under Graduate Programmes"}]
    },
    {
        "query": "Tell me about the Central Library facilities, books stack, and working hours at MSAJCE.",
        "answer": """**Central Campus Library (Learning Centre) at MSAJCE**

The MSAJCE Central Library is a support service housed in a spacious area of **8,978 Square Feet** covering the Ground Floor and the First Floor.

### 1. Library Resources and Stack Collection Details

| Resource Type | Quantity / Details |
| :--- | :--- |
| **Total Book Volumes** | 29,853 volumes |
| **Unique Titles** | 5,628 titles |
| **Reference Volumes** | 1,885 reference books |
| **E-books Collection** | 3,790 e-books |
| **Print Journals & Magazines** | 35 specialized print journals, 20 magazines, 5 daily newspapers |
| **Digital Library access** | DELNET membership (1,379 e-journals), J-Gate subscription, Gale Database (1,800 international journals) |
| **Library Management** | Fully computerized with Bar-coded Technology and Koha open-source software |

### 2. Library Working Hours
The library is open throughout the week, including Sundays:

| Day | Working Hours |
| :--- | :--- |
| **Monday to Saturday** | 8:00 A.M. to 7:00 P.M. |
| **Sunday** | 10:00 A.M. to 4:00 P.M. |

*Note: The library and computer systems are fully open up to late hours for all hostellers (till 7:00 PM for boys, 9:00 PM for girls).*
""",
        "citations": [{"source": "msajce_library.md", "page": "1", "section": "Overview"}]
    },
    {
        "query": "List all UG and PG degree courses offered at Mohamed Sathak A.J. College of Engineering.",
        "answer": """**Degree Programmes Offered at MSAJCE**

MSAJCE offers 12 Undergraduate (B.E. / B.Tech) courses and 2 Postgraduate (M.E.) courses. The intake seats are divided equally (50-50) between the Government Quota and Management Quota.

### 1. Undergraduate Programmes (4 Years)

| S.No | Course Name | Course Code / Type | Sanctioned Intake |
| :--- | :--- | :--- | :--- |
| 1 | B.E. Computer Science and Engineering | B.E. (Permanent Affiliation) | 60 Seats |
| 2 | B.Tech. Information Technology | B.Tech. | 60 Seats |
| 3 | B.Tech. Artificial Intelligence and Data Science | B.Tech. (AI & DS) | 60 Seats |
| 4 | B.Tech. Artificial Intelligence and Machine Learning | B.Tech. (AI & ML) | 60 Seats |
| 5 | B.E. Computer Science and Engineering (Cyber Security) | B.E. | 30 Seats |
| 6 | B.Tech. Computer Science and Business Systems | B.Tech. (CSBS) | 30 Seats |
| 7 | B.E. Electronics and Communication Engineering | B.E. (NBA Accredited) | 60 Seats |
| 8 | B.E. Electrical and Electronics Engineering | B.E. | 30 Seats |
| 9 | B.E. Mechanical Engineering | B.E. (NBA Accredited) | 30 Seats |
| 10 | B.E. Civil Engineering | B.E. | 30 Seats |
| 11 | B.E. Electronics and Communication (Advanced Communication Tech) | B.E. (ACT) | 60 Seats |
| 12 | B.E. Electronics and Communication (VLSI Design) | B.E. (VLSI) | 60 Seats |

### 2. Postgraduate Programmes (2 Years)

| S.No | Course Name | Course Type | Sanctioned Intake |
| :--- | :--- | :--- | :--- |
| 1 | M.E. Computer Science and Engineering | M.E. | 18 Seats |
| 2 | M.E. Structural Engineering | M.E. (Civil Dept) | 18 Seats |
""",
        "citations": [{"source": "msajce_admission.md", "page": "1", "section": "Under Graduate Programmes"}]
    },
    {
        "query": "What are the placement statistics, highest package, and top recruiting companies at MSAJCE?",
        "answer": """**Campus Placements & Internships at MSAJCE**

The Training and Placement Cell at MSAJCE runs comprehensive training (aptitude, communication, coding) starting from the first year.

### 1. Key Statistics
*   **Average Placement Rate:** Over **90%** of outgoing eligible students secure placements.
*   **Internship Partners:** Key organizations where our students completed extensive internships:
    *   **Lenovo:** 75 students (2022-2023)
    *   **Zoho Tech:** 51 students (2022-2023)
    *   **Green Valleys Shelters:** 45 students (2022-2023)
    *   **Thermodyn:** 39 students (2022-2023)
    *   **Precision Instruments & Electronics:** 9 students

### 2. Top Recruiting Corporate Partners
MSAJCE graduates are regularly placed with leading technology and corporate firms:
*   *TCS, Infosys, Wipro, CTS (Cognizant), Hexaware, IBM, L&T, Sutherland, Disenosys, Openwave, Preethi Engineering.*

### 3. Training & Placement Cell Contacts
For placement drives, companies recruiting, or student queries:
*   👤 **Mr. S.V. Vinodh (Placement Officer):** placement@msajce-edu.in
*   👤 **Mr. Ajin Sijo John (Assistant Placement Officer)**
*   📞 **General Office Helpline:** +91 99400 04500 (For phone routing)
""",
        "citations": [{"source": "msajce_placement.md", "page": "1", "section": "Overview"}]
    },
    {
        "query": "What are the hostel facilities, room capacity, mess, and rules for the Boys Hostel at MSAJCE?",
        "answer": """**Boys Hostel Facilities at MSAJCE**

The Boys Hostel is located directly inside the campus, providing a safe and convenient residential experience.

### 1. Hostel Accommodation details

| Facility | Details |
| :--- | :--- |
| **Total Blocks** | 3 Residential Blocks |
| **Total Capacity** | 480 Students |
| **Non-AC Rooms** | 233 Rooms (2 occupants per room) |
| **AC Rooms** | 6 Rooms (2 occupants per room) |
| **In-Room Amenities** | Furnished with cots, mattresses, pillows, bedspreads, study tables & chairs, lamps, individual cupboards, fan, and water heaters |

### 2. General Facilities & Amenities
*   **Hygienic Mess & Canteen:** Located inside the hostel premises, serving high-quality vegetarian and non-vegetarian meals.
*   **Recreation Room:** Equipped with an LCD-TV, indoor game setups (table tennis, chess, carrom), and a reading room stocked with newspapers and journals.
*   **Connectivity:** High-speed Wi-Fi internet access throughout the hostel blocks.
*   **Study Access:** Hostellers can utilize the Main Campus Library and the Computer Centre, which remain open until 7:00 PM.
""",
        "citations": [{"source": "msajce_hostel.md", "page": "1", "section": "Boys Hostel"}]
    },
    {
        "query": "What are the hostel facilities, room capacity, and details for the Girls Hostel at MSAJCE?",
        "answer": """**Girls Hostel Facilities at MSAJCE**

The MSAJCE Girls Hostel is situated off-campus at Sholinganallur (5 KM from the college), placed in a posh area with high security. The college provides dedicated transport to commute between the hostel and the campus.

### 1. Accommodation details

| Facility | Details |
| :--- | :--- |
| **Total Blocks** | 1 Secure Block |
| **Total Capacity** | 210 Students |
| **Rooms** | 71 Non-AC Rooms (3 occupants per room) |
| **In-Room Amenities** | Cots, mattresses, pillows, bedspreads, study tables with lamps, individual cupboards, attached bath/toilet, washbasins, and vanity mirrors |

### 2. General Facilities & Amenities
*   **Mess Facility:** Hygienic vegetarian and non-vegetarian meals served in a spacious mess hall with separate seating.
*   **Recreation Room:** TV hall with LCD-TV, magazines, newspapers, and indoor gaming facility.
*   **Water & Power:** RO purified drinking water on all floors, uninterrupted power supply, and 24/7 security.
*   **Study Access:** High-speed Wi-Fi. The college library and computer facilities are accessible until 9:00 PM for girls hostel students.
""",
        "citations": [{"source": "msajce_hostel.md", "page": "1", "section": "Girls Hostel"}]
    },
    {
        "query": "Give an overview of college bus routes, route numbers, boarding points, and timings at MSAJCE.",
        "answer": """**College Transport & Bus Routes**

MSAJCE operates a fleet of **22 college buses**, one Tata ACE, and one Ambulance. Transport covers Chennai, Chengalpattu, Kanchipuram, and Tiruvallur districts. All buses arrive at the campus by 8:00 AM.

### 1. Sample College Bus Routes

| Route Number | Source / Start Location | Departure Time | Key Stops En Route |
| :--- | :--- | :--- | :--- |
| **Route AR 3** | Uthiramerur | 6:00 AM | Paranur Tollgate, Guduvanchery, Vandalur Zoo, Kandigai, Kelambakkam, Sipcot |
| **Route AR 4** | Moolakadai | 6:10 AM | Perambur, Dowton, Central, Marina Beach, Adyar, Sholinganallur |
| **Route N/3** | MMDA School | 6:15 AM | Anna Nagar, Skywalk, Loyola College, T. Nagar, Saidapet, Velachery, OMR |
| **Route AR 6** | MMDA School / ICF | 6:10 AM | Egmore, Triplicane, Madhyakilash, SRP Tools, Perungudi, Karapakkam |
| **Route AR 7** | Chunambedu | 5:25 AM | Kalpakkam, Thirukazukundram, Paiyanur, Thirupporur, Kelambakkam |
| **Route AR 8** | Manjambakkam | 5:50 AM | Retteri, Padi, Ashok Pillar, Aadampakkam, Pallikarani, Medavakkam |
| **Route AR 9** | Ennore | 6:15 AM | Broadway, Central, Mylapore, Mandaveli, Adyar, Thiruvanmiyur |
| **Route AR 10** | Porur | 6:25 AM | Kundrathur, Pallavaram, Chrompet, Tambaram, Camp Road, Medavakkam |
| **Route R 22** | Nemilichery | 5:50 AM | Poonnamalle, Ramachandra Hospital, Porur, Kathipara, Velachery, Medavakkam |

*Note: Individual drivers' personal phone numbers are withheld for privacy reasons. For any urgent transport inquiries or coordinates, contact the General Office: +91 99400 04500.*

### 2. Transport Office
*   👤 **Transport Convener:** Dr. K. P. Santhosh Nathan (Email: ped.santhosh@msajce-edu.in)
*   👤 **Assistant Transport Convener:** Mr. A. Abdul Gafoor
""",
        "citations": [{"source": "msajce_transport.md", "page": "1", "section": "College Bus Facility"}]
    },
    {
        "query": "Tell me about the laboratory facilities, technology centres, and practical learning infrastructure at MSAJCE.",
        "answer": """**Practical Learning Labs & Technology Centres**

MSAJCE features state-of-the-art laboratory infrastructure and specialized Centres of Excellence (CoE) to build industry-ready skills.

### 1. Specialized Technology Centres (CoEs)

| Centre Name | Focus Area / Training Partners |
| :--- | :--- |
| **Apple iOS Lab** | Mobile Application Development |
| **Red Hat Academy** | Linux Administration & Open Source Technologies |
| **CISCO Networking Academy** | Network Routing, Switching (CCNA) & Cyber Security |
| **Texas Instruments Lab** | Embedded Systems, Microcontrollers & Internet of Things (IoT) |
| **E-Yantra Robotics Lab** | Robotics Design and Automation (supported by IIT Bombay) |

### 2. Infrastructure & Computing
*   **Computing Facilities:** Over **1,000+ high-end computers** deployed across dedicated department labs.
*   **Network:** Connected via high-speed optical fiber backbone with **100 Mbps dedicated leased-line internet** and Wi-Fi access.
*   **Core Labs:** Advanced engineering laboratories matching Anna University curricula (e.g. CAD/CAM Labs, VLSI design systems, Soil mechanics, Concrete highway systems, and Heat transfer systems).
""",
        "citations": [{"source": "msajce_placement.md", "page": "1", "section": "Facilities"}]
    },
    {
        "query": "What scholarships are available for students at MSAJCE?",
        "answer": """**Scholarships & Financial Aid at MSAJCE**

deserving and meritorious students joining MSAJCE can apply for government schemes or trust-based scholarships.

### 1. Government Scholarship Schemes

| Scholarship Name | eligibility criteria | Wards Assistance / Amount |
| :--- | :--- | :--- |
| **Pragati Scholarship (AICTE)** | Girl students (up to 2 per family), Income < 8 Lakhs | Rs. 50,000 / Year |
| **Saksham Scholarship (AICTE)** | Specially abled students (disability >= 40%), Income < 8 Lakhs | Rs. 50,000 / Year |
| **Merit-cum-Means (MOMA)** | Minority community students with >= 50% marks in +2, Income < 2.5 Lakhs | Rs. 20,000 / Year (+ Hosteller/Day Scholar allowances) |
| **Central Sector Scheme (MHRD)** | Students scoring >= 80th percentile in board exams, Income < 8 Lakhs | Rs. 10,000 / Year |
| **Labour Welfare Scheme** | Wards of Beedi, Mine, and Cine Workers, family income < 10,000/month | Rs. 15,000 / Year |

### 2. Mohamed Sathak Trust & Merit Aid
*   **Management Scholarships:** Wards joining MSAJCE via TNEA with cutoffs of **180/200 and above** are eligible for educational merit scholarships covering tuition fees (subject to trust approval).
*   **Special Consideration for Girls:** A dedicated **10% tuition fee waiver** is provided for girl students by the Trust.
*   **Need-Based Financial Assistance:** Wards from economically weaker sections receive management waivers upon income certificate validation.
""",
        "citations": [{"source": "msajce_admission.md", "page": "1", "section": "Under Graduate Programmes"}]
    },
    {
        "query": "Tell me about MSAJCE's affiliation, accreditation, NAAC grade, and history.",
        "answer": """** Mohamed Sathak A.J. College of Engineering (MSAJCE)**

MSAJCE was established in **2001** by the Mohamed Sathak Trust, a pioneer in educational institutions. The college is located in Siruseri IT Park, inside the Chennai IT corridor on Rajiv Gandhi Salai (OMR).

### 1. Affiliations & Approvals
*   **Anna University:** Affiliated to Anna University, Chennai.
*   **AICTE:** Approved by the All India Council for Technical Education, New Delhi.

### 2. Quality Accreditations

| Metric / Body | Accreditation Status |
| :--- | :--- |
| **NAAC Rating** | Accredited with an **'A' Grade** |
| **NBA Accreditation** | Key departments (Mechanical Engineering, Electronics & Communication) are accredited by the NBA |
| **NIRF Participation** | Participates annually in the National Institutional Ranking Framework |

### 3. Campus Location
*   **Address:** 34, Rajiv Gandhi Salai (OMR), Inside SIPCOT IT Park, Siruseri, Egattur, Chennai, Tamil Nadu 603103.
*   **Precise Coordinates:** 12.8358° N, 80.2186° E (or 12°50'08.9"N 80°13'07.0"E)
*   **Plus Code:** R6P9+8C Egattur, Tamil Nadu
*   📍 **Google Maps Location:** [Mohamed Sathak A.J. College of Engineering on Google Maps](https://maps.app.goo.gl/nrTgXSwx1h76SjdSA)

### 4. Institutional Vision & Mission
*   **Vision:** To provide quality technical education and create engineers with high ethical standards and professional competence.
*   **Mission:** To provide advanced learning infrastructure, nurture R&D activities, and inculcate moral values and leadership skills to make students productive members of society.
""",
        "citations": [{"source": "msajce_about.md", "page": "1", "section": "Overview"}]
    },
    {
        "query": "What sports facilities, athletic infrastructure, and student clubs are active at MSAJCE?",
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
""",
        "citations": [{"source": "msajce_sports.md", "page": "1", "section": "Overview"}]
    },
    {
        "query": "What are the official contact numbers, email addresses, and location details for visiting MSAJCE campus?",
        "answer": """**Contact Information & Location**

### 1. Campus Address
**Mohamed Sathak A.J. College of Engineering**
34, Rajiv Gandhi Salai (OMR), Inside SIPCOT IT Park, Siruseri, Egattur, Chennai, Tamil Nadu 603103, India.

*   **Coordinates:** 12.8358° N, 80.2186° E (or 12°50'08.9"N 80°13'07.0"E)
*   **Plus Code:** R6P9+8C Egattur, Tamil Nadu
*   📍 **Google Maps Location:** [Mohamed Sathak A.J. College of Engineering on Google Maps](https://maps.app.goo.gl/nrTgXSwx1h76SjdSA)

### 2. Key Office Contacts

| Department / Query | Phone Number / Contact | Email / Website |
| :--- | :--- | :--- |
| **Admission Helpline** | +91 99400 04500 | msajce.office@gmail.com |
| **Head of Admission** | Dr. K. P. Santhosh Nathan | ped.santhosh@msajce-edu.in |
| **Administrative Landline** | 044 - 2747 0021 / 23 / 24 / 25 / 26 / 0025 | admin@msajce-edu.in / msajce.office@gmail.com |
| **Placement Cell** | Mr. S.V. Vinodh | placement@msajce-edu.in |
| **Official Website** | — | [www.msajce-edu.in](https://www.msajce-edu.in) |
""",
        "citations": [{"source": "msajce_about.md", "page": "1", "section": "Overview"}]
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
