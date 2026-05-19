import os
import re

def fix_except(content):
    # This regex matches 'except (Exception1, Exception2):'
    # It safely handles multiple exceptions separated by commas before the colon
    # We only want to match lines starting with 'except ' and ending with ':'
    # where there are no parentheses but there are commas.
    
    def replacer(match):
        exceptions = match.group(1).strip()
        if ' as ' in exceptions:
            return match.group(0) # Do not touch 'except A, B as e' wait, that's invalid anyway
        # If it already has parens, it won't match our regex because we exclude parens
        return f"except ({exceptions}):"

    # Match 'except ' followed by anything without parenthesis, ending in ':'
    # e.g. 'except (ValueError, KeyError):'
    # We must be careful not to match 'except Exception as e:'
    # So we only match if there is a comma
    new_content = re.sub(r'except\s+([A-Za-z0-9_,\s]+):', lambda m: f"except ({m.group(1)}):" if ',' in m.group(1) and ' as ' not in m.group(1) else m.group(0), content)
    return new_content

for root, _, files in os.walk('.'):
    if '.venv' in root or '.git' in root or '__pycache__' in root:
        continue
    for file in files:
        if file.endswith('.py'):
            path = os.path.join(root, file)
            with open(path, 'r') as f:
                content = f.read()
            new_content = fix_except(content)
            if new_content != content:
                print(f"Fixed {path}")
                with open(path, 'w') as f:
                    f.write(new_content)
