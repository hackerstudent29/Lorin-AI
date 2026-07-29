import json
import os

transcript_path = r"C:\Users\sthir\.gemini\antigravity-ide\brain\9d5a8a57-cf16-41c4-a72b-c0a116714dc8\.system_generated\logs\transcript_full.jsonl"
output_path = r"d:\.gemini\bots\MSAJCE chatbot 1\backend\dataset\committees_and_policies\msajce_msajcepolicy.md"

extracted_lines = []
found = False

with open(transcript_path, 'r', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line)
        if data.get('type') == 'USER_INPUT':
            content = data.get('content', '')
            if 'The following changes were made by the USER to: d:\\.gemini\\bots\\MSAJCE chatbot 1\\backend\\dataset\\committees_and_policies\\msajce_msajcepolicy.md' in content:
                # We found the message! Let's extract the new lines from the diff block.
                lines = content.split('\n')
                in_diff = False
                for l in lines:
                    if l.startswith('[diff_block_start]'):
                        in_diff = True
                        continue
                    if l.startswith('[diff_block_end]'):
                        in_diff = False
                        break
                    
                    if in_diff:
                        if l.startswith('+ '):
                            extracted_lines.append(l[2:])
                        elif l.startswith('+'):
                            extracted_lines.append(l[1:])
                        elif l.startswith(' '):
                            extracted_lines.append(l[1:])
                found = True

if found and extracted_lines:
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(extracted_lines))
    print(f"Successfully recovered {len(extracted_lines)} lines!")
else:
    print("Could not find the diff block in the transcript.")
