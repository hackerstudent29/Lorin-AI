import re

file_path = r"d:\.gemini\bots\MSAJCE chatbot 1\backend\dataset\committees_and_policies\msajce_msajcepolicy.md"

with open(file_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    line = line.strip()
    
    # Remove numbered list markers at the start of the line (e.g., "1. ", "2. ")
    line = re.sub(r'^\d+\.\s+', '', line)
    
    # Remove bullet markers like "-", "*" if any exist at the start
    line = re.sub(r'^[-*]\s+', '', line)
    
    new_lines.append(line)

# Rejoin with newlines so we have a clean text
text = '\n'.join(new_lines)

# Now, split by double newlines to get paragraphs
paragraphs = text.split('\n\n')

formatted_paragraphs = []
for p in paragraphs:
    # Inside each paragraph, replace single newlines with spaces
    # This joins hard-wrapped lines into a single continuous sentence/paragraph
    # But first, ensure we don't have multiple spaces
    p = p.replace('\n', ' ')
    p = re.sub(r'\s+', ' ', p)
    formatted_paragraphs.append(p.strip())

# Join paragraphs with double newlines
final_text = '\n\n'.join(formatted_paragraphs)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(final_text)

print("Hard wraps and list markers removed.")
