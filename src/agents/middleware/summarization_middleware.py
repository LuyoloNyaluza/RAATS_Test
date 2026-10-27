"""
End-of-day summarization middleware that saves to memory and logs.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.utils.logger import log_session_summary
from src.data.mt5_bridge import get_account_balance


class SummarizationMiddleware:
    """
    Runs at end of trading day to:
    1. Create structured session summary
    2. Save to JSONL (durable, queryable) in data/summaries/
    3. Optionally post it to Discord
    """

    def __init__(
        self,
        memory_dir: Optional[str] = None,
        enable_discord: bool = False,
        starting_balance: Optional[float] = None,
        notifier: Any = None,
    ):
        self.memory_dir = Path(memory_dir or os.environ.get(
            "RAATS_MEMORY_DIR",
            "data/summaries"
        )).expanduser()
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        self.enable_discord = enable_discord
        self._notifier = notifier
        # Pass the balance captured at the START of the session. It used to be read
        # here, but this object is built at session END, so "starting" equalled
        # "closing" and balance_change was always ~0.
        self.starting_balance = (
            starting_balance if starting_balance is not None else get_account_balance()
        )

    def process_session_end(self, session_results: Dict[str, Any]) -> Dict[str, Any]:
        """Process end-of-day summary and save to memory."""

        manager = session_results.get("manager")
        if not manager:
            return {"error": "No manager in session results"}

        summary = self._build_summary(manager, session_results)

        # 1. Save to JSONL (durable, queryable)
        self._save_jsonl(summary)

        # 2. Cross-session memory hook (currently a no-op, see method)
        self._save_to_hermes_memory(summary)

        # 3. Log via existing logger
        log_session_summary(
            active_list=manager.active_list,
            waitlist=manager.waitlist,
            hold_list=[h["ticker"] for h in manager.hold_history],
            metrics=summary["metrics"],
        )

        # 4. Post to Discord if enabled
        if self.enable_discord:
            self._send_discord_summary(summary)

        return summary

    def _build_summary(self, manager, session_results: Dict) -> Dict[str, Any]:
        """Build structured summary from session results."""

        categories = manager._categorize_results()

        try:
            from src.simulation.orchestrator import compute_performance_metrics
            metrics = compute_performance_metrics(
                manager.risk_manager.closed_trades,
                manager.portfolio_value,
            )
            metrics = dict(metrics)
        except ImportError:
            metrics = {
                "open_trades": len(manager.risk_manager.positions),
                "closed_trades": len(manager.risk_manager.closed_trades),
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "daily_pnl": 0.0,
                "win_rate": 0.0,
            }

        metrics["open_trades"] = len(manager.risk_manager.positions)
        metrics["closed_trades"] = len(manager.risk_manager.closed_trades)
        metrics["final_invest_count"] = len(manager.final_invest)

        closing_balance = get_account_balance()

        mt5_summary = {}
        if manager.mt5_data:
            for t, d in manager.mt5_data.items():
                mt5_summary[t] = {
                    "mt5_symbol": d.get("mt5_symbol"),
                    "tradable": d.get("tradable"),
                    "spread_pct": d.get("spread_pct"),
                    "bid": d.get("bid"),
                    "ask": d.get("ask"),
                }

        rgr_summary = {}
        for t, d in manager.rgr_results.items():
            rgr_summary[t] = {
                "passed": d.get("passed"),
                "rgr": d.get("rgr"),
                "ror": d.get("ror"),
                "rpr": d.get("rpr"),
                "direction": d.get("direction"),
            }

        now = datetime.now()
        week_num = now.isocalendar()[1]
        day_name = now.strftime("%A")
        date_str = now.strftime("%Y-%m-%d")

        return {
            "week": week_num,
            "day": day_name,
            "date": date_str,
            "session_date": date_str,
            "session_time": now.isoformat(),
            "starting_balance": self.starting_balance,
            "closing_balance": closing_balance,
            "balance_change": (closing_balance - self.starting_balance) if (closing_balance is not None and self.starting_balance is not None) else None,
            "final_invest": manager.final_invest,
            "active_list": manager.active_list,
            "waitlist": manager.waitlist,
            "hold_history": manager.hold_history,
            "replacement_history": manager.replacement_history,
            "rgr_rejected": manager.rgr_rejected,
            "rgr_details": rgr_summary,
            "mt5_data": mt5_summary,
            "categories": {k: v for k, v in categories.items() if v},
            "metrics": metrics,
            "portfolio_summary": manager.risk_manager.portfolio_summary(),
            "closed_positions": manager.closed_positions_today,
        }

    def _save_jsonl(self, summary: Dict[str, Any]) -> None:
        """Append to JSONL file for durable storage."""
        file_path = self.memory_dir / f"sessions_{datetime.now().strftime('%Y-%m')}.jsonl"
        # default=str: numpy floats / Timestamps in the summary used to crash json.dumps
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(summary, default=str) + "\n")
        print(f"Session summary saved to {file_path}")

    def _save_to_hermes_memory(self, summary: Dict[str, Any]) -> None:
        """Placeholder: nothing is written to any cross-session memory yet.

        The JSONL file above is the only durable record. Previous days' findings
        are NOT fed back to the agents until something reads those files.
        """
        pass

    def _send_discord_summary(self, summary: Dict[str, Any]) -> None:
        """Post the summary to the Discord channel."""
        try:
            notifier = self._notifier
            if notifier is None:
                from src.notifications.discord_notifier import DiscordNotifier
                notifier = DiscordNotifier()
            if notifier.send_summary(self._format_discord_message(summary)):
                print("Discord summary sent")
        except Exception as e:
            print(f"Discord summary failed: {e}")

    def _format_discord_message(self, summary: Dict[str, Any]) -> str:
        """Format summary for Discord (markdown: **bold**)."""
        m = summary.get("metrics") or {}
        # RiskManager.portfolio_summary() holds realized/daily PnL and win rate.
        # compute_performance_metrics() has none of those keys, so reading them
        # from metrics always showed $0.00 and 0.0%.
        ps = summary.get("portfolio_summary") or {}

        def money(v: Optional[float]) -> str:
            return f"${v:,.2f}" if v is not None else "N/A"

        lines = [
            f"Week {summary['week']}, {summary['day']} {summary['date']}",
            "",
            "**Account balance**",
            f"   Start: {money(summary['starting_balance'])}",
            f"   End:   {money(summary['closing_balance'])}",
            "   Change: " + (f"${summary['balance_change']:+,.2f}" if summary['balance_change'] is not None else "N/A"),
            "",
            f"**Final INVEST ({len(summary['final_invest'])}):** {', '.join(summary['final_invest']) or 'None'}",
            f"**Active list:** {', '.join(summary['active_list']) or 'None'}",
            "",
            f"**Open trades:** {m.get('open_trades', ps.get('open_positions', 0))}",
            f"**Realized PnL:** {money(ps.get('realized_pnl', m.get('realized_pnl', 0.0)))}",
            f"**Daily PnL:** {money(ps.get('daily_pnl', m.get('daily_pnl', 0.0)))}",
            f"**Win rate:** {ps.get('win_rate', m.get('win_rate_pct', 0.0)):.1f}%",
        ]
        for key, label, fmt in (("total_return_pct", "Return", "{:+.2f}%"),
                                ("sharpe", "Sharpe", "{:.2f}"),
                                ("max_drawdown_pct", "Max drawdown", "{:.2f}%")):
            if m.get(key) is not None:
                lines.append(f"**{label}:** " + fmt.format(m[key]))

        if summary.get("rgr_rejected"):
            lines.append(f"**RGR rejected:** {', '.join(summary['rgr_rejected'])}")

        if summary.get("mt5_data"):
            lines.append("")
            lines.append("**MT5 data**")
            for t, d in summary["mt5_data"].items():
                lines.append(f"  {t} -> {d.get('mt5_symbol')} (spread: {d.get('spread_pct')}%)")

        return "\n".join(lines)


def run_summarization(
    session_results: Dict[str, Any],
    enable_discord: bool = False,
    starting_balance: Optional[float] = None,
) -> Dict[str, Any]:
    """Quick function to run summarization middleware."""
    middleware = SummarizationMiddleware(
        enable_discord=enable_discord,
        starting_balance=starting_balance,
    )
    return middleware.process_session_end(session_results)