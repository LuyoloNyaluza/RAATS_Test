import sys
import os

# Paths
trading_loop_path = r'C:\Users\Zamuxolo\RAATS_Test\src\agents\trading_loop_dynamic.py'

# Read the file
with open(trading_loop_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 1. Change the function signature of run_dynamic_trading_session
# Find the line that starts with 'def run_dynamic_trading_session'
for i, line in enumerate(lines):
    if line.strip().startswith('def run_dynamic_trading_session'):
        # We'll replace the line and possibly the following lines until the closing parenthesis
        # Let's find the end of the function signature (the line that has the closing ')')
        j = i
        while j < len(lines) and ')' not in lines[j]:
            j += 1
        if j < len(lines):
            # Now replace lines[i:j+1] with the new signature
            new_signature = 'def run_dynamic_trading_session(\n    ticker_universe: Optional[List[str]],\n    simulate_date: Optional[str] = None,\n    max_active_positions: int = 10,\n    waitlist_size: int = 10,\n    max_articles_per_ticker: int = 5,\n    total_article_cap: Optional[int] = 50,\n    sentiment_model: str = \"mistral\",\n    news_fetch_pause: float = 0.5,\n    portfolio_value: float = 10_000,\n    analyst_model: Optional[str] = None\n) -> Dict[str, Any]:\n'
            # We need to keep the indentation level; the original line had no indent (it's at the class level? Actually it's a function outside the class? Let's check.
            # Looking at the original file, run_dynamic_trading_session is a function outside the class, so it has no indent (or 0 indent).
            # We'll keep the same indentation as the original line.
            indent = len(line) - len(line.lstrip())
            new_signature = ' ' * indent + new_signature
            lines[i:j+1] = [new_signature]
        break

# 2. Change _get_discovery_components to call get_discovery_components with open_positions and remove filtering
# Find the function _get_discovery_components
for i, line in enumerate(lines):
    if line.strip().startswith('def _get_discovery_components'):
        # We'll replace from this line to the end of the function.
        # Find the end of the function (next line that starts with 'def ' at same indent level or end of file)
        j = i + 1
        while j < len(lines):
            # Check if this line is a new function at the same indent level as the current function's def line
            if lines[j].strip().startswith('def ') and (len(lines[j]) - len(lines[j].lstrip())) == (len(lines[i]) - len(lines[i].lstrip())):
                break
            j += 1
        # Now replace lines[i:j] with the new method
        # Get the original indentation of the def line
        indent = len(lines[i]) - len(lines[i].lstrip())
        new_method = [
            '    def _get_discovery_components(self) -> dict:\n',
            '        \"\"\"Get discovery components using the new discovery layer approach.\"\"\"\n',
            '        # Get current open positions to exclude from consideration\n',
            '        open_positions = set(self.risk_manager.positions.keys())\n',
            '        \n',
            '        # Get the discovery components from the new discovery layer\n',
            '        # Pass open_positions so discovery layer can handle exclusion internally\n',
            '        candidate_universe, random_list, auxiliary = get_discovery_components(open_positions=open_positions)\n',
            '        \n',
            '        return {\n',
            '            \'candidates\': candidate_universe,\n',
            '            \'random_list\': random_list,\n',
            '            \'auxiliary\': auxiliary\n',
            '        }\n'
        ]
        # Apply indentation
        new_method = [(' ' * indent) + line if not line.startswith(' ') else line for line in new_method]
        lines[i:j] = new_method
        break

# 3. Change _generate_dynamic_universe to not fall back to static list
# Find the function _generate_dynamic_universe
for i, line in enumerate(lines):
    if line.strip().startswith('def _generate_dynamic_universe'):
        # We'll replace from this line to the end of the function.
        j = i + 1
        while j < len(lines):
            if lines[j].strip().startswith('def ') and (len(lines[j]) - len(lines[j].lstrip())) == (len(lines[i]) - len(lines[i].lstrip())):
                break
            j += 1
        # Now we need to find the specific block we want to change: the else block that handles when tickers is empty.
        # Let's instead replace the whole function with a corrected version.
        # We'll keep the function signature and the initial part until the else block.
        # But for simplicity, let's just replace the else block.
        # We'll look for the line: 'if not tickers:'
        for k in range(i, j):
            if lines[k].strip().startswith('if not tickers:'):
                # We found the if block. We'll replace from this line to the end of the if block (until the line that is not indented more than this if line)
                # Determine the indent of this if line
                if_indent = len(lines[k]) - len(lines[k].lstrip())
                # Find the end of the if block: the next line that has indent <= if_indent and is not empty
                l = k + 1
                while l < j:
                    if lines[l].strip() == '':
                        l += 1
                        continue
                    if len(lines[l]) - len(lines[l].lstrip()) <= if_indent:
                        break
                    l += 1
                # Now replace lines[k:l] with the new block
                new_block = [
                    '            if not tickers:\n',
                    '                print(\"WARNING: Dynamic universe generation returned empty list. No candidates for this session.\")\n',
                    '                # Do not fall back to static list; keep empty to signal no candidates.\n',
                    '                self._last_universe = []\n',
                    '                self._last_random_list = []\n',
                    '                return [], [], {}\n'
                ]
                # Apply the same indent as the if line (which is 12 spaces? we'll keep the indent of the if line)
                # Actually, the if line is inside the function, so we keep its indentation.
                # We'll just use the lines as we wrote them (they have 12 spaces? we'll keep the indent we found in the original if line)
                # But we wrote new_block with 12 spaces? Let's just use the indent from the original if line.
                orig_if_indent = len(lines[k]) - len(lines[k].lstrip())
                new_block = [(' ' * orig_if_indent) + l if not l.startswith(' ') else l for l in new_block]
                lines[k:l] = new_block
                break
        break

# 4. Change the demo call in __main__ block to use ticker_universe=None
# Find the __main__ block
for i, line in enumerate(lines):
    if line.strip().startswith('if __name__ == \"__main__\":'):
        # Now look for the line with 'run_dynamic_trading_session' and 'ticker_universe=demo_universe'
        for j in range(i, len(lines)):
            if 'run_dynamic_trading_session' in lines[j] and 'ticker_universe=demo_universe' in lines[j]:
                # Replace that line
                # We want to keep the same indentation and change the argument.
                # We'll replace the whole line with a new one that has ticker_universe=None
                # But we want to keep the comment if possible.
                # Let's just replace the line with: '            session = run_dynamic_trading_session(\n                ticker_universe=None, # use dynamic discovery\n                ...'
                # However, it's easier to replace the specific part.
                # We'll do a simple string replacement on the line.
                lines[j] = lines[j].replace('ticker_universe=demo_universe', 'ticker_universe=None')
                # Also update the comment if we want, but we can leave it.
                # Optionally, we can change the comment to indicate dynamic discovery.
                # Let's just change the comment after the None to say '# use dynamic discovery'
                # Find the comment part
                if '# use the demo universe to test fixed mode' in lines[j]:
                    lines[j] = lines[j].replace('# use the demo universe to test fixed mode', '# use dynamic discovery')
                break
        break

# Write back the file
with open(trading_loop_path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Modified trading_loop_dynamic.py")