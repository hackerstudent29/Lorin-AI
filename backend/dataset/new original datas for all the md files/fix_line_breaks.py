import re

file_path = r"d:\.gemini\bots\MSAJCE chatbot 1\backend\dataset\committees_and_policies\msajce_msajcepolicy.md"

with open(file_path, "r", encoding="utf-8") as f:
    text = f.read()

# Fix splits where a number followed by a dot caused a newline mid-sentence.
# e.g., "at the age of\n\n65. In case" -> "at the age of 65. In case"
# e.g., "during the year from 1st July to\n\n30th June." -> "during the year from 1st July to 30th June."
# We look for \n\n followed by a number and a dot, but we check if the preceding character is NOT a sentence ender (like ., :, !) or it's a lowercase letter or 'of', 'to', etc.

# A simpler way: Find all paragraphs. If a paragraph ends without a period, and the next paragraph starts with a number, they might have been split.
paragraphs = text.split('\n\n')
new_paragraphs = []

for p in paragraphs:
    p = p.strip()
    if not p:
        continue
    
    if new_paragraphs:
        prev = new_paragraphs[-1]
        # If the previous paragraph does NOT end with a valid sentence ending or punctuation that signifies end of a block
        # AND the current paragraph starts with a number.
        if re.match(r'^\d+\.', p) and not re.search(r'[.:!?>]$', prev):
            # Join them back
            new_paragraphs[-1] = prev + " " + p
            continue
            
    new_paragraphs.append(p)

# Also fix the weird "65. In case..." split directly just in case the above logic misses it.
# E.g., "at the age of\n\n65. "
text = '\n\n'.join(new_paragraphs)
text = re.sub(r'([a-z])\n\n(\d+\.)', r'\1 \2', text)
text = re.sub(r'([A-Za-z])\n\n([a-z])', r'\1 \2', text) # Any other mid-sentence splits?

with open(file_path, "w", encoding="utf-8") as f:
    f.write(text)

print("Line breaks fixed.")
