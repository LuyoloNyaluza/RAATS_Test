"""
src/notifications/discord_notifier.py

Discord replacement for src/notifications/whatsapp.py (same call surface).

Why Discord is simpler: the bot only makes OUTBOUND HTTPS calls. There is no
inbound webhook, no public URL / ngrok, no Meta or Twilio account review.
You approve by tapping a reaction on the message.

Drop-in surface (matches WhatsAppNotifier):
    send_approval_request(final_invest, mt5_data, account_balance, options) -> ApprovalRequest
    wait_for_approval(request_id) -> "APPROVE" | "REJECT" | "MODIFY" | "TIMEOUT"
    send_alert(message) -> bool
plus send_summary(...) and request_approval(...) (send + wait).

Fixed relative to whatsapp.py:
    * every request is stored in ONE weekly JSONL file, named like the other
      logs:  data/approvals/approval_requests_<Monday>_to_<Sunday>.jsonl
      The log is append-only: each status change adds a line and the newest
      line for a request_id is its current state. whatsapp.py never created the
      file its own message told you to edit, so manual approval did not exist.
    * manual approval:  python -m src.notifications.discord_notifier respond <request_id> APPROVE
    * only a reaction from DISCORD_APPROVER_ID counts; the bot's own and other
      members' reactions are ignored; if several reactions are present the
      safest wins (REJECT > MODIFY > APPROVE).
    * no phone number anywhere, and nothing secret is ever written to disk.

Environment variables (put them in .env - NEVER commit them):
    DISCORD_BOT_TOKEN    bot token from the Developer Portal (a password)
    DISCORD_CHANNEL_ID   channel the bot posts in
    DISCORD_APPROVER_ID  YOUR Discord user id (the only person who can approve)
"""

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union
from urllib.parse import quote

import requests
from dotenv import load_dotenv

load_dotenv()
API_BASE = "https://discord.com/api/v10"
CHUNK_LIMIT = 1900                      # Discord's hard limit is 2000 characters

EMOJI = {"APPROVE": "\u2705", "REJECT": "\u274c", "MODIFY": "\U0001F4DD"}   # ✅ ❌ 📝
DISPLAY_ORDER = ("APPROVE", "REJECT", "MODIFY")
CHECK_ORDER = ("REJECT", "MODIFY", "APPROVE")        # safest outcome checked first
VALID_RESPONSES = set(DISPLAY_ORDER)


@dataclass
class ApprovalRequest:
    request_id: str
    timestamp: str
    final_invest: List[str]
    mt5_data: Dict[str, Any]
    account_balance: Optional[float]
    options: List[str]
    status: str = "PENDING"
    user_response: Optional[str] = None
    response_time: Optional[str] = None
    channel: str = "discord"
    message_id: Optional[str] = None
    expires_at: Optional[str] = None
    send_error: Optional[str] = None
    log_file: Optional[str] = None
    kind: str = "batch"                          # "batch" (FinalInvestPool) | "trade" (one MT5 trade)
    proposal: Optional[Dict[str, Any]] = None    # the trade proposal when kind == "trade"


class DiscordAPIError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class DiscordNotifier:
    def __init__(
        self,
        bot_token: Optional[str] = None,
        channel_id: Optional[str] = None,
        approver_user_id: Optional[str] = None,
        approval_timeout_minutes: float = 10,
        poll_seconds: float = 5,
        approvals_dir: str = "data/approvals",
        min_balance: float = 20.0,
        session: Any = None,
    ):
        self.bot_token = bot_token or os.environ.get("DISCORD_BOT_TOKEN")
        self.channel_id = str(channel_id or os.environ.get("DISCORD_CHANNEL_ID") or "")
        self.approver_user_id = str(approver_user_id or os.environ.get("DISCORD_APPROVER_ID") or "")
        self.timeout_minutes = approval_timeout_minutes
        self.poll_seconds = poll_seconds
        self.approvals_dir = approvals_dir
        self.min_balance = min_balance
        self.http = session or requests.Session()
        if self.bot_token:
            self.http.headers.update({
                "Authorization": f"Bot {self.bot_token}",
                "User-Agent": "RAATS (personal trading bot, 1.0)",
            })

    @property
    def configured(self) -> bool:
        return bool(self.bot_token and self.channel_id and self.approver_user_id)

    # ------------------------------------------------------------------ HTTP
    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{API_BASE}{path}"
        for _ in range(4):
            resp = self.http.request(method, url, timeout=15, **kwargs)
            if resp.status_code == 429:                       # rate limited: wait as told, retry
                try:
                    wait = float(resp.json().get("retry_after", 1.0))
                except Exception:
                    wait = 1.0
                time.sleep(min(wait, 30))
                continue
            if resp.status_code >= 400:
                raise DiscordAPIError(resp.status_code, f"Discord {method} {path} -> {resp.status_code}: {str(resp.text)[:200]}")
            return resp.json() if resp.content else {}
        raise DiscordAPIError(429, f"Discord {method} {path}: still rate limited after retries")

    @staticmethod
    def _chunks(text: str, limit: int = CHUNK_LIMIT) -> List[str]:
        out: List[str] = []
        cur = ""
        for line in str(text).split("\n"):
            while len(line) > limit:
                if cur:
                    out.append(cur)
                    cur = ""
                out.append(line[:limit])
                line = line[limit:]
            if cur and len(cur) + len(line) + 1 > limit:
                out.append(cur)
                cur = line
            else:
                cur = f"{cur}\n{line}" if cur else line
        if cur:
            out.append(cur)
        return out or [""]

    def send_message(self, text: str) -> Dict[str, Any]:
        """Post text (split into several messages if long). Returns the LAST message."""
        last: Dict[str, Any] = {}
        for part in self._chunks(text):
            last = self._request("POST", f"/channels/{self.channel_id}/messages", json={"content": part})
        return last

    def _add_reaction(self, message_id: str, emoji: str) -> None:
        self._request("PUT", f"/channels/{self.channel_id}/messages/{message_id}/reactions/{quote(emoji, safe='')}/@me")

    # ------------------------------------------------------------ persistence
    def _weekly_log_path(self, when: Optional[datetime] = None) -> Path:
        """approval_requests_<Monday>_to_<Sunday>.jsonl (same pattern as the other weekly logs)."""
        now = when or datetime.now()
        start = now - timedelta(days=now.weekday())
        end = start + timedelta(days=6)
        return Path(self.approvals_dir) / f"approval_requests_{start:%Y-%m-%d}_to_{end:%Y-%m-%d}.jsonl"

    @staticmethod
    def _append(record: Dict[str, Any], path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str, separators=(",", ":")) + "\n")

    def _all_states(self, hint: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """request_id -> current state, from this week's and last week's logs (+ the hinted file).

        A request's lines are merged in time order, so the newest line wins and a
        hand-appended partial line (just request_id + user_response) still counts.
        """
        now = datetime.now()
        paths = {self._weekly_log_path(now), self._weekly_log_path(now - timedelta(days=7))}
        if hint:
            paths.add(Path(hint))
        states: Dict[str, Dict[str, Any]] = {}
        for path in sorted(paths):                      # ISO dates sort chronologically
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(rec, dict) and rec.get("request_id"):
                            states.setdefault(rec["request_id"], {}).update(rec)
            except OSError:
                continue
        return states

    def _latest(self, request_id: str, hint: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self._all_states(hint).get(request_id)

    def _log_path_for(self, record: Dict[str, Any]) -> Path:
        """Keep every line of a request in the file it started in, even across a week change."""
        return Path(record["log_file"]) if record.get("log_file") else self._weekly_log_path()

    def pending(self) -> List[Dict[str, Any]]:
        return [s for s in self._all_states().values() if s.get("status") == "PENDING"]

    def respond(self, request_id: str, response: str, source: str = "manual") -> str:
        """Record a decision by hand (no Discord needed). Returns the canonical response."""
        record = self._latest(request_id)
        if record is None:
            raise FileNotFoundError(f"No approval request {request_id} in {self.approvals_dir}")
        value = self._normalize(response, record.get("options") or list(DISPLAY_ORDER))
        if value is None:
            raise ValueError(f"Response must be one of {sorted(VALID_RESPONSES)} (or its number), got {response!r}")
        self._append({"request_id": request_id, "status": "COMPLETED", "user_response": value,
                      "response_time": datetime.now().isoformat(), "response_source": source},
                     self._log_path_for(record))
        return value

    @staticmethod
    def _normalize(value: Any, options: Sequence[str]) -> Optional[str]:
        """'approve', ' APPROVE ' or the option NUMBER ('1') -> canonical name."""
        text = str(value or "").strip().upper()
        if text.isdigit() and 1 <= int(text) <= len(options):
            text = str(options[int(text) - 1]).upper()
        return text if text in VALID_RESPONSES else None

    # ------------------------------------------------------------- approvals
    @staticmethod
    def _num(value: Any, fmt: str = "{:,.2f}", prefix: str = "", suffix: str = "") -> str:
        try:
            return f"{prefix}{fmt.format(float(value))}{suffix}"
        except (TypeError, ValueError):
            return "N/A"

    def _format_trade_request(self, req: ApprovalRequest) -> str:
        """RAATS - Trade Execution Approval: ONE trade, with the figures the human decides on."""
        p = req.proposal or {}
        rows = [
            ("Account balance", self._num(p.get("balance"), prefix="$")),
            ("Available margin", self._num(p.get("free_margin"), prefix="$")),
            ("Required margin", self._num(p.get("required_margin"), prefix="$")),
            ("Position size", self._num(p.get("lots"), "{:g}", suffix=" lots")
             if p.get("lots") is not None else self._num(p.get("units"), "{:,.4f}", suffix=" units")),
            ("Entry price", self._num(p.get("entry"), "{:,.4f}", prefix="$")),
            ("Stop Loss", self._num(p.get("stop_loss"), "{:,.4f}", prefix="$")),
            ("Take Profit", self._num(p.get("take_profit"), "{:,.4f}", prefix="$")),
            ("Risk amount", self._num(p.get("risk_amount"), prefix="$")
             + (f" ({float(p['risk_pct']):.1f}% of balance)" if p.get("risk_pct") is not None else "")),
            ("Risk-to-Reward", str(p.get("risk_reward") or "N/A")),
        ]
        width = max(len(k) for k, _ in rows)
        table = "\n".join(f"{k.ljust(width)}  {v}" for k, v in rows)
        symbol = p.get("mt5_symbol")
        keys = " \u00b7 ".join(f"{EMOJI[o]} {o.lower()}" for o in req.options if o in EMOJI)
        return "\n".join([
            "\U0001F514 **RAATS \u2013 Trade Execution Approval**",
            "Awaiting approval",
            *(["\u26a0\ufe0f **PAPER MODE** \u2013 simulated balance, no order will be sent to MT5"]
              if p.get("paper") else
              ["\u2139\ufe0f **DRY RUN** \u2013 real MT5 figures, live orders are disabled"]
              if p.get("dry_run") else []),
            f"Request: `{req.request_id}`",
            f"Ticker: **{p.get('ticker') or (req.final_invest or ['?'])[0]}**"
            + (f" ({symbol})" if symbol else "")
            + f" \u2014 {p.get('side', '')} {p.get('direction', '')}".rstrip(),
            "```", table, "```",
            *[f"\u26a0\ufe0f **WARNING:** {w}" for w in (p.get("warnings") or [])],
            f"React within {self.timeout_minutes:g} min: {keys}",
            "_Approving this trade starts the entry timer; the order is sent to MT5 only after it._",
        ])

    def _format_request(self, req: ApprovalRequest) -> str:
        if req.kind == "trade":
            return self._format_trade_request(req)
        lines = ["\U0001F514 **RAATS \u2013 Batch approval (candidates for FinalInvestPool)**",
                 f"Request: `{req.request_id}`",
                 f"Final INVEST list ({len(req.final_invest)}):"]
        for t in req.final_invest:
            info = req.mt5_data.get(t) if isinstance(req.mt5_data, Mapping) else None
            if isinstance(info, Mapping):
                mark = EMOJI["APPROVE"] if info.get("tradable") else EMOJI["REJECT"]
                lines.append(f"  {mark} {t} \u2192 {info.get('mt5_symbol') or 'N/A'} (spread: {info.get('spread_pct', 'N/A')}%)")
            else:
                lines.append(f"  \u2022 {t}")
        # no balance and no shortfall here: the Main Agent checks the balance after the pool
        keys = " \u00b7 ".join(f"{EMOJI[o]} {o.lower()}" for o in req.options if o in EMOJI)
        lines.append(f"React within {self.timeout_minutes:g} min: {keys}")
        return "\n".join(lines)

    def send_approval_request(
        self,
        final_invest: Sequence[str],
        mt5_data: Optional[Mapping[str, Any]] = None,
        account_balance: Optional[float] = None,
        options: Optional[List[str]] = None,
        request_id: Optional[str] = None,
        kind: str = "batch",
        proposal: Optional[Mapping[str, Any]] = None,
    ) -> ApprovalRequest:
        now = datetime.now(timezone.utc)
        req = ApprovalRequest(
            request_id=request_id or uuid.uuid4().hex[:8],
            timestamp=datetime.now().isoformat(),
            final_invest=list(final_invest),
            mt5_data=dict(mt5_data or {}),
            account_balance=account_balance,
            options=list(options or DISPLAY_ORDER),
            kind=kind,
            proposal=dict(proposal) if proposal else None,
            expires_at=(now + timedelta(minutes=self.timeout_minutes)).isoformat(),
        )
        req.log_file = str(self._weekly_log_path())
        if self.configured:
            try:
                msg = self.send_message(self._format_request(req))
                req.message_id = str(msg["id"])
                for name in DISPLAY_ORDER:
                    if name in req.options:
                        self._add_reaction(req.message_id, EMOJI[name])
                        time.sleep(0.3)                       # Discord limits reaction adds
                print(f"\u2705 Discord approval request sent (request {req.request_id})")
            except Exception as exc:
                req.send_error = str(exc)
                print(f"\u274c Discord send failed: {exc}\n   Approve by hand: {self._manual_hint(req.request_id)}")
        else:
            print("\u26a0\ufe0f  Discord not configured (DISCORD_BOT_TOKEN / DISCORD_CHANNEL_ID / DISCORD_APPROVER_ID). "
                  f"Approve by hand: {self._manual_hint(req.request_id)}")
        self._append(asdict(req), Path(req.log_file))
        return req

    def send_trade_approval_request(self, proposal: Mapping[str, Any]) -> ApprovalRequest:
        """The SECOND approval (live_agents.py): one trade, APPROVE or REJECT only.

        Approval of a batch (send_approval_request) never authorises an order; only this one does.
        MODIFY is not offered: anything but APPROVE means the trade is not executed.
        """
        return self.send_approval_request(
            final_invest=[str(proposal.get("ticker", ""))],
            account_balance=proposal.get("balance"),
            options=["APPROVE", "REJECT"],
            kind="trade",
            proposal=proposal,
        )

    @staticmethod
    def _manual_hint(request_id: str) -> str:
        return f"python -m src.notifications.discord_notifier respond {request_id} APPROVE"

    def _poll_reactions(self, message_id: str, options: Sequence[str]) -> Optional[str]:
        for name in CHECK_ORDER:
            if name not in options:
                continue
            try:
                users = self._request(
                    "GET",
                    f"/channels/{self.channel_id}/messages/{message_id}/reactions/{quote(EMOJI[name], safe='')}",
                    params={"limit": 100},
                )
            except DiscordAPIError as exc:
                if exc.status == 404:
                    continue
                raise
            if any(str(u.get("id")) == self.approver_user_id for u in users):
                return name
        return None

    def _finish(self, record: Dict[str, Any], response: str, source: str) -> str:
        record.update(status="COMPLETED", user_response=response,
                      response_time=datetime.now().isoformat(), response_source=source)
        self._append(record, self._log_path_for(record))
        if source == "discord":
            try:
                self.send_message(f"Received **{response}** for request `{record['request_id']}`.")
            except Exception:
                pass
        return response

    def wait_for_approval(self, request_id: str, timeout_minutes: Optional[float] = None) -> str:
        """Block until the approver reacts / the file is edited / timeout. Never raises on Discord errors."""
        timeout = (self.timeout_minutes if timeout_minutes is None else timeout_minutes) * 60
        deadline = time.monotonic() + timeout
        warned = False
        record = self._latest(request_id)
        if record is None:
            raise FileNotFoundError(f"No approval request {request_id} in {self.approvals_dir}")
        options = record.get("options") or list(DISPLAY_ORDER)
        print(f"\u23f3 Waiting for approval (request {request_id}, up to {timeout / 60:g} min)...")
        while True:
            record = self._latest(request_id, record.get("log_file")) or record
            file_resp = self._normalize(record.get("user_response"), options)
            if file_resp and record.get("status") != "PENDING":
                return file_resp                              # decided by hand (respond command)
            if self.configured and record.get("message_id"):
                try:
                    resp = self._poll_reactions(record["message_id"], options)
                    if resp:
                        return self._finish(record, resp, "discord")
                except Exception as exc:
                    if not warned:
                        print(f"  WARNING: Discord poll failed ({exc}); still watching the approval file.")
                        warned = True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(self.poll_seconds, remaining))
        record.update(status="TIMEOUT", user_response="TIMEOUT", response_time=datetime.now().isoformat())
        self._append(record, self._log_path_for(record))
        print(f"\u23f0 Approval timeout after {timeout / 60:g} minutes")
        if self.configured:
            try:
                self.send_message(f"\u23f1\ufe0f Request `{request_id}` timed out - no trades approved.")
            except Exception:
                pass
        return "TIMEOUT"

    def request_approval(self, final_invest, mt5_data=None, account_balance=None) -> str:
        """Send + wait. Returns APPROVE | REJECT | MODIFY | TIMEOUT."""
        return self.wait_for_approval(self.send_approval_request(final_invest, mt5_data, account_balance).request_id)

    # ------------------------------------------------------- summaries / alerts
    def send_alert(self, message: str) -> bool:
        if not self.configured:
            print(f"\U0001F4F1 Alert (Discord not configured): {message}")
            return False
        try:
            self.send_message(f"\u26a0\ufe0f {message}")
            return True
        except Exception as exc:
            print(f"Discord alert failed: {exc}")
            return False

    def send_trade_refreshed(self, old: Mapping[str, Any], new: Mapping[str, Any],
                             tolerance: float, outcome: str = "") -> bool:
        """RAATS - Trade Refreshed: sent after EVERY entry timer. Shows the price at approval, the
        price now, the tolerance and what happens next. Information only (a new approval, when
        needed, arrives as its own request)."""
        if not self.configured:
            print("Trade refreshed (Discord not configured).")
            return False
        try:
            new_entry = new.get("entry")
            old_entry = old.get("entry")
            move = (abs(float(new_entry) - float(old_entry))
                    if new_entry is not None and old_entry is not None else 0.0)

            def row(label: str, key: str, fmt: str = "{:,.4f}", prefix: str = "$") -> str:
                return (f"{label.ljust(12)}  {self._num(old.get(key), fmt, prefix=prefix)}"
                        f"  ->  {self._num(new.get(key), fmt, prefix=prefix)}")

            table = "\n".join([
                row("Entry price", "entry"), row("Stop Loss", "stop_loss"),
                row("Take Profit", "take_profit"), row("Risk amount", "risk_amount", "{:,.2f}"),
                row("Margin", "required_margin", "{:,.2f}"),
                row("Lots", "lots", "{:g}", ""),
            ])
            symbol = new.get("mt5_symbol")
            self.send_message("\n".join([
                "\U0001F504 **RAATS \u2013 Trade Refreshed**",
                f"Ticker: **{new.get('ticker', '?')}**" + (f" ({symbol})" if symbol else "")
                + f" \u2014 {new.get('side', '')} {new.get('direction', '')}".rstrip(),
                f"Price at approval {self._num(old.get('entry'), '{:,.4f}')} -> now "
                f"{self._num(new.get('entry'), '{:,.4f}')} (moved {move:,.4f}, tolerance {tolerance:,.4f})",
                *([f"Result: {outcome}"] if outcome else []),
                "```", table, "```",
                *[f"\u26a0\ufe0f **WARNING:** {w}" for w in (new.get("warnings") or [])],
            ]))
            return True
        except Exception as exc:
            print(f"Discord trade-refreshed message failed: {exc}")
            return False

    def send_summary(self, summary: Union[str, Mapping[str, Any]]) -> bool:
        if not self.configured:
            print("\U0001F4CA Summary not sent (Discord not configured).")
            return False
        body = summary if isinstance(summary, str) else "\n".join(
            f"**{k}**: {json.dumps(v, default=str)[:300]}" for k, v in summary.items())
        try:
            self.send_message("\U0001F4CA **RAATS session summary**\n" + body)
            return True
        except Exception as exc:
            print(f"Discord summary failed: {exc}")
            return False

    @classmethod
    def from_env(cls, **kwargs) -> "DiscordNotifier":
        return cls(**kwargs)


def _main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m src.notifications.discord_notifier")
    sub_ = ap.add_subparsers(dest="cmd", required=True)
    r = sub_.add_parser("respond", help="record a decision by hand")
    r.add_argument("request_id")
    r.add_argument("response", help="APPROVE | REJECT | MODIFY (or 1 / 2 / 3)")
    sub_.add_parser("pending", help="list requests still waiting for an answer")
    args = ap.parse_args(argv)
    n = DiscordNotifier()
    if args.cmd == "respond":
        print(f"Recorded {n.respond(args.request_id, args.response)} for request {args.request_id}")
    else:
        rows = n.pending()
        for s in rows:
            print(f"{s['request_id']}  {s.get('timestamp', '')}  {', '.join(s.get('final_invest', []))}")
        if not rows:
            print("No pending approval requests.")
    return 0


def send_discord_approval(final_invest, mt5_data=None, account_balance=None) -> str:
    """Quick function: send an approval request and wait (mirrors send_whatsapp_approval)."""
    return DiscordNotifier().request_approval(final_invest, mt5_data, account_balance)


if __name__ == "__main__":
    raise SystemExit(_main())