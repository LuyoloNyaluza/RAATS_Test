"""
Tests for the broker symbol catalog (standard library only; no MT5 terminal needed).

    python test_broker_symbols.py     (from the folder holding broker_symbols.py, or the project
                                       root: it also tries src/data)
"""
import os
import sys
import tempfile

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "src", "data"))
os.environ["RAATS_BROKER_DIR"] = tempfile.mkdtemp()
os.environ.pop("RAATS_USE_MT5", None)
os.environ.pop("RAATS_BROKER_FILTER", None)
import broker_symbols as BS


def sym(name, path="Stocks\\US", mode=4):
    return {"name": name, "path": path, "description": "", "trade_mode": mode}


SYMBOLS = [
    sym("AAPL"), sym("TSLA_i"), sym("#GFS"), sym("MSFT.US"),
    sym("NVDA", mode=3),                                  # close-only: not tradable
    sym("EURUSD", "Forex\\Majors"), sym("XAUUSD", "Metals"),
    sym("CAT", "Forex\\Exotics"),                         # a non-share that shares a base name
    sym("VOD.L", "Stocks\\UK"), sym("VOD.US", "Stocks\\US"),
]
cat = BS.Catalog(SYMBOLS, "FBS-Real", "2026-11-10T08:00:00")

# 1. naming styles: exact, ".US" suffix, "_i" suffix, "#" prefix
assert cat.resolve("AAPL") == "AAPL"
assert cat.resolve("MSFT") == "MSFT.US"
assert cat.resolve("TSLA") == "TSLA_i"
assert cat.resolve("GFS") == "#GFS", "prefix style must resolve"
print("1. AAPL / MSFT.US / TSLA_i / #GFS all resolve")

# 2. a ticker the broker does not list is not offered (the ORKA case)
assert cat.resolve("ORKA") is None and not cat.has("ORKA")
print("2. a ticker the broker does not list is not offered")

# 3. only FULL trading counts; a share is never matched to a forex/metal symbol
assert cat.resolve("NVDA") is None, "close-only is not tradable"
assert cat.resolve("CAT") is None, "a Forex path must not match the stock ticker"
print("3. close-only symbols and non-share paths do not match")

# 4. two listings of one base: the US one wins
assert cat.resolve("VOD") == "VOD.US"
print("4. ambiguous base name prefers the US listing")

# 5. save to disk, then load the cache when MT5 is unreachable
BS._fetch_from_mt5 = lambda: cat
BS._STATE.update(catalog=None, loaded=0.0, next_try=0.0)
got = BS.get_catalog(refresh=True)
assert got is cat and any(f.name.startswith("symbols_FBS-Real") for f in BS._catalog_dir().glob("*.json"))
BS._fetch_from_mt5 = lambda: None                         # terminal down
BS._STATE.update(catalog=None, loaded=0.0, next_try=0.0)
cached = BS.get_catalog()
assert cached is not None and cached.resolve("GFS") == "#GFS" and len(cached) == len(cat)
print("5. the list is cached per server and reused when MT5 is unreachable")

# 6. fail OPEN: no MT5 and no cache -> no filtering
os.environ["RAATS_BROKER_DIR"] = tempfile.mkdtemp()
BS._STATE.update(catalog=None, loaded=0.0, next_try=0.0)
assert BS.get_catalog() is None and BS.accepts("ORKA") is True
print("6. no list available: accepts() fails open")

# 7. switches: paper mode and RAATS_BROKER_FILTER=0 turn the filter off
BS._fetch_from_mt5 = lambda: cat
BS._STATE.update(catalog=None, loaded=0.0, next_try=0.0)
assert BS.accepts("ORKA") is False
os.environ["RAATS_USE_MT5"] = "0"
assert BS.get_catalog() is None and BS.accepts("ORKA") is True
os.environ.pop("RAATS_USE_MT5")
os.environ["RAATS_BROKER_FILTER"] = "0"
assert BS.get_catalog() is None and BS.accepts("ORKA") is True
os.environ.pop("RAATS_BROKER_FILTER")
print("7. paper mode / RAATS_BROKER_FILTER=0 switch the catalog off")

# 8. the catalog never raises
BS._STATE.update(catalog=None, loaded=0.0, next_try=0.0)
BS._fetch_from_mt5 = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
try:
    ok = BS.accepts("AAPL")
except Exception as exc:
    raise AssertionError(f"accepts must never raise: {exc}")
print("8. errors never raise")

# 9. a running session notices that the terminal moved to another broker
other = BS.Catalog([sym("ORKA"), sym("AAPL")], "OtherBroker-Live", "2026-11-10T09:00:00")
BS._fetch_from_mt5 = lambda: cat
BS._STATE.update(catalog=None, loaded=0.0, next_try=0.0, server_checked=0.0)
BS._max_age_hours = lambda: 1e9                             # the cached list itself is not stale
assert BS.get_catalog(refresh=True) is cat and BS.current_server() == "FBS-Real"
BS._fetch_from_mt5 = lambda: other
BS._read_server = lambda: "OtherBroker-Live"
assert BS.get_catalog() is cat, "within 5 minutes the cached list is reused"
BS._STATE["server_checked"] = 0.0                           # 5 minutes later
got = BS.get_catalog()
assert got is other and BS.current_server() == "OtherBroker-Live" and BS.accepts("ORKA") is True
print("9. a running session picks up a broker switch (checked every 5 minutes)")

print("ALL BROKER SYMBOL TESTS PASSED")
