"""
WhatsApp notifications with approval flow for RAATS.
"""

import os
import json
import requests
import uuid
import time
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict


@dataclass
class ApprovalRequest:
    request_id: str
    timestamp: str
    final_invest: List[str]
    mt5_data: Dict[str, Any]
    account_balance: Optional[float]
    options: List[str]  # ["APPROVE", "REJECT", "MODIFY"]
    status: str = "PENDING"
    user_response: Optional[str] = None
    response_time: Optional[str] = None


class WhatsAppNotifier:
    """
    Sends trade approval requests via WhatsApp and handles responses.
    
    SET YOUR MOBILE NUMBER HERE:
    ----------------------------
    Either set WHATSAPP_PHONE environment variable, or pass phone_number
    to the constructor. Format: +1234567890 (with country code, no spaces)
    """
    
    def __init__(
        self,
        webhook_url: Optional[str] = None,
        phone_number: Optional[str] = None,
        approval_timeout_minutes: int = 10,
    ):
        # ─── INSERT YOUR MOBILE NUMBER HERE ───
        # Option 1: Set as environment variable WHATSAPP_PHONE=+27123456789
        # Option 2: Pass directly: WhatsAppNotifier(phone_number="+27123456789")
        # Option 3: Edit the default below
        self.webhook_url = webhook_url or os.environ.get("WHATSAPP_WEBHOOK_URL")
        self.phone_number = phone_number or os.environ.get("WHATSAPP_PHONE", "+27685265175")  # ← YOUR NUMBER SET HERE
        # ──────────────────────────────────────
        
        self.approval_timeout = approval_timeout_minutes * 60
        self.pending_requests: Dict[str, ApprovalRequest] = {}
        self._response_dir = Path("./data/approvals").expanduser()
        self._response_dir.mkdir(parents=True, exist_ok=True)
        
    def send_approval_request(
        self,
        final_invest: List[str],
        mt5_data: Dict[str, Any],
        account_balance: Optional[float] = None,
        options: Optional[List[str]] = None,
    ) -> ApprovalRequest:
        """Send approval request and return request object."""
        
        request_id = str(uuid.uuid4())[:8]
        options = options or ["APPROVE", "REJECT", "MODIFY"]
        
        request = ApprovalRequest(
            request_id=request_id,
            timestamp=datetime.now().isoformat(),
            final_invest=final_invest,
            mt5_data=mt5_data,
            account_balance=account_balance,
            options=options,
        )
        
        self.pending_requests[request_id] = request
        
        # Format message
        message = self._format_approval_message(request)
        
        # Send via webhook (WhatsApp Business API, Twilio, etc.)
        if self.webhook_url:
            try:
                response = requests.post(
                    self.webhook_url,
                    json={
                        "to": self.phone_number,
                        "text": message,
                        "request_id": request_id,
                    },
                    timeout=10,
                )
                response.raise_for_status()
                print(f"✅ WhatsApp approval request sent to {self.phone_number}")
            except Exception as e:
                print(f"❌ WhatsApp send failed: {e}")
                print(f"   Webhook: {self.webhook_url}")
                print(f"   Phone: {self.phone_number}")
        else:
            print("⚠️  No WHATSAPP_WEBHOOK_URL set - saving to file only")
        
        # Save to file for persistence (fallback)
        self._save_request(request)
        
        return request
    
    def _format_approval_message(self, req: ApprovalRequest) -> str:
        lines = [
            f"🔔 *RAATS Trade Approval Required*",
            f"Request ID: `{req.request_id}`",
            f"Time: {req.timestamp}",
            "",
            f"📋 *Final INVEST List ({len(req.final_invest)}):*",
        ]
        
        for ticker in req.final_invest:
            mt5 = req.mt5_data.get(ticker, {})
            symbol = mt5.get("mt5_symbol", "N/A")
            spread = mt5.get("spread_pct", "N/A")
            tradable = "✅" if mt5.get("tradable") else "❌"
            lines.append(f"  {tradable} {ticker} → {symbol} (spread: {spread}%)")
        
        if req.account_balance is not None:
            bal_emoji = "✅" if req.account_balance >= 20 else "⚠️"
            lines.append(f"\n💰 *MT5 Account Balance:* {bal_emoji} ${req.account_balance:.2f}")
            if req.account_balance < 20:
                lines.append("  ⚠️ *WARNING: Balance < $20 - trades may be rejected!*")
        
        lines.append(f"\n*Options:*")
        for i, opt in enumerate(req.options, 1):
            lines.append(f"  {i}. {opt}")
        
        lines.append(f"\nReply with option number (1-{len(req.options)}) or option name.")
        lines.append(f"Timeout: {self.approval_timeout // 60} minutes")
        
        return "\n".join(lines)
    
    def wait_for_approval(self, request_id: str) -> Optional[str]:
        """
        Wait for human response (polling file-based).
        In production, use webhook callback for real-time response.
        """
        print(f"⏳ Waiting for WhatsApp approval (Request: {request_id})...")
        print(f"   Check your WhatsApp for the approval message")
        print(f"   Or edit response file: {self._get_request_file(request_id)}")
        
        start = time.time()
        while time.time() - start < self.approval_timeout:
            response = self._check_response_file(request_id)
            if response:
                # Update request with response
                req = self.pending_requests.get(request_id)
                if req:
                    req.status = "COMPLETED"
                    req.user_response = response
                    req.response_time = datetime.now().isoformat()
                    self._save_request(req)
                return response
            time.sleep(5)
        
        # Timeout
        req = self.pending_requests.get(request_id)
        if req:
            req.status = "TIMEOUT"
            req.user_response = "TIMEOUT"
            req.response_time = datetime.now().isoformat()
            self._save_request(req)
        
        print(f"⏰ Approval timeout after {self.approval_timeout // 60} minutes")
        return "TIMEOUT"
    
    def _check_response_file(self, request_id: str) -> Optional[str]:
        """Check if response file exists with user decision."""
        path = self._get_request_file(request_id)
        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)
                return data.get("user_response")
            except:
                pass
        return None
    
    def _get_weekly_log_path(self, prefix: str) -> Path:
        """Generate weekly log path: prefix_YYYY-MM-DD_to_YYYY-MM-DD.jsonl"""
        from datetime import datetime, timedelta
        now = datetime.now()
        # Start of week (Monday)
        week_start = now - timedelta(days=now.weekday())
        week_end = week_start + timedelta(days=6)
        start_str = week_start.strftime("%Y-%m-%d")
        end_str = week_end.strftime("%Y-%m-%d")
        return self._response_dir / f"{prefix}_{start_str}_to_{end_str}.jsonl"

    def _save_request(self, request: ApprovalRequest) -> None:
        """Append request to weekly JSONL log for persistence."""
        log_path = self._get_weekly_log_path("approval_requests")
        with open(log_path, "a") as f:
            f.write(json.dumps(asdict(request)) + "\n")
    
    def _get_request_file(self, request_id: str) -> Path:
        return self._response_dir / f"{request_id}.json"
    
    def send_alert(self, message: str) -> bool:
        """Send a simple alert message (not approval)."""
        if not self.webhook_url:
            print(f"📱 Alert (no webhook): {message}")
            return False
        
        try:
            requests.post(
                self.webhook_url,
                json={"to": self.phone_number, "text": message},
                timeout=5,
            )
            return True
        except Exception as e:
            print(f"WhatsApp alert failed: {e}")
            return False


# Convenience function
def send_whatsapp_approval(
    final_invest: List[str],
    mt5_data: Dict[str, Any],
    account_balance: Optional[float] = None,
    phone_number: Optional[str] = None,
    webhook_url: Optional[str] = None,
) -> Optional[str]:
    """Quick function to send approval and wait for response."""
    notifier = WhatsAppNotifier(
        webhook_url=webhook_url,
        phone_number=phone_number,
    )
    request = notifier.send_approval_request(
        final_invest=final_invest,
        mt5_data=mt5_data,
        account_balance=account_balance,
    )
    return notifier.wait_for_approval(request.request_id)