"""JOB B — every 5 min: poll positions → diff → signals → paper trades."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import fetch_positions
import notes
import paper_engine

LOG_FILE = Path("logs/job_positions.log")
ACTIVE_WALLETS = Path("active_wallets.json")
SIGNALS_FILE = Path("signals.json")
STATE_DIR = Path("state")


def log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line)
    with LOG_FILE.open("a") as f:
        f.write(line + "\n")


def _short(addr: str) -> str:
    return f"{addr[:10]}..." if addr and len(addr) > 10 else (addr or "?")


def _load_signals() -> list:
    if SIGNALS_FILE.exists():
        with SIGNALS_FILE.open() as f:
            return json.load(f)
    return []


def _save_signals(signals: list) -> None:
    with SIGNALS_FILE.open("w") as f:
        json.dump(signals, f, indent=2)


def _load_prior_positions(addr: str) -> list:
    p = STATE_DIR / f"{addr}.json"
    if p.exists():
        with p.open() as f:
            return json.load(f).get("positions", [])
    return []


def _save_state(addr: str, snapshot: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (STATE_DIR / f"{addr}.json").open("w") as f:
        json.dump(snapshot, f, indent=2)


def main() -> int:
    # Bootstrap guard: do not alert-spam before the first daily run.
    if not ACTIVE_WALLETS.exists():
        log("active_wallets.json missing — Job A hasn't run yet, skipping")
        return 0

    try:
        with ACTIVE_WALLETS.open() as f:
            shortlist = json.load(f).get("top_traders", [])
        active_addrs = {t["address"] for t in shortlist}

        # Follow-to-exit: also poll any trader we still hold open paper
        # positions for, even if they've dropped off the shortlist, so their
        # positions get a CLOSED signal when the trader actually exits.
        # Without this, dropped traders' positions never close and leak forever.
        held_addrs = {
            pos["trader"]
            for pos in paper_engine.load_portfolio().get("open_positions", {}).values()
        }
        follow_only = held_addrs - active_addrs
        poll_addrs = sorted(active_addrs | held_addrs)
        log(
            f"Polling {len(poll_addrs)} traders "
            f"({len(active_addrs)} shortlisted, {len(follow_only)} follow-to-exit)"
        )

        signals = _load_signals()
        ts = datetime.now(timezone.utc).isoformat()
        new_count = 0

        for addr in poll_addrs:
            try:
                curr = fetch_positions.get_open_positions(addr)
            except Exception as e:
                log(f"poll failed for {_short(addr)}: {e}")
                continue

            curr_positions = curr["positions"]
            prior = _load_prior_positions(addr)

            curr_map = {f"{p['coin']}:{p['side']}": p for p in curr_positions}
            prior_map = {f"{p['coin']}:{p['side']}": p for p in prior}

            opened = [curr_map[k] for k in curr_map if k not in prior_map]
            closed = [prior_map[k] for k in prior_map if k not in curr_map]

            # Only open new copies from traders on the current shortlist;
            # for follow-to-exit traders we manage existing positions only.
            if addr in active_addrs:
                for p in opened:
                    signals.append({"ts": ts, "trader": addr, "type": "NEW", **p})
                    new_count += 1
            for p in closed:
                signals.append({"ts": ts, "trader": addr, "type": "CLOSED", **p})
                new_count += 1

            _save_state(addr, {
                "positions": curr_positions,
                "timestamp_ms": curr.get("timestamp_ms"),
            })

        if new_count:
            _save_signals(signals)
            log(f"{new_count} new signals appended")
        else:
            log("No position changes")

        portfolio = paper_engine.apply_new_signals()

        # Stop-losses can fire on price moves alone, with zero new signals.
        stopped = portfolio.get("last_stopped", [])
        if stopped:
            log(f"{len(stopped)} position(s) stopped out: {', '.join(stopped)}")

        if new_count or stopped:
            history = portfolio.get("equity_history", [])
            equity = history[-1]["equity"] if history else portfolio["cash"]
            start = portfolio["starting_cash"]
            pnl_pct = (equity - start) / start * 100 if start else 0.0

            lines = [f"{new_count} signal(s) this poll"]
            for s in (signals[-new_count:] if new_count else []):
                lines.append(f"{s['type']} {s['side']} {s['coin']} ({_short(s['trader'])})")
            for key in stopped:
                lines.append(f"STOP-LOSS closed {key}")
            lines.append(f"Portfolio equity: ${equity:,.2f} ({pnl_pct:+.2f}%)")
            notes.append_entry("Position poll (Job B)", lines)

        return 0
    except Exception as e:
        log(f"FATAL: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
