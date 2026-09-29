import os
import sys

def main():
    errors = []
    base_path = r'C:\Users\Zamuxolo\RAATS_Test'
    trading_loop_path = os.path.join(base_path, 'src', 'agents', 'trading_loop_dynamic.py')
    discovery_path = os.path.join(base_path, 'src', 'data', 'discovery.py')
    
    # Read files
    with open(trading_loop_path, 'r', encoding='utf-8') as f:
        tl = f.read()
    with open(discovery_path, 'r', encoding='utf-8') as f:
        disc = f.read()
    
    # 1. Check run_dynamic_trading_session signature
    if 'def run_dynamic_trading_session(' not in tl:
        errors.append("run_dynamic_trading_session function not found")
    else:
        # Look for the parameter with annotation
        # We'll just check that the string 'ticker_universe: Optional[List[str]]' appears in the function definition area.
        # We'll get the lines of the function definition (first few lines after the def)
        lines = tl.splitlines()
        in_signature = False
        signature_lines = []
        for line in lines:
            if line.strip().startswith('def run_dynamic_trading_session'):
                in_signature = True
            if in_signature:
                signature_lines.append(line)
                if line.strip().endswith(':'):
                    break
        signature = ' '.join(signature_lines)
        if 'ticker_universe: Optional[List[str]]' not in signature:
            errors.append("run_dynamic_trading_session missing ticker_universe: Optional[List[str]] in signature")
    
    # 2. Check __main__ block for ticker_universe=None
    main_start = tl.find('if __name__ == "__main__":')
    if main_start == -1:
        errors.append("__main__ block not found")
    else:
        main_block = tl[main_start:main_start+2000]  # should be enough
        if 'run_dynamic_trading_session' not in main_block:
            errors.append("__main__ block does not call run_dynamic_trading_session")
        elif 'ticker_universe=None' not in main_block:
            errors.append("__main__ block does not call run_dynamic_trading_session with ticker_universe=None")
    
    # 3. Check _get_discovery_components calls get_discovery_components with open_positions
    # We'll look for the function _get_discovery_components and then see if the call is present in its vicinity.
    func_start = tl.find('def _get_discovery_components(self)')
    if func_start == -1:
        errors.append("_get_discovery_components function not found")
    else:
        # Look at a window of 2000 characters after the function start
        window = tl[func_start:func_start+2000]
        if 'get_discovery_components(open_positions=open_positions)' not in window:
            errors.append("_get_discovery_components does not call get_discovery_components with open_positions in the expected location")
    
    # 4. Check _generate_dynamic_universe for static fallback and proper empty handling
    gen_start = tl.find('def _generate_dynamic_universe')
    if gen_start == -1:
        errors.append("_generate_dynamic_universe function not found")
    else:
        window = tl[gen_start:gen_start+2000]
        # Check for static fallback
        if 'tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]' in window:
            errors.append("_generate_dynamic_universe still contains static fallback")
        # Check for warning
        if 'WARNING: Dynamic universe generation returned empty list. No candidates for this session.' not in window:
            errors.append("_generate_dynamic_universe missing warning for empty universe")
        # Check that we set _last_universe and _last_random_list to [] in the empty case
        # We'll look for the if not tickers: block
        if 'if not tickers:' not in window:
            errors.append("_generate_dynamic_universe missing 'if not tickers:' check")
        # We'll also check that we set the attributes to [] (we can do a simple presence check in the window)
        if 'self._last_universe = []' not in window:
            errors.append("_generate_dynamic_universe missing setting _last_universe to []")
        if 'self._last_random_list = []' not in window:
            errors.append("_generate_dynamic_universe missing setting _last_random_list to []")
        # We expect that in the empty case, we return [] (via return self._last_universe which is now [])
        # Since we return self._last_universe, we don't need to check for a return statement.
    
    # 5. Check pre_market_scan calls _generate_dynamic_universe and handles empty universe
    pre_start = tl.find('def pre_market_scan')
    if pre_start == -1:
        errors.append("pre_market_scan function not found")
    else:
        window = tl[pre_start:pre_start+2000]
        if 'tickers = self._generate_dynamic_universe()' not in window:
            errors.append("pre_market_scan does not call _generate_dynamic_universe")
        if 'if not tickers:' not in window:
            errors.append("pre_market_scan missing 'if not tickers:' check")
        warn = "WARNING: Dynamic universe generation returned empty list. No candidates for this session."
        if warn not in window:
            errors.append("pre_market_scan missing warning for empty universe")
        if 'self.active_list = []' not in window:
            errors.append("pre_market_scan does not set active_list to empty after warning")
        if 'self.waitlist = []' not in window:
            errors.append("pre_market_scan does not set waitlist to empty after warning")
        # Check that we return (function returns None, so we expect a return statement)
        # We'll just check that there is a return statement in the window (not strictly necessary but good)
        if 'return' not in window:
            errors.append("pre_market_scan missing return statement")
    
    # 6. Check discovery layer signature includes open_positions
    disc_start = disc.find('def get_discovery_components')
    if disc_start == -1:
        errors.append("get_discovery_components function not found in discovery.py")
    else:
        window = disc[disc_start:disc_start+2000]
        if 'open_positions: set[str] | None = None,' not in window:
            errors.append("get_discovery_components signature missing open_positions parameter")
    
    # Output
    if errors:
        print("❌ VERIFICATION FAILED")
        for err in errors:
            print(f"  - {err}")
        return 1
    else:
        print("✅ VERIFICATION PASSED")
        print("All required changes are present in the source files.")
        return 0

if __name__ == "__main__":
    sys.exit(main())