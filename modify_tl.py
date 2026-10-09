import sys
file_path = r'C:\Users\Zamuxolo\RAATS_Test\src\agents\trading_loop_dynamic.py'
with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find index of _get_replacements
start_idx = None
for i, line in enumerate(lines):
    if line.rstrip().startswith('def _get_replacements(self,'):
        start_idx = i
        break
if start_idx is None:
    print("ERROR: Could not find _get_replacements method")
    sys.exit(1)

# Helper method text
helper_lines = [
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

# Insert helper before _get_replacements
lines[start_idx:start_idx] = helper_lines

# Now find the new start index of _get_replacements after insertion
new_start_idx = None
for i, line in enumerate(lines):
    if line.rstrip().startswith('def _get_replacements(self,'):
        new_start_idx = i
        break
if new_start_idx is None:
    print("ERROR: Could not find _get_replacements after inserting helper")
    sys.exit(1)

# Find end of method: look for next line that starts with '    def ' or '    class ' after new_start_idx
end_idx = None
for i in range(new_start_idx + 1, len(lines)):
    stripped = lines[i].lstrip()
    if stripped.startswith('def ') or stripped.startswith('class '):
        # Check if line is at class level (indentation 4 spaces)
        if lines[i].startswith('    def ') or lines[i].startswith('    class '):
            end_idx = i
            break
if end_idx is None:
    end_idx = len(lines)

# Extract method lines
method_lines = lines[new_start_idx:end_idx]
# We'll insert a call to the helper before the final 'return replacements' line.
new_method_lines = []
for line in method_lines:
    if line.rstrip() == 'return replacements':
        # Insert the call block before this line.
        indent = len(line) - len(line.lstrip())
        new_method_lines.append(' ' * indent + '# ----------------------------------\n')
        new_method_lines.append(' ' * indent + '# Replenish waiting list from universe for each replacement used\n')
        new_method_lines.append(' ' * indent + '# ----------------------------------\n')
        new_method_lines.append(' ' * indent + f'self._replenish_waitlist_from_universe(len(replacements))\n')
        new_method_lines.append(line)  # keep the return line
    else:
        new_method_lines.append(line)

# Replace method lines
lines[new_start_idx:end_idx] = new_method_lines

# Write back
with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("SUCCESS: Updated trading_loop_dynamic.py with replenishment logic.")