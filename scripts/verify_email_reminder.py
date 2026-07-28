#!/usr/bin/env python3
"""
Verification script for send_reminder.py.
Checks syntax and that the send_reminder function can be called
without actually sending an email (by mocking the SMTP connection).
"""

import sys
import os
import importlib.util
from unittest.mock import patch, MagicMock

# Path to the script we want to verify
SCRIPT_PATH = os.path.join(os.path.dirname(__file__), 'send_reminder.py')

def load_module():
    """Load the send_reminder module from its file."""
    spec = importlib.util.spec_from_file_location("send_reminder", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    # Avoid executing the module's main block when imported
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

def test_syntax():
    """Check that the script can be parsed by ast."""
    import ast
    with open(SCRIPT_PATH, 'r', encoding='utf-8') as f:
        source = f.read()
    try:
        ast.parse(source)
        print("✓ Syntax check passed")
        return True
    except SyntaxError as e:
        print(f"✗ Syntax error: {e}")
        return False

def test_import():
    """Try to import the module and ensure send_reminder exists."""
    try:
        module = load_module()
        if hasattr(module, 'send_reminder') and callable(module.send_reminder):
            print("✓ Import and function check passed")
            return module
        else:
            print("✗ send_reminder function missing or not callable")
            return None
    except Exception as e:
        print(f"✗ Failed to import module: {e}")
        return None

def test_function_call(mod):
    """Call send_reminder with mocked SMTP to avoid network."""
    # Mock the SMTP_SSL class used in the script
    with patch('smtplib.SMTP_SSL') as mock_smtp_ssl:
        # Configure the mock to behave like a context manager
        mock_instance = MagicMock()
        mock_smtp_ssl.return_value.__enter__.return_value = mock_instance
        mock_smtp_ssl.return_value.__exit__.return_value = False
        try:
            mod.send_reminder()
            print("✓ send_reminder executed without error (SMTP mocked)")
            # Optionally assert that login and send_message were called
            mock_instance.login.assert_called_once()
            mock_instance.send_message.assert_called_once()
            return True
        except Exception as e:
            print(f"✗ send_reminder raised an exception: {e}")
            return False

def main():
    print("=== Verifying send_reminder.py ===")
    if not test_syntax():
        sys.exit(1)
    module = test_import()
    if module is None:
        sys.exit(1)
    if not test_function_call(module):
        sys.exit(1)
    print("All verification checks passed.")

if __name__ == '__main__':
    main()