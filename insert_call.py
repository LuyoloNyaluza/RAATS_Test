import sys

def main():
    file_path = r'C:\Users\Zamuxolo\RAATS_Test\src\agents\trading_loop_dynamic.py'
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Find the _get_replacements method
    method_start = None
    for i in range(len(lines)-1):
        if 'def _get_replacements' in lines[i] and 'self,' in lines[i+1]:
            method_start = i
            break
    if method_start is None:
        for i, line in enumerate(lines):
            if 'def _get_replacements' in line:
                method_start = i
                break
    if method_start is None:
        print("ERROR: Could not find _get_replacements method")
        return 1
    
    # Find the end of the method
    indent = len(lines[method_start]) - len(lines[method_start].lstrip())
    method_end = None
    for i in range(method_start + 1, len(lines)):
        if len(lines[i]) - len(lines[i].lstrip()) == indent and (lines[i].lstrip().startswith('def ') or lines[i].lstrip().startswith('class ')):
            method_end = i
            break
    if method_end is None:
        method_end = len(lines)
    
    # Extract method lines
    method_lines = lines[method_start:method_end]
    # We'll insert the call before the final 'return replacements' line.
    new_method_lines = []
    for line in method_lines:
        if line.rstrip() == 'return replacements':
            line_indent = len(line) - len(line.lstrip())
            # Insert the call block
            new_method_lines.append(' ' * line_indent + '# ----------------------------------\n')
            new_method_lines.append(' ' * line_indent + '# Replenish waiting list from universe for each replacement used\n')
            new_method_lines.append(' ' * line_indent + '# ----------------------------------\n')
            new_method_lines.append(' ' * line_indent + f'self._replenish_waitlist_from_universe(len(replacements))\n')
            new_method_lines.append(line)  # keep the return line
        else:
            new_method_lines.append(line)
    
    # Replace the method lines
    lines[method_start:method_end] = new_method_lines
    
    # Write back
    with open(file_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    
    print("SUCCESS: Added call to helper in _get_replacements.")
    return 0

if __name__ == '__main__':
    sys.exit(main())