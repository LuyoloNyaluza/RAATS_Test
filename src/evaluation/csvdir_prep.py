"""
src/evaluation/csvdir_prep.py

Builds the folder layout zipline's csvdir bundle needs:

    <csv_dir>/daily/AAPL.csv     columns: date,open,high,low,close,volume,dividend,split

Two sources:

  source="yahoo"       Download long daily history (needed for 50/200 SMA
                       backtests). Prices are dividend/split ADJUSTED, so the
                       dividend/split columns are written as 0 / 1.
  source="indicators"  Convert the existing RAATS indicator files
                       (data/processed/indicators/<TICKER>_indicators.csv).
                       These only hold ~60 trading days, so they are fine for
                       short windows but too short for a 200-day SMA.

No zipline import here, so it can be tested on its own.
"""

import os
import re
from pathlib import Path
from typing import Iterable, List, Optional

import pandas as pd

REQUIRED = ["Date", "Open", "High", "Low", "Close", "Volume"]
_NAME_RE = re.compile(r"^(?:\d+_)?(?P<ticker>.+?)_indicators\.csv$", re.IGNORECASE)


def _to_zipline_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise any OHLCV frame (with a 'Date' column) to zipline's layout."""
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df["Date"]).dt.tz_localize(None).dt.normalize(),
            "open": df["Open"].astype(float),
            "high": df["High"].astype(float),
            "low": df["Low"].astype(float),
            "close": df["Close"].astype(float),
            "volume": df["Volume"].fillna(0).astype("int64"),
            "dividend": 0.0,
            "split": 1.0,
        }
    )
    out = out.dropna(subset=["open", "high", "low", "close"])
    out = out.drop_duplicates("date").sort_values("date")
    # zipline rejects zero/negative prices
    out = out[(out[["open", "high", "low", "close"]] > 0).all(axis=1)]
    return out


def _write(out: pd.DataFrame, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(dest, index=False, date_format="%Y-%m-%d")


def convert_indicators(
    indicators_dir: str,
    csv_dir: str,
    tickers: Optional[Iterable[str]] = None,
    min_rows: int = 20,
) -> List[str]:
    """Convert <TICKER>_indicators.csv files. Returns tickers written."""
    wanted = {t.upper() for t in tickers} if tickers else None
    written: List[str] = []

    for path in sorted(Path(indicators_dir).glob("*_indicators.csv")):
        m = _NAME_RE.match(path.name)
        if not m:
            continue
        ticker = m.group("ticker").upper()
        if wanted is not None and ticker not in wanted:
            continue
        try:
            out = _to_zipline_frame(pd.read_csv(path))
        except Exception as exc:
            print(f"  skip {ticker}: {exc}")
            continue
        if len(out) < min_rows:
            print(f"  skip {ticker}: only {len(out)} rows")
            continue
        _write(out, Path(csv_dir) / "daily" / f"{ticker}.csv")
        written.append(ticker)
    return written


def download_yahoo(
    tickers: Iterable[str],
    csv_dir: str,
    start: str,
    end: str,
    overwrite: bool = False,
) -> List[str]:
    """Download adjusted daily bars from Yahoo Finance into the csvdir layout."""
    import yfinance as yf

    written: List[str] = []
    for ticker in [t.upper() for t in tickers]:
        dest = Path(csv_dir) / "daily" / f"{ticker}.csv"
        if dest.exists() and not overwrite:
            written.append(ticker)
            continue

        raw = yf.download(
            ticker, start=start, end=end, interval="1d",
            auto_adjust=True, progress=False,
        )
        if raw is None or raw.empty:
            print(f"  skip {ticker}: no data from Yahoo")
            continue
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        raw = raw.reset_index().rename(columns={"index": "Date"})
        _write(_to_zipline_frame(raw), dest)
        written.append(ticker)
    return written


def drop_non_sessions(csv_dir: str, calendar: str = "XNYS") -> None:
    """Remove rows that are not trading sessions of `calendar` (zipline's bar
    writer rejects them). Needs exchange_calendars (installed with zipline)."""
    try:
        import exchange_calendars as xcals
        cal = xcals.get_calendar(calendar)
        first, last = cal.first_session, cal.last_session
    except Exception as exc:
        print(f"  (session check skipped: {exc})")
        return

    for p in sorted((Path(csv_dir) / "daily").glob("*.csv")):
        d = pd.read_csv(p)
        ts = pd.to_datetime(d["date"])
        keep = [
            (first <= t <= last) and cal.is_session(t) for t in ts
        ]
        removed = len(d) - sum(keep)
        if removed:
            d[keep].to_csv(p, index=False)
            print(f"  {p.stem}: removed {removed} non-session rows")


ZIPLINE_COLS = ["open", "high", "low", "close", "volume", "dividend", "split"]


def quarantine_strays(csv_dir: str, keep: Iterable[str]) -> List[str]:
    """
    Zipline's csv bundle ingests EVERY *.csv in <csv_dir>/daily as a symbol.
    Move any file whose name is not one of `keep` to <csv_dir>/_ignored/
    (moved, not deleted). Returns the moved file names.
    """
    keep_set = {t.upper() for t in keep}
    daily = Path(csv_dir) / "daily"
    ignored = Path(csv_dir) / "_ignored"
    moved: List[str] = []
    for p in sorted(daily.glob("*.csv")):
        if p.stem.upper() not in keep_set:
            ignored.mkdir(exist_ok=True)
            os.replace(p, ignored / p.name)
            moved.append(p.name)
    if moved:
        print(f"  moved {len(moved)} stray file(s) out of daily/ -> _ignored/: "
              f"{moved[:5]}{' ...' if len(moved) > 5 else ''}")
    return moved


def validate_csvdir(csv_dir: str) -> List[str]:
    """Names of files in daily/ that zipline cannot ingest (wrong columns)."""
    bad: List[str] = []
    for p in sorted((Path(csv_dir) / "daily").glob("*.csv")):
        cols = [c.strip() for c in pd.read_csv(p, nrows=0).columns]
        if not cols or cols[0].lower() != "date" or any(
            c not in cols for c in ZIPLINE_COLS
        ):
            bad.append(p.name)
    return bad


def describe(csv_dir: str) -> pd.DataFrame:
    """Rows and date range per ticker already in <csv_dir>/daily."""
    rows = []
    for p in sorted((Path(csv_dir) / "daily").glob("*.csv")):
        d = pd.read_csv(p, usecols=["date"])
        rows.append({"ticker": p.stem, "rows": len(d),
                     "first": d["date"].min(), "last": d["date"].max()})
    return pd.DataFrame(rows)


def prepare_csvdir(
    tickers: Iterable[str],
    csv_dir: str,
    source: str = "yahoo",
    start: str = "2014-01-01",
    end: str = "2024-12-31",
    indicators_dir: Optional[str] = None,
) -> str:
    """Build <csv_dir>/daily for `tickers` and print what is there."""
    tickers = [t.upper() for t in tickers]
    if source == "yahoo":
        done = download_yahoo(tickers, csv_dir, start, end)
    elif source == "indicators":
        if not indicators_dir:
            raise ValueError("indicators_dir is required for source='indicators'")
        done = convert_indicators(indicators_dir, csv_dir, tickers)
    else:
        raise ValueError("source must be 'yahoo' or 'indicators'")

    missing = sorted(set(tickers) - set(done))
    if missing:
        print(f"  WARNING: no data written for {missing}")
    quarantine_strays(csv_dir, tickers)
    drop_non_sessions(csv_dir)
    info = describe(csv_dir)
    print(info.to_string(index=False) if not info.empty else "  (no CSVs)")
    return csv_dir