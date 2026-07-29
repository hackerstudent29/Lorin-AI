# -*- coding: utf-8 -*-
import os
import re
import json

output_base = r'd:\.gemini\bots\MSAJCE chatbot 1\backend\dataset'
artifact_path = r'C:\Users\sthir\.gemini\antigravity-ide\brain\6347d93a-2190-4d81-aec0-8a63e8f60010\entity_registry.md'

# Match titles case insensitively, but names MUST start with an uppercase letter
name_pattern = re.compile(r'\b(Dr\.|Mr\.|Ms\.|Mrs\.|Prof\.)\s+([A-Z][A-Za-z\.]*(?:\s+[A-Z][A-Za-z\.]*)*)')

mentions_list = []

for root, dirs, files in os.walk(output_base):
    for file in files:
        if file.endswith('.md'):
            path = os.path.join(root, file)
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                for line in lines:
                    context = line.strip()
                    if not context: continue
                    # Find titles first, ignoring case
                    title_matches = re.finditer(r'\b(Dr\.|Mr\.|Ms\.|Mrs\.|Prof\.)\s+', context, re.IGNORECASE)
                    for tm in title_matches:
                        start_idx = tm.end()
                        title = tm.group(1).title()
                        
                        # Now match the name strictly with case sensitivity
                        # We look at the substring starting after the title
                        name_match = re.match(r'([A-Z][A-Za-z\.]*(?:\s+[A-Z][A-Za-z\.]*)*)', context[start_idx:])
                        if name_match:
                            name = name_match.group(1).strip()
                            full_name = f'{title} {name}'
                            full_name = re.sub(r'[,\(\)]+$', '', full_name).strip()
                            
                            role = 'Unknown'
                            if 'Professor' in context: role = 'Professor'
                            elif 'Assistant Professor' in context: role = 'Assistant Professor'
                            elif 'Managing Director' in context: role = 'Managing Director'
                            elif 'Student' in context or 'batch' in context.lower(): role = 'Student/Alumni'
                            elif 'CEO' in context: role = 'CEO'
                            elif 'Founder' in context: role = 'Founder'
                            elif 'Principal' in context: role = 'Principal'
                            elif 'Engineer' in context: role = 'Engineer'
                            
                            dept = 'Unknown'
                            if 'CSE' in context or 'Computer Science' in context: dept = 'CSE'
                            elif 'IT' in context or 'Information Technology' in context: dept = 'IT'
                            elif 'AIDS' in context or 'Artificial Intelligence' in context: dept = 'AIDS'
                            elif 'ECE' in context or 'Electronics' in context: dept = 'ECE'
                            elif 'Mech' in context or 'Mechanical' in context: dept = 'Mech'
                            elif 'Civil' in context: dept = 'Civil'
                            elif 'CSBS' in context or 'Business Systems' in context: dept = 'CSBS'
                            elif 'AIML' in context or 'Machine Learning' in context: dept = 'AIML'
                            elif 'VLSI' in context: dept = 'VLSI'
                            
                            mentions_list.append({
                                'name': full_name,
                                'role': role,
                                'dept': dept,
                                'file': file,
                                'context': context
                            })

# Group by name
grouped = {}
for m in mentions_list:
    n = m['name']
    if n not in grouped:
        grouped[n] = {'roles': set(), 'depts': set(), 'contexts': set(), 'files': set()}
    grouped[n]['roles'].add(m['role'])
    grouped[n]['depts'].add(m['dept'])
    grouped[n]['contexts'].add(m['context'])
    grouped[n]['files'].add(m['file'])

# Write to markdown
with open(artifact_path, 'w', encoding='utf-8') as f:
    f.write('# Entity Registry (Merged)\n\n')
    f.write('This table lists every distinct human name found in the documents. Mentions of the exact same name across different files are merged into a single entity.\n\n')
    f.write('| Entity Name | Roles | Departments | Files | Sample Context |\n')
    f.write('|---|---|---|---|---|\n')
    
    # Sort for consistent output
    for name, data in sorted(grouped.items()):
        roles_str = ', '.join(sorted([r for r in data['roles'] if r != 'Unknown']))
        if not roles_str: roles_str = 'Unknown'
        depts_str = ', '.join(sorted([d for d in data['depts'] if d != 'Unknown']))
        if not depts_str: depts_str = 'Unknown'
        files_str = ', '.join(sorted(data['files']))
        
        # Take the first context as a sample, escape pipes
        sample_ctx = list(data['contexts'])[0].replace('|', '\|')
        
        f.write(f'| {name} | {roles_str} | {depts_str} | {files_str} | {sample_ctx} |\n')

print(f'Merged {len(mentions_list)} mentions into {len(grouped)} distinct entities.')
