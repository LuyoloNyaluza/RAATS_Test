import sys
import re

file_path = r'C:\Users\Zamuxolo\RAATS_Test\src\agents\trading_loop_dynamic.py'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Check if helper already exists
if '_replenish_waitlist_from_universe' in content:
    print("Helper already exists, skipping insertion.")
else:
    # Insert helper method before _get_replacements
    # We'll use regex to find the method definition and insert before it.
    # Pattern for the method definition line (with possible whitespace)
    pattern = r'(\s+def _get_replacements\(self,\s*number_needed: int,\) -> List\[str\]:)'
    # We want to insert the helper before this pattern.
    helper = '''    # ----------------------------------
    # Helper to replenish waiting list from universe
    # ----------------------------------
    def _replenish_waitlist_from_universe(self, count: int) -> None:
        """Add up to `count` new tickers from ticker_universe to waiting list,
        skipping those already in active list, final_invest, waiting list,
        or closed positions.
        """
        added = 0
        while added < count and self._next_universe_index < len(self.ticker_universe):
            ticker = self.ticker_universe[self._next_universe_index]
            self._next_universe_index += 1
            if (
                ticker not in self.active_list
                and ticker not in self.final_invest
                and ticker not in self.waitlist
                and ticker not in self.closed_positions_today
            ):
                self.waitlist.append(ticker)
                added += 1

'''
    # We need to preserve the indentation of the line before insertion.
    # We'll do a simple replacement: insert the helper before the match.
    # We'll use re.sub with a lambda to insert the helper before the match.
    def insert_helper(match):
        return helper + match.group(0)
    
    new_content = re.sub(pattern, insert_helper, content, count=1)
    
    # Now we need to modify the _get_replacements method to add a call to the helper before returning.
    # We'll find the method body and insert the call before the return statement.
    # We'll do another regex to capture the method body and replace it.
    # We'll match from the method definition line to the next line that starts with the same indentation as the method definition but is a new method or class or end of string.
    # This is more complex; we'll instead do a simple replacement: look for the line 'return replacements' and insert the call block before it.
    # We'll do lines.
    lines = new_content.splitlines(keepends=True)
    # Find the index of the line that contains 'def _get_replacements'
    method_start = None
    for i, line in enumerate(lines):
        if line.rstrip().startswith('def _get_replacements(self,'):
            method_start = i
            break
    if method_start is None:
        print("ERROR: Could not find _get_replacements after inserting helper")
        sys.exit(1)
    # Find the end of the method: look for the next line that starts with the same indentation as the method definition and is a def or class.
    indent = len(lines[method_start]) - len(lines[method_start].lstrip())
    method_end = None
    for i in range(method_start + 1, len(lines)):
        if len(lines[i]) - len(lines[i].lstrip()) == indent and (lines[i].lstrip().startswith('def ') or lines[i].lstrip().startswith('class ')):
            method_end = i
            break
    if method_end is None:
        method_end = len(lines)
    # Now we have the method lines.
    method_lines = lines[method_start:method_end]
    # We'll insert the call block before the final 'return replacements' line.
    new_method_lines = []
    for line in method_lines:
        if line.rstrip() == 'return replacements':
            # Insert the call block before this line.
            line_indent = len(line) - len(line.lstrip())
            new_method_lines.append(' ' * line_indent + '# ----------------------------------\n')
            new_method_lines.append(' ' * line_indent + '# Replenish waiting list from universe for each replacement used\n')
            new_method_lines.append(' ' * line_indent + '# ----------------------------------\n')
            new_method_lines.append(' ' * line_indent + f'self._replenish_waitlist_from_universe(len(replacements))\n')
            new_method_lines.append(line)  # keep the return line
        else:
            new_method_lines.append(line)
    # Replace the method lines
    lines[method_start:method_end] = new_method_lines
    new_content = ''.join(lines)
    
    # Write back
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("SUCCESS: Updated trading_loop_dynamic.py with replenishment logic.")