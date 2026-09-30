import sys
import os

trading_loop_path = r'C:\Users\Zamuxolo\RAATS_Test\src\agents\trading_loop_dynamic.py'
with open(trading_loop_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print("=== Checking _get_discovery_components method ===")
for i, line in enumerate(lines):
    if '_get_discovery_components' in line and 'def' in line:
        print(f"Line {i+1}: {line.rstrip()}")
        # Print the next 5 lines
        for j in range(i, min(i+6, len(lines))):
            print(f"  {j+1}: {lines[j].rstrip()}")
        break

print("\n=== Checking _generate_dynamic_universe method ===")
for i, line in enumerate(lines):
    if '_generate_dynamic_universe' in line and 'def' in line:
        print(f"Line {i+1}: {line.rstrip()}")
        # Print the next 10 lines
        for j in range(i, min(i+12, len(lines))):
            print(f"  {j+1}: {lines[j].rstrip()}")
        break

print("\n=== Checking for static fallback in _generate_dynamic_universe ===")
for i, line in enumerate(lines):
    if '_generate_dynamic_universe' in line and 'def' in line:
        # Look for the fallback in the next 20 lines
        for j in range(i, min(i+20, len(lines))):
            if 'tickers = [\"AAPL\", \"MSFT\", \"GOOGL\", \"AMZN\", \"TSLA\"]' in lines[j]:
                print(f"Found static fallback at line {j+1}: {lines[j].rstrip()}")
        break

print("\n=== Checking for warning message ===")
for i, line in enumerate(lines):
    if 'WARNING: Dynamic universe generation returned empty list' in line:
        print(f"Found warning at line {i+1}: {line.rstrip()}")

print("\n=== Checking for empty returns ===")
for i, line in enumerate(lines):
    if 'self._last_universe = []' in line:
        print(f"Found self._last_universe = [] at line {i+1}: {line.rstrip()}")
    if 'self._last_random_list = []' in line:
        print(f"Found self._last_random_list = [] at line {i+1}: {line.rstrip()}")
    if 'return []' in line and 'self._last_universe' not in line and 'self._last_random_list' not in line:
        print(f"Found return [] at line {i+1}: {line.rstrip()}")