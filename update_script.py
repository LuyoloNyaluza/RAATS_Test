import sys
file_path = r'C:\Users\Zamuxolo\RAATS_Test\src\agents\trading_loop_dynamic.py'
with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the line index where the method starts (by looking for a line that contains 'def _get_replacements' and the next line contains 'self,')
method_start = None
for i in range(len(lines)-1):
    if 'def _get_replacements' in lines[i] and 'self,' in lines[i+1]:
        method_start = i
        break
if method_start is None:
    # fallback: just look for 'def _get_replacements'
    for i, line in enumerate(lines):
        if 'def _get_replacements' in line:
            method_start = i
            break
if method_start is None:
    print("ERROR: Could not find _get_replacements method")
    sys.exit(1)

# Insert helper before method_start
helper = [
    '    # ----------------------------------\n',
    '    # Helper to replenish waiting list from universe\n',
    '    # ----------------------------------\n',
    '    def _replenish_waitlist_from_universe(self, count: int) -> None:\n',
    '        """Add up to `count` new tickers from ticker_universe to waiting list,\n',
    '        skipping those already in active list, final_invest, waiting list,\n',
    '        or closed positions.\n',
    '        """\n',
    '        added = 0\n',
    '        while added < count and self._next_universe_index < len(self.ticker_universe):\n',
    '            ticker = self.ticker_universe[self._next_universe_index]\n',
    '            self._next_universe_index += 1\n',
    '            if (\n',
    '                ticker not in self.active_list\n',
    '                and ticker not in self.final_invest\n',
    '                and ticker not in self.waitlist\n',
    '                and ticker not in self.closed_positions_today\n',
    '            ):\n',
    '                self.waitlist.append(ticker)\n',
    '                added += 1\n',
    '\n'
]
lines[method_start:method_start] = helper

# Now find the new method start (after insertion)
new_method_start = None
for i in range(len(lines)-1):
    if 'def _get_replacements' in lines[i] and 'self,' in lines[i+1]:
        new_method_start = i
        break
if new_method_start is None:
    for i, line in enumerate(lines):
        if 'def _get_replacements' in line:
            new_method_start = i
            break
if new_method_start is None:
    print("ERROR: Could not find _get_replacements after inserting helper")
    sys.exit(1)

# Find the end of the method: look for the next line that starts with the same indentation as the method definition and is a def or class.
indent = len(lines[new_method_start]) - len(lines[new_method_start].lstrip())
method_end = None
for i in range(new_method_start + 1, len(lines)):
    if len(lines[i]) - len(lines[i].lstrip()) == indent and (lines[i].lstrip().startswith('def ') or lines[i].lstrip().startswith('class ')):
        method_end = i
        break
if method_end is None:
    method_end = len(lines)

# Extract the method lines
method_lines = lines[new_method_start:method_end]
# Insert a call to the helper before the final 'return replacements' line.
new_method_lines = []
for line in method_lines:
    if line.rstrip() == 'return replacements':
        line_indent = len(line) - len(line.lstrip())
        new_method_lines.append(' ' * line_indent + '# ----------------------------------\n')
        new_method_lines.append(' ' * line_indent + '# Replenish waiting list from universe for each replacement used\n')
        new_method_lines.append(' ' * line_indent + '# ----------------------------------\n')
        new_method_lines.append(' ' * line_indent + f'self._replenish_waitlist_from_universe(len(replacements))\n')
        new_method_lines.append(line)  # keep the return line
    else:
        new_method_lines.append(line)

# Replace the method lines
lines[new_method_start:method_end] = new_method_lines

# Write back
with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("SUCCESS: Updated trading_loop_dynamic.py with replenishment logic.")