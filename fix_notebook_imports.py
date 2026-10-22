import json
import os

notebook_path = r'C:\Users\Zamuxolo\RAATS_Test\notebooks\14_backtest_intro.ipynb'

def main():
    with open(notebook_path, 'r', encoding='utf-8') as f:
        nb = json.load(f)
    
    # Find the code cell with imports (likely second cell)
    for cell in nb['cells']:
        if cell.get('cell_type') == 'code':
            source = cell.get('source', [])
            # Join source lines to check
            joined = ''.join(source)
            if 'from zipline.api import' in joined and 'slippage' in joined and 'commission' in joined:
                # Replace the import line
                new_source = []
                for line in source:
                    if line.strip().startswith('from zipline.api import'):
                        # Replace this line with the new imports
                        new_source.append('from zipline.api import order_target, symbol, set_slippage, set_commission\n')
                        new_source.append('from zipline.fixers.slippage import FixedSlippage\n')
                        new_source.append('from zipline.fixers.commission import PerShare\n')
                    else:
                        new_source.append(line)
                cell['source'] = new_source
                break
    
    # Also need to replace the usage lines: set_slippage(slippage.FixedSlippage(spread=0)) -> set_slippage(FixedSlippage(spread=0))
    # and set_commission(commission.PerShare(cost=0.005)) -> set_commission(PerShare(cost=0.005))
    for cell in nb['cells']:
        if cell.get('cell_type') == 'code':
            source = cell.get('source', [])
            new_source = []
            for line in source:
                if 'set_slippage(slippage.FixedSlippage' in line:
                    line = line.replace('set_slippage(slippage.FixedSlippage', 'set_slippage(FixedSlippage')
                if 'set_commission(commission.PerShare' in line:
                    line = line.replace('set_commission(commission.PerShare', 'set_commission(PerShare')
                new_source.append(line)
            cell['source'] = new_source
            break
    
    with open(notebook_path, 'w', encoding='utf-8') as f:
        json.dump(nb, f, indent=1)
    print(f'Updated {notebook_path}')

if __name__ == '__main__':
    main()