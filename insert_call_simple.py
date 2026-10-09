import sys

def main():
    file_path = r'C:\Users\Zamuxolo\RAATS_Test\src\agents\trading_loop_dynamic.py'
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # We know the line we want to insert before is at index 1227 (0-indexed) which is line 1228: '        return replacements'
    # But let's find it dynamically to be safe.
    target_line = '        return replacements'
    target_index = None
    for i, line in enumerate(lines):
        if line.rstrip() == target_line:
            target_index = i
            break
    
    if target_index is None:
        print("ERROR: Could not find the target line:", target_line)
        return 1
    
    # The indentation of the target line is 8 spaces (since it's inside the method)
    indent = len(lines[target_index]) - len(lines[target_index].lstrip())
    
    # Insert the call block before the target line.
    # We want to insert:
    #         # ----------------------------------
    #         # Replenish waiting list from universe for each replacement used
    #         # ----------------------------------
    #         self._replenish_waitlist_from_universe(len(replacements))
    insert_lines = [
        '        # ----------------------------------\n',
        '        # Replenish waiting list from universe for each replacement used\n',
        '        # ----------------------------------\n',
        f'        self._replenish_waitlist_from_universe(len(replacements))\n'
    ]
    
    # Insert at target_index
    lines[target_index:target_index] = insert_lines
    
    # Write back
    with open(file_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    
    print("SUCCESS: Inserted call to helper before return in _get_replacements.")
    return 0

if __name__ == '__main__':
    sys.exit(main())