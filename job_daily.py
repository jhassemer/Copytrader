"""JOB A — once a day: leaderboard → shortlist → NOTES."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import analyze_wallets
import fetch_leaderboard
import fetch_positions
import notes

LOG_FILE = Path("logs/job_daily.log")
ACTIVE_WALLETS = Path("active_wallets.json")


def log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line)
    with LOG_FILE.open("a") as f:
        f.write(line + "\n")


def _short(addr: str) -> str:
    return f"{addr[:10]}..." if addr and len(addr) > 10 else (addr or "?")


def _prior_addresses() -> list:
    if not ACTIVE_WALLETS.exists():
        return []
    try:
        with ACTIVE_WALLETS.open() as f:
            data = json.load(f)
        return [t["address"] for t in data.get("top_traders", [])]
    except Exception:
        return []


def main() -> int:
    try:
        prior = _prior_addresses()

        log("Fetching leaderboard...")
        payload = fetch_leaderboard.fetch()
        fetch_leaderboard.save_snapshot(payload)
        rows = payload.get("leaderboardRows", []) if isinstance(payload, dict) else payload
        log(f"Leaderboard: {len(rows)} traders fetched")

        result = analyze_wallets.main()
        top = result["top_traders"]
        log(f"Shortlist updated: {len(top)} traders")

        # Capture current open positions for the NOTES snapshot (best effort).
        positions_by_addr = {}
        for t in top:
            addr = t["address"]
            try:
                positions_by_addr[addr] = fetch_positions.get_open_positions(addr)["positions"]
            except Exception as e:
                log(f"positions fetch failed for {_short(addr)}: {e}")
                positions_by_addr[addr] = None

        new_addrs = [t["address"] for t in top]
        added = [a for a in new_addrs if a not in prior]
        removed = [a for a in prior if a not in new_addrs]

        lines = [f"Leaderboard: {len(rows)} traders fetched, {len(top)} shortlisted"]
        if prior:
            lines.append(f"Shortlist change: +{len(added)} new, -{len(removed)} dropped")
            for a in added:
                lines.append(f"+added {_short(a)}")
            for a in removed:
                lines.append(f"-removed {_short(a)}")
        else:
            lines.append("First shortlist (no prior run)")

        for i, t in enumerate(top, 1):
            lines.append(
                f"#{i} {_short(t['address'])} acc=${t['account_value']:,.0f} "
                f"month=${t['month_pnl']:,.0f} edge={t['month_edge_bps']:.0f}bps"
            )

        lines.append("Current positions across the shortlist:")
        for t in top:
            addr = t["address"]
            positions = positions_by_addr.get(addr)
            if positions is None:
                lines.append(f"  {_short(addr)} (positions unavailable)")
            elif not positions:
                lines.append(f"  {_short(addr)} no open positions")
            else:
                desc = ", ".join(f"{p['side']} {p['coin']} x{p['leverage']}" for p in positions)
                lines.append(f"  {_short(addr)} {len(positions)} positions: {desc}")

        notes.append_entry("Daily refresh (Job A)", lines)
        log("NOTES.md updated")
        return 0
    except Exception as e:
        log(f"FATAL: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
