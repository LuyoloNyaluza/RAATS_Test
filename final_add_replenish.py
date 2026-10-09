import sys

def main():
    file_path = r'C:\Users\Zamuxolo\RAATS_Test\src\agents\trading_loop_dynamic.py'
    
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Step 1: Find where to insert the helper method (before _get_replacements)
    insert_idx = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith('def _get_replacements(self,'):
            insert_idx = i
            break
    
    if insert_idx is None:
        print("ERROR: Could not find _get_replacements method")
        return 1
        
    # Step 2: Define the helper method
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
    
    # Step 3: Insert the helper method before _get_replacements
    lines[insert_idx:insert_idx] = helper_lines
    
    # Step 4: Find the new location of _get_replacements after insertion
    new_insert_idx = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith('def _get_replacements(self,'):
            new_insert_idx = i
            break
            
    if new_insert_idx is None:
        print("ERROR: Could not find _get_replacements after inserting helper")
        return 1
        
    # Step 5: Find the end of the _get_replacements method
    # The method definition line is at new_insert_idx
    indent = len(lines[new_insert_idx]) - len(lines[new_insert_idx].lstrip())
    method_end = None
    for i in range(new_insert_idx + 1, len(lines)):
        if len(lines[i]) - len(lines[i].lstrip()) == indent and (lines[i].lstrip().startswith('def ') or lines[i].lstrip().startswith('class ')):
            method_end = i
            break
    if method_end is None:
        method_end = len(lines)
    
    # Step 6: Extract the method lines and modify to add the call to helper
    method_lines = lines[new_insert_idx:method_end]
    new_method_lines = []
    
    for line in method_lines:
        if line.rstrip() == 'return replacements':
            # Insert the call block before this line
            line_indent = len(line) - len(line.lstrip())
            new_method_lines.append(' ' * line_indent + '# ----------------------------------\n')
            new_method_lines.append(' ' * line_indent + '# Replenish waiting list from universe for each replacement used\n')
            new_method_lines.append(' ' * line_indent + '# ----------------------------------\n')
            new_method_lines.append(' ' * line_indent + f'self._replenish_waitlist_from_universe(len(replacements))\n')
            new_method_lines.append(line)  # Keep the return line
        else:
            new_method_lines.append(line)
    
    # Step 7: Replace the method lines
    lines[new_insert_idx:method_end] = new_method_lines
    
    # Step 8: Write back to file
    with open(file_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    
    print("SUCCESS: Updated trading_loop_dynamic.py with waiting list replenishment logic.")
    return 0

if __name__ == '__main__':
    sys.exit(main())