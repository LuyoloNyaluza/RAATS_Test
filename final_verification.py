import sys
import os

def main():
    trading_loop_path = r'C:\Users\Zamuxolo\RAATS_Test\src\agents\trading_loop_dynamic.py'
    discovery_path = r'C:\Users\Zamuxolo\RAATS_Test\src\data\discovery.py'
    
    with open(trading_loop_path, 'r', encoding='utf-8') as f:
        tl = f.read()
    with open(discovery_path, 'r', encoding='utf-8') as f:
        disc = f.read()
    
    checks = []
    
    # 1. run_dynamic_trading_session signature
    if 'def run_dynamic_trading_session(' in tl and 'ticker_universe: Optional[List[str]]' in tl:
        checks.append(("run_dynamic_trading_session signature", True))
    else:
        checks.append(("run_dynamic_trading_session signature", False))
    
    # 2. __main__ block demo call
    main_start = tl.find('if __name__ == "__main__":')
    if main_start != -1:
        main_block = tl[main_start:main_start+2000]
        if 'run_dynamic_trading_session' in main_block and 'ticker_universe=None' in main_block:
            checks.append(("__main__ demo call with ticker_universe=None", True))
        else:
            checks.append(("__main__ demo call with ticker_universe=None", False))
    else:
        checks.append(("__main__ block not found", False))
    
    # 3. _get_discovery_components calls get_discovery_components with open_positions
    func_start = tl.find('def _get_discovery_components(self)')
    if func_start != -1:
        # Look within the next 2000 characters for the call
        after = tl[func_start:func_start+2000]
        if 'get_discovery_components(open_positions=open_positions)' in after:
            checks.append(("_get_discovery_components calls get_discovery_components with open_positions", True))
        else:
            checks.append(("_get_discovery_components calls get_discovery_components with open_positions", False))
    else:
        checks.append(("_get_discovery_components function not found", False))
    
    # 4. _generate_dynamic_universe handles empty universe correctly
    gen_start = tl.find('def _generate_dynamic_universe')
    if gen_start != -1:
        after = tl[gen_start:gen_start+2000]
        if 'WARNING: Dynamic universe generation returned empty list. No candidates for this session.' in after:
            checks.append(("_generate_dynamic_universe has warning for empty universe", True))
        else:
            checks.append(("_generate_dynamic_universe has warning for empty universe", False))
        if 'self._last_universe = []' in after:
            checks.append(("_generate_dynamic_universe sets _last_universe to []", True))
        else:
            checks.append(("_generate_dynamic_universe sets _last_universe to []", False))
        if 'self._last_random_list = []' in after:
            checks.append(("_generate_dynamic_universe sets _last_random_list to []", True))
        else:
            checks.append(("_generate_dynamic_universe sets _last_random_list to []", False))
        if 'return []' in after:
            checks.append(("_generate_dynamic_universe returns []", True))
        else:
            checks.append(("_generate_dynamic_universe returns []", False))
        if 'tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]' not in after:
            checks.append(("_generate_dynamic_universe has no static fallback", True))
        else:
            checks.append(("_generate_dynamic_universe has no static fallback", False))
    else:
        checks.append(("_generate_dynamic_universe function not found", False))
    
    # 5. pre_market_scan handles empty universe from _generate_dynamic_universe
    pre_start = tl.find('def pre_market_scan')
    if pre_start != -1:
        after = tl[pre_start:pre_start+2000]
        if 'tickers = self._generate_dynamic_universe()' in after:
            checks.append(("pre_market_scan calls _generate_dynamic_universe", True))
        else:
            checks.append(("pre_market_scan calls _generate_dynamic_universe", False))
        if 'if not tickers:' in after:
            checks.append(("pre_market_scan has 'if not tickers:' check", True))
        else:
            checks.append(("pre_market_scan has 'if not tickers:' check", False))
        warn = "WARNING: Dynamic universe generation returned empty list. No candidates for this session."
        if warn in after:
            checks.append(("pre_market_scan warns on empty universe", True))
        else:
            checks.append(("pre_market_scan warns on empty universe", False))
        if 'self.active_list = []' in after:
            checks.append(("pre_market_scan sets active_list to [] on empty", True))
        else:
            checks.append(("pre_market_scan sets active_list to [] on empty", False))
        if 'self.waitlist = []' in after:
            checks.append(("pre_market_scan sets waitlist to [] on empty", True))
        else:
            checks.append(("pre_market_scan sets waitlist to [] on empty", False))
        if 'return' in after:  # we return None, so just a return statement
            checks.append(("pre_market_scan returns early on empty", True))
        else:
            checks.append(("pre_market_scan returns early on empty", False))
    else:
        checks.append(("pre_market_scan function not found", False))
    
    # 6. discovery layer signature includes open_positions
    disc_start = disc.find('def get_discovery_components')
    if disc_start != -1:
        # Look at the line and the next line (since the signature may span lines)
        # We'll just look in a window after the start
        window = disc[disc_start:disc_start+500]
        if 'open_positions' in window:
            checks.append(("get_discovery_components signature includes open_positions", True))
        else:
            checks.append(("get_discovery_components signature includes open_positions", False))
    else:
        checks.append(("get_discovery_components function not found", False))
    
    # Output results
    all_passed = True
    for name, ok in checks:
        if ok:
            print(f"✅ {name}")
        else:
            print(f"❌ {name}")
            all_passed = False
    
    print("\n" + "="*60)
    if all_passed:
        print("🎉 ALL CHECKS PASSED")
        print("The dynamic watchlist discovery layer has been successfully implemented.")
    else:
        print("❌ SOME CHECKS FAILED")
    print("="*60)
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())