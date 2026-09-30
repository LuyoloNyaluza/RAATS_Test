import sys
import os

trading_loop_path = r'C:\Users\Zamuxolo\RAATS_Test\src\agents\trading_loop_dynamic.py'
with open(trading_loop_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the __main__ block
in_main = False
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped.startswith('if __name__ == "__main__":'):
        in_main = True
        print(f"Start of __main__ block at line {i+1}: {line.rstrip()}")
        continue
    if in_main:
        # If we hit a line that is not indented (i.e., starts with non-whitespace) and is not empty, we are out of the block.
        if stripped and not (line.startswith(' ') or line.startswith('\t')):
            print(f"End of __main__ block at line {i} (previous line was {i})")
            break
        # Print the line number and content
        print(f"{i+1:4}: {line.rstrip()}")