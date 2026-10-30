"""
src/data/reserve_tickers.py

One-time reserve of extra candidates for a session that has run out of tickers.

When the top 50 and the waiting list are exhausted and fewer than 5 tickers reached the
final INVEST list, the trading loop adds up to 30 reserve tickers:

    10 from  https://finance.yahoo.com/markets/stocks/trending/
    10 from  https://finance.yahoo.com/markets/world-indices/
    10 from  https://finance.yahoo.com/markets/stocks/most-active/

Duplicates are removed across the three sources AND against every ticker the session
already knows (top 50, waiting list, active, tested, rejected, final INVEST). A symbol that
is already taken is skipped and the next one on that page is used, so each source still
contributes up to 10 DISTINCT new tickers. The result is interleaved
(trending, index, most active, trending, ...) so the first batch drawn into the top 10 mixes
all three sources.

How each list is fetched (the first method that works):

    trending       page table  ->  Yahoo trending API
    world indices  page table  ->  built-in list of the major world indices
    most active    page table  ->  yfinance screener "most_actives"

The page tables are read from Yahoo's HTML, which Yahoo can change at any time; the fallbacks
keep the reserve working when that happens. Run

    python -m src.data.reserve_tickers

to see what each source returned, and which method was used.
"""

import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote

import requests

TRENDING_URL = "https://finance.yahoo.com/markets/stocks/trending/"
WORLD_INDICES_URL = "https://finance.yahoo.com/markets/world-indices/"
MOST_ACTIVE_URL = "https://finance.yahoo.com/markets/stocks/most-active/"
TRENDING_API_URL = "https://query1.finance.yahoo.com/v1/finance/trending/US"

PER_SOURCE = 10          # tickers taken from each source
FETCH_COUNT = 40         # fetch more than 10 so duplicates can be skipped

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Used only when the world-indices page cannot be read.
WORLD_INDICES_FALLBACK: List[str] = [
    "^GSPC", "^DJI", "^IXIC", "^RUT", "^GSPTSE", "^BVSP", "^MXX",       # Americas
    "^FTSE", "^GDAXI", "^FCHI", "^STOXX50E", "^N100", "^IBEX", "^AEX",   # Europe
    "^N225", "^HSI", "000001.SS", "^BSESN", "^NSEI", "^AXJO", "^KS11",   # Asia-Pacific
    "^TWII", "^STI", "^JKSE", "^NZ50",
]

_SYMBOL_RE = re.compile(r"^\^?[A-Z0-9]{1,12}(?:[.\-=][A-Z0-9]{1,6})?$")
_TABLE_RE = re.compile(r"<table\b.*?</table>", re.I | re.S)
_HREF_RE = re.compile(r"""href=["'](?:https?://finance\.yahoo\.com)?/quote/([^/"'?#]+)""", re.I)


# ---------------------------------------------------------------- helpers
def normalize(symbol: Any) -> str:
    """'%5EGSPC' / ' aapl ' -> '^GSPC' / 'AAPL'."""
    return unquote(str(symbol)).strip().upper()


def valid_symbol(symbol: str) -> bool:
    return bool(_SYMBOL_RE.match(symbol))


def _ordered_unique(items: Iterable[str]) -> List[str]:
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def parse_symbols_from_html(html: str) -> List[str]:
    """Symbols linked inside the page's <table>(s), in page order.

    Only table cells are read: every Yahoo page also carries a header strip of market
    links (^GSPC, ^DJI, ...) that must not be mistaken for the list itself.
    """
    tables = _TABLE_RE.findall(html or "")
    text = "\n".join(tables)
    symbols = (normalize(m) for m in _HREF_RE.findall(text))
    return _ordered_unique(s for s in symbols if valid_symbol(s))


def _http_get(url: str, **kwargs: Any) -> requests.Response:
    resp = requests.get(url, headers=HEADERS, timeout=15, **kwargs)
    resp.raise_for_status()
    return resp


def _page_symbols(url: str) -> List[str]:
    try:
        return parse_symbols_from_html(_http_get(url).text)
    except Exception:
        return []


# ---------------------------------------------------------------- sources
def fetch_trending(count: int = FETCH_COUNT) -> Tuple[List[str], str]:
    page = _page_symbols(TRENDING_URL)
    if len(page) >= PER_SOURCE:
        return page[:count], "page"
    try:
        data = _http_get(TRENDING_API_URL, params={"count": count, "lang": "en-US"}).json()
        quotes = data["finance"]["result"][0]["quotes"]
        api = _ordered_unique(s for s in (normalize(q.get("symbol", "")) for q in quotes) if valid_symbol(s))
        if api:
            return api[:count], "api"
    except Exception:
        pass
    return [], "none"


def fetch_world_indices(count: int = FETCH_COUNT) -> Tuple[List[str], str]:
    page = _page_symbols(WORLD_INDICES_URL)
    if len(page) >= PER_SOURCE:
        return page[:count], "page"
    return list(WORLD_INDICES_FALLBACK[:count]), "built-in list"


def fetch_most_active(count: int = FETCH_COUNT) -> Tuple[List[str], str]:
    page = _page_symbols(MOST_ACTIVE_URL)
    if len(page) >= PER_SOURCE:
        return page[:count], "page"
    try:
        import yfinance as yf
        quotes = yf.screen("most_actives", count=count).get("quotes", [])
        screen = _ordered_unique(s for s in (normalize(q.get("symbol", "")) for q in quotes) if valid_symbol(s))
        if screen:
            return screen[:count], "screener"
    except Exception:
        pass
    return [], "none"


SOURCES: List[Tuple[str, Callable[[], Tuple[List[str], str]]]] = [
    ("trending", fetch_trending),
    ("world_indices", fetch_world_indices),
    ("most_active", fetch_most_active),
]


# ---------------------------------------------------------------- main entry
def build_reserve(
    exclude: Iterable[str] = (),
    per_source: int = PER_SOURCE,
    fetchers: Optional[List[Tuple[str, Callable[[], Tuple[List[str], str]]]]] = None,
    accept: Optional[Callable[[str], bool]] = None,
) -> Dict[str, Any]:
    """Pick up to `per_source` NEW tickers from each source.

    Args:
        exclude: every ticker the session already knows. They are never returned.
        fetchers: [(name, callable returning (symbols, method))]; defaults to SOURCES.
        accept: optional filter, e.g. "does the broker offer it". A symbol it rejects is
            skipped and the next one on that page is used, so a source still fills up to
            `per_source` ACCEPTED tickers.

    Returns:
        {"tickers": interleaved list, "by_source": {name: [...]},
         "duplicates_dropped": {name: [...]}, "untradable_dropped": {name: [...]},
         "methods": {name: how it was fetched}}
    """
    seen = {normalize(s) for s in exclude if s}
    picked: Dict[str, List[str]] = {}
    dropped: Dict[str, List[str]] = {}
    untradable: Dict[str, List[str]] = {}
    methods: Dict[str, str] = {}

    for name, fetch in (fetchers or SOURCES):
        try:
            symbols, method = fetch()
        except Exception as exc:
            symbols, method = [], f"failed: {exc}"
        methods[name], picked[name], dropped[name], untradable[name] = method, [], [], []
        for raw in symbols:
            sym = normalize(raw)
            if not valid_symbol(sym):
                continue
            if sym in seen:
                dropped[name].append(sym)       # already known, or taken by an earlier source
                continue
            if len(picked[name]) >= per_source:
                continue
            if accept is not None:
                try:
                    ok = bool(accept(sym))
                except Exception:
                    ok = False
                if not ok:
                    untradable[name].append(sym)
                    continue
            picked[name].append(sym)
            seen.add(sym)

    ordered: List[str] = []
    for i in range(per_source):
        for name in picked:
            if i < len(picked[name]):
                ordered.append(picked[name][i])
    return {"tickers": ordered, "by_source": picked, "duplicates_dropped": dropped,
            "untradable_dropped": untradable, "methods": methods}


if __name__ == "__main__":
    result = build_reserve()
    for name, tickers in result["by_source"].items():
        print(f"{name:<14} via {result['methods'][name]:<14} {len(tickers):>2}: {tickers}")
        if result["duplicates_dropped"][name]:
            print(f"{'':<14} duplicates skipped: {result['duplicates_dropped'][name]}")
        if result["untradable_dropped"][name]:
            print(f"{'':<14} not tradable skipped: {result['untradable_dropped'][name]}")
    print(f"\nreserve ({len(result['tickers'])}): {result['tickers']}")
