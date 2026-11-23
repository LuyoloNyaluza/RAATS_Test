"""One workbook, four worksheets (Trades open, Waiting, Closed, Blocked), each row stamped with the
date and time the file was generated in the last column."""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Dict, List, Sequence, Tuple

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

STAMP = "Generated at"

SHEETS: List[Tuple[str, str, List[Tuple[str, str]]]] = [
    ("Trades open", "open", [("Ticket", "ticket"), ("Symbol", "symbol"), ("Side", "side"), ("Volume", "volume"),
                             ("Entry", "entry"), ("Current", "current"), ("SL", "sl"), ("TP", "tp"),
                             ("Swap", "swap"), ("Commission", "commission"), ("P/L ($)", "pnl"),
                             ("Change %", "pct"), ("Opened", "opened")]),
    ("Waiting", "waiting", [("Ticker", "ticker"), ("Reason", "reason"), ("Since", "since")]),
    ("Closed", "closed", [("Ticker", "ticker"), ("Side", "side"), ("Entry", "entry"), ("Exit", "exit"),
                          ("P/L ($)", "pnl"), ("R", "r"), ("Exit reason", "reason"), ("Closed", "time")]),
    ("Blocked", "blocked", [("Ticker", "ticker"), ("Reason", "reason"), ("Time", "time")]),
]


def _safe(v: Any) -> Any:
    """Stop spreadsheet formula injection: text that starts with = + - @ is stored as plain text."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@"):
        return "'" + v
    return v


def build_workbook(data: Dict[str, Sequence[Dict[str, Any]]], when: datetime) -> bytes:
    wb = Workbook()
    active_sheet = wb.active
    if active_sheet is not None:
        wb.remove(active_sheet)
    stamp = when.strftime("%Y-%m-%d %H:%M:%S")
    head_fill = PatternFill("solid", fgColor="1B2735")
    for title, key, cols in SHEETS:
        ws = wb.create_sheet(title)
        headers = [c[0] for c in cols] + [STAMP]
        ws.append(headers)
        for c in ws[1]:
            c.font, c.fill = Font(bold=True, color="FFFFFF"), head_fill
            c.alignment = Alignment(horizontal="center")
        for row in data.get(key, []):
            ws.append([_safe(row.get(field)) for _, field in cols] + [stamp])
        ws.freeze_panes = "A2"
        for i, h in enumerate(headers, start=1):
            width = max([len(str(h))] + [len(str(c.value or "")) for c in ws[get_column_letter(i)]]) + 3
            ws.column_dimensions[get_column_letter(i)].width = min(width, 48)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
