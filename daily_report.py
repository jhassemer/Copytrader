"""JOB C — read-only: compute 24h PnL + activity, post to Slack."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

PORTFOLIO_FILE = Path("portfolio.json")
TRADES_FILE = Path("paper_trades.json")
SIGNALS_FILE = Path("signals.json")
ACTIVE_WALLETS = Path("active_wallets.json")


def _load(path: Path, default):
    if path.exists():
        with path.open() as f:
            return json.load(f)
    return default


def _parse(ts):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _short(addr: str) -> str:
    return f"{addr[:10]}..." if addr and len(addr) > 10 else (addr or "?")


def humanize_age(ts) -> str:
    dt = _parse(ts)
    if dt is None:
        return "unknown"
    secs = int((datetime.now(timezone.utc) - dt).total_seconds())
    if secs < 0:
        secs = 0
    if secs < 60:
        return f"{secs}s ago"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m ago"
    hours, rem_min = divmod(mins, 60)
    if hours < 24:
        return f"{hours}h {rem_min}m ago"
    days, rem_hr = divmod(hours, 24)
    return f"{days}d {rem_hr}h ago"


def build_message() -> str:
    portfolio = _load(PORTFOLIO_FILE, {})
    trades = _load(TRADES_FILE, [])
    signals = _load(SIGNALS_FILE, [])
    wallets = _load(ACTIVE_WALLETS, {})

    starting_cash = portfolio.get("starting_cash", 10_000.0)
    history = portfolio.get("equity_history", [])
    current_equity = history[-1]["equity"] if history else starting_cash

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    equity_24h_ago = None
    for snap in history:
        ts = _parse(snap.get("ts"))
        if ts is not None and ts <= cutoff:
            equity_24h_ago = snap["equity"]
    if equity_24h_ago is None:
        equity_24h_ago = starting_cash

    pnl_24h = current_equity - equity_24h_ago
    pnl_24h_pct = (pnl_24h / equity_24h_ago * 100) if equity_24h_ago else 0.0
    pnl_all = current_equity - starting_cash
    pnl_all_pct = (pnl_all / starting_cash * 100) if starting_cash else 0.0

    closed_24h = [t for t in trades if (_parse(t.get("closed_at")) or now) >= cutoff
                  and _parse(t.get("closed_at")) is not None]
    realized_24h = sum(t.get("pnl", 0) for t in closed_24h)

    sig_24h = [s for s in signals if (_parse(s.get("ts")) is not None and _parse(s.get("ts")) >= cutoff)]
    new_24h = sum(1 for s in sig_24h if s.get("type") == "NEW")
    closed_sig_24h = sum(1 for s in sig_24h if s.get("type") == "CLOSED")

    open_positions = portfolio.get("open_positions", {})

    lines = [
        f"*📈 Copytrade daily report — {now.strftime('%Y-%m-%d')}*",
        "",
        f"*Portfolio:* `${current_equity:,.2f}`  (yesterday: `${equity_24h_ago:,.2f}`)",
        f"*24h PnL:* `{pnl_24h:+,.2f}` USD  (`{pnl_24h_pct:+.2f}%`)",
        f"*All-time:* `{pnl_all:+,.2f}` USD  (`{pnl_all_pct:+.2f}%`)  — start `${starting_cash:,.0f}`",
        "",
        "*Last 24h activity:*",
        f"• Signals: {new_24h} NEW, {closed_sig_24h} CLOSED",
        f"• Closed paper trades: {len(closed_24h)}  (realized PnL: `{realized_24h:+,.2f}` USD)",
        f"• Open positions: {len(open_positions)}",
        "",
        "*Last activity:*",
    ]

    if signals:
        s = signals[-1]
        lines.append(
            f"• Last signal: {humanize_age(s.get('ts'))} — "
            f"{s.get('type')} {s.get('side')} {s.get('coin')} ({_short(s.get('trader', ''))})"
        )
    else:
        lines.append("• Last signal: none yet")

    if trades:
        t = trades[-1]
        lines.append(
            f"• Last paper trade closed: {humanize_age(t.get('closed_at'))} — "
            f"{t.get('side')} {t.get('coin')} PnL `{t.get('pnl', 0):+,.2f}` USD"
        )
    else:
        lines.append("• Last paper trade closed: none yet")

    lines.append("")
    lines.append(f"*Following:* {len(wallets.get('top_traders', []))} traders")

    if open_positions:
        lines.append("")
        lines.append("*Open positions:*")
        for pos in list(open_positions.values())[:10]:
            lines.append(
                f"• {pos['side']} {pos['coin']}  size=`{pos['size']:.4f}`  "
                f"entry=`${pos['entry_price']:,.4f}`  x{pos['leverage']}"
            )

    return "\n".join(lines)


def main() -> int:
    dry_run = os.environ.get("DRY_RUN") == "1"
    webhook = os.environ.get("SLACK_WEBHOOK_URL")

    if not webhook and not dry_run:
        print("ERROR: SLACK_WEBHOOK_URL not set")
        return 1

    message = build_message()

    if dry_run:
        print(message)
        return 0

    resp = requests.post(webhook, json={"text": message}, timeout=20)
    if not (200 <= resp.status_code < 300):
        print(f"ERROR: Slack webhook returned {resp.status_code}: {resp.text}")
        resp.raise_for_status()
    print("Report posted to Slack")
    return 0


if __name__ == "__main__":
    sys.exit(main())
