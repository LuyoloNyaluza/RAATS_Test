import json
import os

notebook_path = r'C:\Users\Zamuxolo\RAATS_Test\notebooks\15_baseline_backtest.ipynb'

def main():
    with open(notebook_path, 'r', encoding='utf-8') as f:
        nb = json.load(f)
    
    # Fix imports: replace zipline.api import and add specific imports for slippage/commission
    for cell in nb['cells']:
        if cell.get('cell_type') == 'code':
            source = cell.get('source', [])
            joined = ''.join(source)
            if 'from zipline.api import order_target, symbol, set_slippage, set_commission, slippage, commission' in joined:
                new_source = []
                for line in source:
                    if line.strip().startswith('from zipline.api import'):
                        new_source.append('from zipline.api import order_target, symbol, set_slippage, set_commission\n')
                        new_source.append('from zipline.fixers.slippage import FixedSlippage\n')
                        new_source.append('from zipline.fixers.commission import PerShare\n')
                    else:
                        new_source.append(line)
                cell['source'] = new_source
                break
    
    # Fix usage lines: set_slippage(slippage.FixedSlippage(...) -> set_slippage(FixedSlippage(...)
    # set_commission(commission.PerShare(...) -> set_commission(PerShare(...)
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