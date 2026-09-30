import re
with open(r'C:\Users\Zamuxolo\RAATS_Test\src\agents\trading_loop_dynamic.py', 'r', encoding='utf-8') as f:
    content = f.read()
pattern = r'def _get_discovery_components\s*\(self\s*\)\s*(-\s*>.*?\s*)?:'
match = re.search(pattern, content)
print('Match:', match)
if match:
    print('Match start:', match.start())
    print('Match end:', match.end())
    print('Matched string:', repr(content[match.start():match.end()]))
else:
    print('No match')
    # Let's try a simpler pattern
    pattern2 = r'def _get_discovery_components\s*\(self\):'
    match2 = re.search(pattern2, content)
    print('Match2:', match2)
    if match2:
        print('Match2 start:', match2.start())
        print('Match2 end:', match2.end())
        print('Matched string2:', repr(content[match2.start():match2.end()]))