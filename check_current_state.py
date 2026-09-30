import sys
import os

trading_loop_path = r'C:\Users\Zamuxolo\RAATS_Test\src\agents\trading_loop_dynamic.py'
with open(trading_loop_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print("=== Checking _get_discovery_components method ===")
for i, line in enumerate(lines):
    if '_get_discovery_components' in line and 'def' in line:
        print(f"Line {i+1}: {line.rstrip()}")
        for j in range(i, min(i+10, len(lines))):
            print(f"  {j+1}: {lines[j].rstrip()}")
        break

print("\n=== Checking _generate_dynamic_universe method ===")
for i, line in enumerate(lines):
    if '_generate_dynamic_universe' in line and 'def' in line:
        print(f"Line {i+1}: {line.rstrip()}")
        for j in range(i, min(i+15, len(lines))):
            print(f"  {j+1}: {lines[j].rstrip()}")
        break

print("\n=== Checking pre_market_scan for empty universe handling ===")
for i, line in enumerate(lines):
    if 'pre_market_scan' in line and 'def' in line:
        print(f"Line {i+1}: {line.rstrip()}")
        for j in range(i, min(i+30, len(lines))):
            print(f"  {j+1}: {lines[j].rstrip()}")
        break