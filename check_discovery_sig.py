with open(r'C:\Users\Zamuxolo\RAATS_Test\src\data\discovery.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
for i, line in enumerate(lines):
    if 'def get_discovery_components' in line:
        print(f"Line {i+1}: {line.rstrip()}")
        # Print the next 2 lines
        for j in range(i+1, min(i+3, len(lines))):
            print(f"  Line {j+1}: {lines[j].rstrip()}")
        break