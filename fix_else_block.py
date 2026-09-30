import sys
import os

trading_loop_path = r'C:\Users\Zamuxolo\RAATS_Test\src\agents\trading_loop_dynamic.py'

with open(trading_loop_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the function _generate_dynamic_universe
for i, line in enumerate(lines):
    if line.strip().startswith('def _generate_dynamic_universe'):
        # Find the end of the function
        j = i + 1
        while j < len(lines):
            if lines[j].strip().startswith('def ') and (len(lines[j]) - len(lines[j].lstrip())) == (len(lines[i]) - len(lines[i].lstrip())):
                break
            j += 1
        # Now we have the function lines[i:j]
        # We need to find the else block inside this function.
        # Let's find the line: 'else:'
        for k in range(i, j):
            if lines[k].strip().startswith('else:'):
                # Now we need to find the end of the else block.
                # Determine the indent of the else line
                else_indent = len(lines[k]) - len(lines[k].lstrip())
                # Find the end of the else block: next line with indent <= else_indent and not empty
                l = k + 1
                while l < j:
                    if lines[l].strip() == '':
                        l += 1
                        continue
                    if len(lines[l]) - len(lines[l].lstrip()) <= else_indent:
                        break
                    l += 1
                # Replace lines[k:l] with the new block
                new_block = [
                    '            if not tickers:\n',
                    '                print(\"WARNING: Dynamic universe generation returned empty list. No candidates for this session.\")\n',
                    '                # Do not fall back to static list; keep empty to signal no candidates.\n',
                    '                self._last_universe = []\n',
                    '                self._last_random_list = []\n',
                    '                return [], [], {}\n'
                ]
                # Apply the same indent as the else line (which is 12 spaces? we'll keep the indent of the else line)
                # Actually, the else line is inside the function, so we keep its indentation.
                # We'll just use the lines as we wrote them (they have 12 spaces? we'll keep the indent we found in the original else line)
                # But we wrote new_block with 12 spaces? Let's just use the indent from the original else line.
                orig_else_indent = len(lines[k]) - len(lines[k].lstrip())
                new_block = [(' ' * orig_else_indent) + l if not l.startswith(' ') else l for l in new_block]
                lines[k:l] = new_block
                break
        break

with open(trading_loop_path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Fixed else block in _generate_dynamic_universe")