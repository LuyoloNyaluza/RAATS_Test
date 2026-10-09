import sys

file_path = r'C:\Users\Zamuxolo\RAATS_Test\src\agents\trading_loop_dynamic.py'

with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the line index of _get_replacements
target = None
for i, line in enumerate(lines):
    if line.rstrip().startswith('def _get_replacements(self,'):
        target = i
        break
if target is None:
    print("ERROR: Could not find _get_replacements method")
    sys.exit(1)

# Helper method text with indentation matching the class methods (4 spaces)
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

# Insert helper before the target line
lines[target:target] = helper

# Now we need to adjust the target index because we inserted lines.
# Find the new index of _get_replacements
new_target = None
for i, line in enumerate(lines):
    if line.rstrip().startswith('def _get_replacements(self,'):
        new_target = i
        break
if new_target is None:
    print("ERROR: Could not find _get_replacements after inserting helper")
    sys.exit(1)

# Now we need to find the end of the _get_replacements method.
# We'll look for the next line that starts with '    def ' or '    class ' after new_target.
# The class methods are indented with 4 spaces, so we look for a line that starts with exactly 4 spaces then 'def ' or 'class '.
end = None
for i in range(new_target + 1, len(lines)):
    stripped = lines[i].lstrip()
    if stripped.startswith('def ') or stripped.startswith('class '):
        # Check if the line is at the same indentation level as the method definition.
        # The method definition line (at new_target) has indentation: len(lines[new_target]) - len(lines[new_target].lstrip())
        # We expect that to be 4 spaces.
        if lines[i].startswith('    def ') or lines[i].startswith('    class '):
            end = i
            break
if end is None:
    end = len(lines)

# Extract the method lines
method_lines = lines[new_target:end]
# We'll insert a call to the helper before the final 'return replacements' line.
new_method_lines = []
for line in method_lines:
    if line.rstrip() == 'return replacements':
        # Insert the call block before this line.
        # Determine the indentation of this line (should be 8 spaces? Let's compute).
        indent = len(line) - len(line.lstrip())
        # The call should be at the same indentation level as the method body.
        # We'll add the call lines with the same indent.
        new_method_lines.append(' ' * indent + '# ----------------------------------\n')
        new_method_lines.append(' ' * indent + '# Replenish waiting list from universe for each replacement used\n')
        new_method_lines.append(' ' * indent + '# ----------------------------------\n')
        new_method_lines.append(' ' * indent + f'self._replenish_waitlist_from_universe(len(replacements))\n')
        new_method_lines.append(line)  # keep the return line
    else:
        new_method_lines.append(line)

# Replace the method lines
lines[new_target:end] = new_method_lines

# Write back
with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("SUCCESS: Updated trading_loop_dynamic.py with replenishment logic.")