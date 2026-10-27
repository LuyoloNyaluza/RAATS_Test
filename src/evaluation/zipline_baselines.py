"""
src/evaluation/zipline_baselines.py

Shared zipline helpers for the Week 10 notebooks (14, 15, 17):

  * ensure_bundle()        - registers + ingests the 'raats_daily' bundle
  * make_buy_and_hold()    - (initialize, handle_data) for buy-and-hold
  * make_sma_crossover()   - (initialize, handle_data) for SMA fast/slow
  * trade_pnls()           - realised P&L per round-trip trade from a result

Why SMA is computed with data.history():
  SimpleMovingAverage is a *Pipeline* factor. It cannot be looked up inside
  handle_data with context.sma[date][asset]; that raises at runtime. The
  supported way in handle_data is data.history().
"""

import json
import os
import subprocess
import sys
import traceback
from zoneinfo import ZoneInfo
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd
from zipline.api import (
    order_target_percent,
    set_commission,
    set_slippage,
    symbol,
)
from zipline.finance.commission import PerShare
from zipline.finance.slippage import FixedSlippage

try:
    from .csvdir_prep import validate_csvdir
except ImportError:  # imported as a top-level module
    from csvdir_prep import validate_csvdir  # type: ignore

from zipline.errors import HistoryWindowStartsBeforeData


BUNDLE_NAME = "raats_daily"

# bundles we registered ourselves: name -> (csv_dir, calendar)
_REGISTERED: Dict[str, Tuple[str, str]] = {}


# ------------------------------------------------------------------
# HELPERS FOR run_algorithm
# ------------------------------------------------------------------

def utc(date) -> pd.Timestamp:
    """
    Timezone-aware UTC timestamp that zipline accepts.

    pd.Timestamp(x, tz="utc") gives datetime.timezone.utc on current pandas,
    which makes zipline fail with "'datetime.timezone' object has no
    attribute 'key'". A ZoneInfo("UTC") timestamp has the .key it expects.
    """
    ts = pd.Timestamp(date)
    zone = ZoneInfo("UTC")
    return ts.tz_localize(zone) if ts.tzinfo is None else ts.tz_convert(zone)


def show_error(label: str, exc: BaseException, frames: int = 8) -> None:
    """Print a short, plain-text traceback (IPython often hides zipline's)."""
    print(f"{label}: FAILED -> {type(exc).__name__}: {exc}")
    print("".join(traceback.format_tb(exc.__traceback__)[-frames:]))


# ------------------------------------------------------------------
# BUNDLE
# ------------------------------------------------------------------

def _ingest_in_subprocess(name: str, csv_dir: str, calendar: str) -> None:
    """
    Run the (one-off) ingest in a fresh Python process and show its output.

    Why: when ingest fails inside Jupyter, IPython often cannot format the
    traceback ("Unexpected exception formatting exception") and the real
    error is lost. A subprocess returns it as plain text.
    """
    code = (
        "import sys, numpy, pandas, zipline\n"
        "print(f'python {sys.version.split()[0]} | pandas {pandas.__version__} | "
        "numpy {numpy.__version__} | zipline {zipline.__version__}')\n"
        "from zipline.data import bundles\n"
        "from zipline.data.bundles.csvdir import csvdir_equities\n"
        f"bundles.register({name!r}, csvdir_equities(['daily'], {csv_dir!r}), "
        f"calendar_name={calendar!r})\n"
        f"bundles.ingest({name!r}, show_progress=False)\n"
        "print('INGEST OK')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    if proc.stdout.strip():
        print(proc.stdout.strip())
    if proc.returncode != 0:
        print("\n--- INGEST FAILED: plain traceback ---")
        print(proc.stderr.strip() or "(no stderr)")
        raise RuntimeError(
            f"Ingest of bundle '{name}' failed; see the traceback printed above."
        ) from None


def _csv_signature(csv_dir: str) -> Dict[str, List[int]]:
    """{ticker: [size, mtime_ns]} for every CSV in <csv_dir>/daily."""
    sig: Dict[str, List[int]] = {}
    daily = os.path.join(csv_dir, "daily")
    if os.path.isdir(daily):
        for fname in sorted(os.listdir(daily)):
            if fname.lower().endswith(".csv"):
                st = os.stat(os.path.join(daily, fname))
                sig[fname[:-4]] = [st.st_size, st.st_mtime_ns]
    return sig


def _manifest_path(csv_dir: str) -> str:
    return os.path.join(csv_dir, "_ingest_manifest.json")


def _read_manifest(csv_dir: str) -> Optional[Dict[str, List[int]]]:
    try:
        with open(_manifest_path(csv_dir), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write_manifest(csv_dir: str) -> None:
    with open(_manifest_path(csv_dir), "w", encoding="utf-8") as fh:
        json.dump(_csv_signature(csv_dir), fh)


def ensure_bundle(
    csv_dir: Optional[str] = None,
    name: str = BUNDLE_NAME,
    calendar: str = "NYSE",
    reingest: bool = False,
) -> str:
    """
    Make sure bundle `name` is registered AND ingested, then return its name.

    csv_dir must contain a sub-folder called 'daily' holding one CSV per
    symbol (AAPL.csv, ...) with columns:
        date,open,high,low,close,volume,dividend,split
    Falls back to the RAATS_CSV_DIR environment variable.
    Re-ingests automatically when the CSV files in daily/ change; pass
    reingest=True to force it.
    """
    from zipline.data import bundles
    from zipline.data.bundles.csvdir import csvdir_equities

    if name not in bundles.bundles:
        csv_dir = csv_dir or os.environ.get("RAATS_CSV_DIR")
        if not csv_dir:
            raise ValueError(
                f"Bundle '{name}' is not registered. Pass csv_dir=... "
                "or set the RAATS_CSV_DIR environment variable."
            )
        daily_dir = os.path.join(csv_dir, "daily")
        if not os.path.isdir(daily_dir):
            raise FileNotFoundError(
                f"Expected a 'daily' folder with CSVs at: {daily_dir}"
            )
        bundles.register(
            name,
            csvdir_equities(["daily"], csv_dir),
            calendar_name=calendar,
        )
        _REGISTERED[name] = (csv_dir, calendar)

    own = name in _REGISTERED
    need = reingest
    why = "forced re-ingest" if reingest else ""

    if not need:
        try:
            bundles.load(name)        # raises ValueError if never ingested
        except ValueError:
            need, why = True, "bundle not ingested yet"
        else:
            # Re-ingest automatically if the CSV set changed (e.g. new tickers)
            if own and _read_manifest(_REGISTERED[name][0]) != _csv_signature(
                _REGISTERED[name][0]
            ):
                need, why = True, "CSV files changed since the last ingest"

    if need:
        if own:
            csv_dir_used, cal_used = _REGISTERED[name]
            bad = validate_csvdir(csv_dir_used)
            if bad:
                raise ValueError(
                    f"{len(bad)} file(s) in {csv_dir_used}\\daily are not in "
                    f"zipline format (need lowercase date,open,high,low,close,"
                    f"volume,dividend,split): {bad[:5]}. Run prepare_csvdir(...) "
                    "first, or move those files out of daily/."
                )
            print(f"Ingesting bundle '{name}' ({why}) ...")
            _ingest_in_subprocess(name, csv_dir_used, cal_used)
            _write_manifest(csv_dir_used)
        else:
            # registered elsewhere (e.g. ~/.zipline/extension.py): in-process
            print(f"Ingesting bundle '{name}' ({why}) ...")
            bundles.ingest(name, show_progress=True)

    return name


# ------------------------------------------------------------------
# STRATEGIES
# ------------------------------------------------------------------

def _setup(context, ticker: str) -> None:
    context.asset = symbol(ticker)
    context.invested = False
    set_slippage(FixedSlippage(spread=0))
    set_commission(PerShare(cost=0.005))


def make_buy_and_hold(ticker: str) -> Tuple[Callable, Callable]:

    def initialize(context):
        _setup(context, ticker)

    def handle_data(context, data):
        if context.invested or not data.can_trade(context.asset):
            return
        order_target_percent(context.asset, 1.0)
        context.invested = True

    return initialize, handle_data


def make_sma_crossover(
    ticker: str,
    fast: int = 50,
    slow: int = 200,
) -> Tuple[Callable, Callable]:

    def initialize(context):
        _setup(context, ticker)

    def handle_data(context, data):
        if not data.can_trade(context.asset):
            return

        try:
            prices = data.history(context.asset, "price", slow, "1d")
        except HistoryWindowStartsBeforeData:
            return

        # Not enough history yet (start of the bundle)
        if len(prices) < slow or prices.isna().any():
            return

        fast_ma = float(prices.iloc[-fast:].mean())
        slow_ma = float(prices.mean())
        want_long = fast_ma > slow_ma

        # Only trade when the signal flips (avoids daily churn/commissions)
        if want_long != context.invested:
            order_target_percent(context.asset, 1.0 if want_long else 0.0)
            context.invested = want_long

    return initialize, handle_data


# ------------------------------------------------------------------
# TRADE P&L
# ------------------------------------------------------------------

def trade_pnls(result) -> List[float]:
    """
    Realised P&L (before commission) of each round trip, from
    result.transactions (a Series of per-day lists of transaction dicts).
    A round trip ends when the position returns to zero. Positions still
    open at the end are NOT counted.
    """
    pnls: List[float] = []
    pos = 0.0
    cash = 0.0
    for day_txns in result.transactions:
        for t in day_txns:
            amount = float(t["amount"])
            price = float(t["price"])
            pos += amount
            cash -= amount * price
            if abs(pos) < 1e-9:
                pnls.append(cash)
                pos = 0.0
                cash = 0.0
    return pnls
