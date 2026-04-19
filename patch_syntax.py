with open('assistant/brain/ai_brain.py', 'r', encoding='utf-8') as f:
    text = f.read()

import re
text = re.sub(
    r'notes_str = "\n"\.join\(\[f"- \{n\}" for n in notes\]\) if notes else "None"',
    r'notes_str = "\\n".join([f"- {n}" for n in notes]) if notes else "None"',
    text
)

# wait actually since it was parsed as a literal newline it looks like:
# notes_str = "
# ".join...

# let's just replace the whole two lines:
import sys
content_lines = []
with open('assistant/brain/ai_brain.py', 'r', encoding='utf-8') as f:
    for line in f.readlines():
        if line.strip() == 'notes_str = "':
            continue
        if line.strip() == '".join([f"- {n}" for n in notes]) if notes else "None"':
            content_lines.append('                notes_str = "\\n".join([f"- {n}" for n in notes]) if notes else "None"\n')
            continue
        content_lines.append(line)

with open('assistant/brain/ai_brain.py', 'w', encoding='utf-8') as f:
    f.writelines(content_lines)
