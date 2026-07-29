import re

def get_words(filepath):
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        text = f.read()
    # Find all alphabetical words
    words = re.findall(r'[A-Za-z]+', text.lower())
    return words

orig_words = get_words(r'd:\.gemini\bots\MSAJCE chatbot 1\backend\dataset\committees_and_policies\msajce_msajcepolicy_backup.md')
new_words = get_words(r'd:\.gemini\bots\MSAJCE chatbot 1\backend\dataset\committees_and_policies\msajce_msajcepolicy.md')

print(f"Original word count: {len(orig_words)}")
print(f"New word count: {len(new_words)}")

# Check for large blocks of missing words
orig_set = set(orig_words)
new_set = set(new_words)

missing_in_new = orig_set - new_set
missing_in_orig = new_set - orig_set

print(f"Unique words missing in new: {len(missing_in_new)}")
print(f"Unique words missing in original: {len(missing_in_orig)}")

# If word counts differ a lot, let's print the first point of divergence
if len(orig_words) != len(new_words):
    for i in range(min(len(orig_words), len(new_words))):
        if orig_words[i] != new_words[i]:
            print(f"Divergence at word {i}: Orig='{orig_words[i]}', New='{new_words[i]}'")
            print(f"Context (Orig): {' '.join(orig_words[max(0, i-5):i+5])}")
            print(f"Context (New): {' '.join(new_words[max(0, i-5):i+5])}")
            break
