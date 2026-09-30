with open(r'C:\Users\Zamuxolo\RAATS_Test\src\agents\trading_loop_dynamic.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'get_discovery_components' in line:
        print(f"{i+1}: {line.rstrip()}")