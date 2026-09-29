import sys
sys.path.insert(0, r'C:\Users\Zamuxolo\RAATS_Test')
with open(r'C:\Users\Zamuxolo\RAATS_Test\src\agents\trading_loop_dynamic.py', 'r', encoding='utf-8') as f:
    content = f.read()

func_start = content.find('def _get_discovery_components(self)')
print(f"Function start at index: {func_start}")
if func_start == -1:
    print("Function not found")
else:
    # Extract the function body until next def at same indent level
    lines = content[func_start:].splitlines(keepends=True)
    # Get the indent of the def line
    indent_line = lines[0]
    indent = len(indent_line) - len(indent_line.lstrip())
    print(f"Indent of def line: {indent}")
    func_lines = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('def ') and len(line) - len(line.lstrip()) == indent:
            print(f"Next def at line {i}: {line.rstrip()}")
            break
        func_lines.append(line)
    func_text = ''.join(func_lines)
    print("--- Function body ---")
    print(repr(func_text))
    print("--- End function body ---")
    # Now check for the call
    target = 'get_discovery_components(open_positions=open_positions)'
    if target in func_text:
        print(f"Found target: {target}")
    else:
        print(f"Target not found: {target}")
        # Let's see what is there
        # We'll look for get_discovery_components
        if 'get_discovery_components' in func_text:
            print("But get_discovery_components is present")
            # Show the line
            for i, line in enumerate(func_lines):
                if 'get_discovery_components' in line:
                    print(f"  Line {i}: {repr(line)}")
        else:
            print("get_discovery_components not found at all")