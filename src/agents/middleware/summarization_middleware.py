"""
End-of-day summarization middleware that saves to memory and logs.
"""

import json
import os
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

from src.utils.logger import log_session_summary
from src.data.mt5_bridge import get_account_balance


class SummarizationMiddleware:
    """
    Runs at end of trading day to:
    1. Create structured session summary
    2. Save to JSONL (durable, queryable) in data/summaries/
    3. Optionally send to WhatsApp/Telegram
    """
    
    def __init__(
        self,
        memory_dir: Optional[str] = None,
        enable_whatsapp: bool = False,
        whatsapp_webhook: Optional[str] = None,
        whatsapp_phone: Optional[str] = None,
    ):
        # Use local data/summaries/ directory by default
        self.memory_dir = Path(memory_dir or os.environ.get(
            "RAATS_MEMORY_DIR", 
            "data/summaries"
        )).expanduser()
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        
        self.enable_whatsapp = enable_whatsapp
        self.whatsapp_webhook = whatsapp_webhook or os.environ.get("WHATSAPP_WEBHOOK_URL")
        self.whatsapp_phone = whatsapp_phone or os.environ.get("WHATSAPP_PHONE")
        # Capture starting balance at initialization
        self.starting_balance = get_account_balance()
        
    def process_session_end(self, session_results: Dict[str, Any]) -> Dict[str, Any]:
        """Process end-of-day summary and save to memory."""
        
        manager = session_results.get("manager")
        if not manager:
            return {"error": "No manager in session results"}
        
        # Build comprehensive summary
        summary = self._build_summary(manager, session_results)
        
        # 1. Save to JSONL (durable, queryable)
        self._save_jsonl(summary)
        
        # 2. Save to Hermes memory (for cross-session recall)
        self._save_to_hermes_memory(summary)
        
        # 3. Log via existing logger
        log_session_summary(
            active_list=manager.active_list,
            waitlist=manager.waitlist,
            hold_list=[h["ticker"] for h in manager.hold_history],
            metrics=summary["metrics"],
        )
        
        # 4. Send WhatsApp if enabled
        if self.enable_whatsapp and self.whatsapp_webhook:
            self._send_whatsapp_summary(summary)
        
        return summary
    
    def _build_summary(self, manager, session_results: Dict) -> Dict[str, Any]:
        """Build structured summary from session results."""
        
        # Categorize results
        categories = manager._categorize_results()
        
        # Performance metrics - with fallback if dependencies not available
        try:
            from src.simulation.orchestrator import compute_performance_metrics
            metrics = compute_performance_metrics(
                manager.risk_manager.closed_trades,
                manager.portfolio_value,
            )
            metrics = dict(metrics)
        except ImportError:
            # Fallback metrics if pandas_ta not available
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
        
        # Get closing balance
        closing_balance = get_account_balance()
        
        # MT5 data if available
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
        
        # RGR results
        rgr_summary = {}
        for t, d in manager.rgr_results.items():
            rgr_summary[t] = {
                "passed": d.get("passed"),
                "rgr": d.get("rgr"),
                "ror": d.get("ror"),
                "rpr": d.get("rpr"),
                "direction": d.get("direction"),
            }
        
        # Week, Day, Date
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
        with open(file_path, "a") as f:
            f.write(json.dumps(summary) + "\n")
        print(f"📝 Session summary saved to {file_path}")
    
    def _save_to_hermes_memory(self, summary: Dict[str, Any]) -> None:
        """Save key facts to Hermes persistent memory."""
        # This uses the memory tool - saving key facts for cross-session recall
        # The actual memory tool calls would be made by the agent using this middleware
        # Example facts to save (agent would call memory tool with these):
        # - "Last session final_invest: AAPL, NVDA, MSFT"
        # - "Last session RGR rejections: TSLA, META"
        # - "Portfolio PnL: +$234.56"
        # - "Session date: 2026-10-23"
        pass  # Implemented via memory tool in actual agent usage
    
    def _send_whatsapp_summary(self, summary: Dict[str, Any]) -> None:
        """Send summary to WhatsApp webhook."""
        import requests

        webhook_url = self.whatsapp_webhook
        if webhook_url is None:
            return

        message = self._format_whatsapp_message(summary)
        try:
            requests.post(
                webhook_url,
                json={"to": self.whatsapp_phone, "text": message},
                timeout=10
            )
            print(f"📱 WhatsApp summary sent to {self.whatsapp_phone}")
        except Exception as e:
            print(f"WhatsApp summary failed: {e}")
    
    def _format_whatsapp_message(self, summary: Dict[str, Any]) -> str:
        """Format summary for WhatsApp."""
        lines = [
            f"📊 *RAATS Session Summary*",
            f"📅 Week {summary['week']}, {summary['day']} {summary['date']}",
            "",
            f"💰 *Account Balance:*",
            f"   Start: ${summary['starting_balance']:.2f}" if summary['starting_balance'] is not None else "   Start: N/A",
            f"   End:   ${summary['closing_balance']:.2f}" if summary['closing_balance'] is not None else "   End:   N/A",
            f"   Change: ${summary['balance_change']:+.2f}" if summary['balance_change'] is not None else "   Change: N/A",
            "",
            f"✅ *Final INVEST ({len(summary['final_invest'])}):* {', '.join(summary['final_invest']) or 'None'}",
            f"📋 *Active List (Top 10):* {', '.join(summary['active_list']) or 'None'}",
            "",
            f"📈 *Open Trades:* {summary['metrics'].get('open_trades', 0)}",
            f"💰 *Realized PnL:* ${summary['metrics'].get('realized_pnl', 0):.2f}",
            f"📉 *Daily PnL:* ${summary['metrics'].get('daily_pnl', 0):.2f}",
            f"🎯 *Win Rate:* {summary['metrics'].get('win_rate', 0):.1f}%",
        ]
        
        if summary.get("rgr_rejected"):
            lines.append(f"🚫 *RGR Rejected:* {', '.join(summary['rgr_rejected'])}")
        
        if summary.get("mt5_data"):
            lines.append("")
            lines.append("*MT5 Data:*")
            for t, d in summary["mt5_data"].items():
                lines.append(f"  {t} → {d['mt5_symbol']} (spread: {d['spread_pct']}%)")
        
        return "\n".join(lines)


# Convenience function
def run_summarization(
    session_results: Dict[str, Any],
    enable_whatsapp: bool = False,
) -> Dict[str, Any]:
    """Quick function to run summarization middleware."""
    middleware = SummarizationMiddleware(
        enable_whatsapp=enable_whatsapp,
    )
    return middleware.process_session_end(session_results)