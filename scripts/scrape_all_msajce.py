import os
import sys
import time
import requests
from bs4 import BeautifulSoup

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")
if not NVIDIA_API_KEY:
    print("❌ Error: NVIDIA_API_KEY environment variable not set.")
    sys.exit(1)

urls = [
    # Major Departments First
    'cse.php', 'it.php', 'ece.php', 'mech.php', 'eee.php', 
    'ece-vlsi.php', 'ece-act.php', 'csbs.php', 'aids.php',
    
    # Academics & Syllabi
    'curriculm.php', 'ese-timetable.php', 'placement.php', 'research.php',
    
    # Campus Facilities & Committees
    'hostel.php', 'library.php', 'transport.php', 'sports.php', 'iqac.php',
    'clubssocieties.php', 'campusradio.php', 'socialservices.php',
    'womensempowermentcell.php', 'karma.php', 'nirf.php', 
    'incubation&startup.php', 'graduationday.php', 'technologycentre.php', 
    'naac.php', 'cyber.php', 'governingcouncil.php', 'planningmonitoringboard.php', 
    'mandatorydisclosure.php', 'principal.php', 'grievanceredressalcommittee.php', 
    'ebsb.php', 'newsletter.php', 'sh.php', 'studentscorner.php', 
    'functionalcommittees.php', 'ourhistory.php'
]

base_url = 'https://www.msajce-edu.in/'
out_dir = os.path.join('backend', 'dataset')
os.makedirs(out_dir, exist_ok=True)

def chunk_text(lines, max_chars=1500):
    chunks = []
    current_chunk = []
    current_len = 0
    for line in lines:
        if current_len + len(line) > max_chars and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = [line]
            current_len = len(line)
        else:
            current_chunk.append(line)
            current_len += len(line)
    if current_chunk:
        chunks.append("\n".join(current_chunk))
    return chunks

def scrape_page(page_url):
    filename = page_url.replace('.php', '.md')
    out_path = os.path.join(out_dir, f'msajce_{filename}')
    full_url = base_url + page_url
    print(f'\n🚀 Scraping {full_url}')
    try:
        res = requests.get(full_url)
        if res.status_code != 200:
            print(f'   ❌ Page returned {res.status_code}')
            return
        soup = BeautifulSoup(res.text, 'html.parser')
        tab_content = soup.find('div', class_='tab-content')
        if not tab_content:
            print('   ⚠️ No tab-content found, skipping.')
            return
        tabs = tab_content.find_all('div', class_='tab-pane', recursive=False)
        if not tabs:
            return
        
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(f'# {page_url.replace(".php", "").upper()}\n\n')
        
        for idx, tab in enumerate(tabs):
            heading = tab.find(['h2', 'h3'])
            tab_title = heading.get_text(strip=True) if heading else f'Section {idx+1}'
            print(f'   -> Tab {idx+1}/{len(tabs)}: {tab_title}')
            with open(out_path, 'a', encoding='utf-8') as f:
                f.write(f'## {tab_title}\n\n')
            
            tab_text_lines = []
            for elem in tab.find_all(['p', 'h3', 'table', 'h4']):
                if elem.name == 'table':
                    for tr in elem.find_all('tr'):
                        cells = [td.get_text(separator=' ', strip=True) for td in tr.find_all(['th', 'td'])]
                        if cells:
                            tab_text_lines.append(' | '.join(cells))
                else:
                    text = elem.get_text(separator=' ', strip=True)
                    if text and text != tab_title:
                        tab_text_lines.append(text)
            
            chunks = chunk_text(tab_text_lines, max_chars=1500)
            for c_idx, chunk in enumerate(chunks):
                if not chunk.strip(): continue
                
                sys_prompt = f"""You are an expert technical writer and data extractor for Mohamed Sathak A.J. College of Engineering (MSAJCE).
🎯 YOUR GOAL:
Read the provided chunk of data and transform all the factual data into beautiful, natural English prose paragraphs suitable for RAG (Retrieval-Augmented Generation).
⚠️ ABSOLUTE RULE — 100% DATA INTEGRITY:
- Extract EVERY SINGLE NAME, TITLE, EVENT, BATCH YEAR, COURSE CODE, SUBJECT, and COMPANY from the text.
- Do not drop any data. Do not hallucinate facts.
✍️ STYLE & FORMATTING:
1. NO BULLET POINTS OR TABLES. Do not output markdown tables. Write flowing narrative sentences instead.
2. VARY YOUR SENTENCE STRUCTURE. Do NOT start every sentence with the same phrase.
3. OUTPUT ONLY PLAIN TEXT PARAGRAPHS separated by blank lines.
4. Ignore any UI navigation text that has no associated data.
"""
                payload = {
                    'model': 'meta/llama-3.1-70b-instruct',
                    'messages': [
                        {'role': 'system', 'content': sys_prompt},
                        {'role': 'user', 'content': f'Transform the following raw data from the {tab_title} section into natural, varied English prose paragraphs. DO NOT omit any names, dates, course codes, or titles. Write flowing sentences, not bullet points:\n\n{chunk}'}
                    ],
                    'temperature': 0.1,
                    'max_tokens': 4000
                }
                
                success = False
                for attempt in range(3):
                    try:
                        r = requests.post('https://integrate.api.nvidia.com/v1/chat/completions', 
                                          headers={'Authorization': f'Bearer {NVIDIA_API_KEY}', 'Content-Type': 'application/json'},
                                          json=payload, timeout=90)
                        r.raise_for_status()
                        part_text = r.json()['choices'][0]['message']['content'].strip()
                        if part_text.startswith('```'):
                            part_text = part_text.split('\n', 1)[-1].rsplit('\n', 1)[0].strip()
                        with open(out_path, 'a', encoding='utf-8') as f:
                            f.write(part_text + '\n\n')
                        success = True
                        time.sleep(5.0)  # Wait 5 seconds to strictly manage rate limits
                        break
                    except Exception as e:
                        print(f'      [RETRY {attempt+1}/3] {e}')
                        time.sleep(3 * (attempt + 1))
                if not success:
                    with open(out_path, 'a', encoding='utf-8') as f:
                        f.write(chunk + '\n\n')
    except Exception as e:
        print(f'Error on {page_url}: {e}')

if __name__ == "__main__":
    for u in urls:
        scrape_page(u)
    print('\n✅ All pages processed!')
