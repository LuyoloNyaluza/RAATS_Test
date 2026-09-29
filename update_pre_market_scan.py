import sys
import os

trading_loop_path = r'C:\Users\Zamuxolo\RAATS_Test\src\agents\trading_loop_dynamic.py'
with open(trading_loop_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Change the annotation of pre_market_scan to -> None
for i, line in enumerate(lines):
    if line.strip().startswith('def pre_market_scan'):
        # We'll change the line to add -> None
        # Find the end of the line (the colon)
        if '->' in line:
            # Already has a return annotation, replace it
            # We'll split at '->' and keep the part before, then add ' -> None:'
            parts = line.split('->')
            lines[i] = parts[0] + ' -> None:\n'
        else:
            # No return annotation, add before the colon
            if line.endswith(':\n'):
                lines[i] = line[:-2] + ' -> None:\n'
            else:
                # If it doesn't end with colon, we assume it's missing and add it
                lines[i] = line.rstrip() + ' -> None:\n'
        break

# Now find the else block in pre_market_scan that handles empty tickers from _generate_dynamic_universe
# We'll look for the line: 'if not tickers:'
for i, line in enumerate(lines):
    if line.strip().startswith('if not tickers:'):
        # We found the if block. We'll replace from this line to the end of the if block.
        # Determine the indent of this if line
        if_indent = len(line) - len(line.lstrip())
        # Find the end of the if block: the next line that has indent <= if_indent and is not empty
        j = i + 1
        while j < len(lines):
            if lines[j].strip() == '':
                j += 1
                continue
            if len(lines[j]) - len(lines[j].lstrip()) <= if_indent:
                break
            j += 1
        # Replace lines[i:j] with the new block
        new_block = [
            '            if not tickers:\n',
            '                print("WARNING: Dynamic universe generation returned empty list. No candidates for this session.")\n',
            '                self._last_universe = []\n',
            '                self._last_random_list = []\n',
            '                self.active_list = []\n',
            '                self.waitlist = []\n',
            '                self.all_sentiment_scores = {}\n',
            '                return\n'
        ]
        # Apply the same indent as the if line
        new_block = [(' ' * if_indent) + l if not l.startswith(' ') else l for l in new_block]
        lines[i:j] = new_block
        break

with open(trading_loop_path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Updated pre_market_scan to handle empty dynamic universe without fallback")