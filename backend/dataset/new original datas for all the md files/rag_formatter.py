import re

file_path = r"d:\.gemini\bots\MSAJCE chatbot 1\backend\dataset\committees_and_policies\msajce_msajcepolicy.md"

with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
    lines = f.readlines()

main_headings = [
    r"E-Governance Policy",
    r"Feedback Policy",
    r"HR Policies",
    r"Scholarship Policy",
    r"ANTI RAGGING POLICY",
    r"Institutional Green Policy",
    r"Roles and Responsibility",
    r"Code of Conduct \(Teaching Faculty\)",
    r"Code Of Conduct \(Administrative \/ Support Staff\)",
    r"Other Terms and Conditions",
    r"Waste Management Policy",
    r"E-Waste Policy",
    r"Sustainability Policy",
    r"Biodiversity Policy",
    r"Environmental Policy",
    r"Reducing Carbon Emissions",
    r"Responsibilities of HOD",
    r"Responsibilities of Placement Officer",
    r"Responsibilities of a Faculty",
    r"Responsibility of Librarian",
    r"Responsibility of Physical Education Director",
    r"General instructions to all the Faculty members",
    r"Do(?:'|`|’)?s and Don(?:'|`|’)?ts for Theory Subjects",
    r"Do(?:'|`|’)?s and Don(?:'|`|’)?ts For Practical Classes",
    r"Responsibilities of Class Advisor",
    r"Responsibilities of Mentors",
    r"Responsibilities of Placement Co-coordinators",
    r"Responsibility of Faculty Lab In charge",
    r"Responsibility of Faculty Handling laboratory classes",
    r"Responsibility of Professional Society Coordinator",
    r"Responsibility of Floor Incharge",
    r"Responsibility of the Head –Academic",
    r"Responsibility of Head –Students Affairs",
    r"Responsibility of Head Technology Centres & Industrial Relations(?:. \(TC&IR\))?",
    r"Responsibility of Head – Research",
    r"Responsibility of Head – IQAC",
    r"Responsibility of Manager – Accounts",
    r"Responsibility of Manager – Administration",
    r"Responsibility of the Maintenance Manager",
    r"Responsibility of the Accountant",
    r"Responsibility of the Exam cell Coordinator"
]

sub_headings = [
    r"Definition",
    r"Orientation",
    r"Staff Dress Code",
    r"Attendance Record",
    r"Recruitment \/ Interview Process of Staff",
    r"Probation Period",
    r"Increment \/ Promotions",
    r"Termination of Service \/ Resignation",
    r"Leave Rules",
    r"Casual Leave \(CL\)",
    r"Vacation Leave \(VL\)",
    r"Restricted Holiday \(RH\)",
    r"Special Leave \(SL\)",
    r"Compensation Off \(C- Off\)",
    r"Maternity Leave \(ML\)",
    r"Leave with Loss of Pay \(LOP\)",
    r"On - Duty \(OD\)",
    r"Conduct & Discipline",
    r"Obligation to maintain secrecy",
    r"Relieving Policies",
    r"Retirement Policies",
    r"Transfer within group of Institutions",
    r"Awards \/ Incentives for faculty, staff and students",
    r"Higher studies",
    r"Patent and IPR",
    r"Patent fee",
    r"Revenue sharing",
    r"Conversion\/Transfer of IP"
]

def clean_line(text):
    text = text.strip()
    # Remove weird bullet characters
    text = re.sub(r'[•❖]', '', text)
    # Remove standard bullets at start (hyphen, asterisk)
    text = re.sub(r'^[-*]+\s*', '', text)
    # Remove letter 'o' if it is used as a bullet (must be followed by space)
    text = re.sub(r'^o\s+', '', text)
    # Remove number bullets like "1. ", "a. ", "12. "
    text = re.sub(r'^\d+\.\s*', '', text)
    text = re.sub(r'^[a-zA-Z]\.\s+', '', text)
    # Remove any trailing colons that are detached
    text = re.sub(r'\s+:$', ':', text)
    return text.strip()

def is_heading(line):
    for h in main_headings:
        if re.fullmatch(h + r'[:.]?', line, re.IGNORECASE):
            return 1, line.rstrip(':.')
    for h in sub_headings:
        if re.fullmatch(h + r'[:.]?', line, re.IGNORECASE):
            return 2, line.rstrip(':.')
    return 0, line

paragraphs = []
current_para = []

def flush_para():
    global current_para
    if current_para:
        para_text = " ".join(current_para)
        para_text = re.sub(r'\s+', ' ', para_text)
        paragraphs.append(para_text)
        current_para = []

for line in lines:
    raw_cleaned = line.strip()
    # Check if a line is just whitespace
    if not raw_cleaned:
        flush_para()
        continue
    
    cleaned = clean_line(raw_cleaned)
    if not cleaned:
        continue
    
    # Is it exactly a heading?
    h_level, h_text = is_heading(cleaned)
    if h_level > 0:
        flush_para()
        if h_level == 1:
            paragraphs.append(f"# {h_text}")
        else:
            paragraphs.append(f"## {h_text}")
        continue
        
    # Check embedded headings
    matched = False
    for h in main_headings:
        match = re.match(r'^(' + h + r'[:.])\s+(.*)', cleaned, re.IGNORECASE)
        if match:
            flush_para()
            paragraphs.append(f"# {match.group(1).rstrip(':.')}")
            if match.group(2):
                current_para.append(match.group(2))
            matched = True
            break
            
    if matched: continue

    for h in sub_headings:
        match = re.match(r'^(' + h + r'[:.])\s+(.*)', cleaned, re.IGNORECASE)
        if match:
            flush_para()
            paragraphs.append(f"## {match.group(1).rstrip(':.')}")
            if match.group(2):
                current_para.append(match.group(2))
            matched = True
            break
            
    if matched: continue
        
    current_para.append(cleaned)

flush_para()

final_text = '\n\n'.join(paragraphs)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(final_text)

print("Formatted!")
