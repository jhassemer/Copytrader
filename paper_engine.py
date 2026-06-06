"""Mock execution engine — applies signals to a paper portfolio."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

INFO_URL = "https://api.hyperliquid.xyz/info"
HEADERS = {"Content-Type": "application/json"}

PORTFOLIO_FILE = Path("portfolio.json")
SIGNALS_FILE = Path("signals.json")
TRADES_FILE = Path("paper_trades.json")

STARTING_CASH = 10_000.0
POSITION_PCT = 0.05    # 5% of cash per signal
SLIPPAGE_BPS = 5
MAX_LEVERAGE = 3

# Risk controls — we set our own stops/caps even when the trader doesn't.
STOP_LOSS_PCT = 0.50       # close a position once its unrealized loss >= 50% of its margin
MAX_GROSS_EXPOSURE = 2.0   # total open notional capped at 2x current equity
MAX_COIN_EXPOSURE = 0.25   # per-coin open notional capped at 25% of current equity
MAX_OPEN_POSITIONS = 40    # hard cap on concurrent open positions


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_mark_prices() -> dict:
    resp = requests.post(INFO_URL, json={"type": "allMids"}, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return {coin: float(px) for coin, px in resp.json().items()}


def load_portfolio() -> dict:
    if PORTFOLIO_FILE.exists():
        with PORTFOLIO_FILE.open() as f:
            return json.load(f)
    return {
        "cash": STARTING_CASH,
        "starting_cash": STARTING_CASH,
        "open_positions": {},
        "equity_history": [],
        "last_processed_signal_index": -1,
    }


def save_portfolio(portfolio: dict) -> None:
    with PORTFOLIO_FILE.open("w") as f:
        json.dump(portfolio, f, indent=2)


def _load_signals() -> list:
    if SIGNALS_FILE.exists():
        with SIGNALS_FILE.open() as f:
            return json.load(f)
    return []


def _append_trade(trade: dict) -> None:
    trades = []
    if TRADES_FILE.exists():
        with TRADES_FILE.open() as f:
            trades = json.load(f)
    trades.append(trade)
    with TRADES_FILE.open("w") as f:
        json.dump(trades, f, indent=2)


def apply_slippage(mark: float, side: str) -> float:
    if side == "LONG":
        return mark * (1 + SLIPPAGE_BPS / 10000)
    return mark * (1 - SLIPPAGE_BPS / 10000)


def position_key(trader: str, coin: str, side: str) -> str:
    return f"{trader}:{coin}:{side}"


def _exposures(portfolio: dict) -> tuple:
    """Return (gross_notional, {coin: notional}) across all open positions."""
    gross = 0.0
    by_coin: dict = {}
    for pos in portfolio["open_positions"].values():
        gross += pos["notional"]
        by_coin[pos["coin"]] = by_coin.get(pos["coin"], 0.0) + pos["notional"]
    return gross, by_coin


def open_position(portfolio: dict, signal: dict, mark: float, marks: dict | None = None) -> bool:
    side = signal["side"]
    leverage = min(int(signal.get("leverage", 1)), MAX_LEVERAGE)
    cash = portfolio["cash"]
    notional = cash * POSITION_PCT * leverage
    margin = notional / leverage
    if margin > cash:
        return False

    # Risk caps: bound concentration and total leverage so a churn of NEW
    # signals can't pile on unbounded exposure.
    if len(portfolio["open_positions"]) >= MAX_OPEN_POSITIONS:
        return False
    equity = _compute_equity(portfolio, marks) if marks is not None else cash
    gross, by_coin = _exposures(portfolio)
    if gross + notional > MAX_GROSS_EXPOSURE * equity:
        return False
    if by_coin.get(signal["coin"], 0.0) + notional > MAX_COIN_EXPOSURE * equity:
        return False

    fill_price = apply_slippage(mark, side)
    size = notional / fill_price
    key = position_key(signal["trader"], signal["coin"], side)

    portfolio["open_positions"][key] = {
        "trader": signal["trader"],
        "coin": signal["coin"],
        "side": side,
        "size": size,
        "entry_price": fill_price,
        "leverage": leverage,
        "margin": margin,
        "notional": notional,
        "opened_at": _now(),
    }
    portfolio["cash"] -= margin
    return True


def _unrealized(pos: dict, mark: float) -> float:
    if pos["side"] == "LONG":
        return (mark - pos["entry_price"]) * pos["size"]
    return (pos["entry_price"] - mark) * pos["size"]


def _settle(portfolio: dict, pos: dict, mark: float, reason: str) -> float:
    """Close an already-popped position at `mark`, bank PnL, record the trade."""
    opposite = "SHORT" if pos["side"] == "LONG" else "LONG"
    exit_price = apply_slippage(mark, opposite)
    pnl = _unrealized(pos, exit_price)

    portfolio["cash"] += pos["margin"] + pnl
    pnl_pct = (pnl / pos["margin"] * 100) if pos["margin"] else 0.0

    _append_trade({
        **pos,
        "exit_price": exit_price,
        "closed_at": _now(),
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "close_reason": reason,
    })
    return pnl


def close_position(portfolio: dict, signal: dict, mark: float) -> bool:
    key = position_key(signal["trader"], signal["coin"], signal["side"])
    pos = portfolio["open_positions"].pop(key, None)
    if pos is None:
        return False
    _settle(portfolio, pos, mark, "signal")
    return True


def apply_stop_losses(portfolio: dict, marks: dict) -> list:
    """Close any position whose unrealized loss has breached STOP_LOSS_PCT of margin."""
    stopped = []
    for key, pos in list(portfolio["open_positions"].items()):
        mark = marks.get(pos["coin"])
        if mark is None or not pos["margin"]:
            continue
        if _unrealized(pos, mark) <= -STOP_LOSS_PCT * pos["margin"]:
            portfolio["open_positions"].pop(key)
            _settle(portfolio, pos, mark, "stop_loss")
            stopped.append(key)
    return stopped


def _compute_equity(portfolio: dict, marks: dict | None) -> float:
    equity = portfolio["cash"]
    marks = marks or {}
    for pos in portfolio["open_positions"].values():
        mark = marks.get(pos["coin"])
        if mark is None:
            equity += pos["margin"]
            continue
        equity += pos["margin"] + _unrealized(pos, mark)
    return equity


def apply_new_signals() -> dict:
    portfolio = load_portfolio()
    signals = _load_signals()

    start = portfolio["last_processed_signal_index"] + 1
    new_signals = signals[start:]

    marks = get_mark_prices()
    for signal in new_signals:
        mark = marks.get(signal.get("coin"))
        if mark is None:
            continue
        if signal["type"] == "NEW":
            open_position(portfolio, signal, mark, marks)
        elif signal["type"] == "CLOSED":
            close_position(portfolio, signal, mark)

    # Risk sweep: enforce our own stop-loss on every poll, regardless of signals.
    portfolio["last_stopped"] = apply_stop_losses(portfolio, marks)

    portfolio["last_processed_signal_index"] = len(signals) - 1

    equity = _compute_equity(portfolio, marks)
    portfolio["equity_history"].append({
        "ts": _now(),
        "equity": equity,
        "cash": portfolio["cash"],
    })

    save_portfolio(portfolio)
    return portfolio


def summary() -> None:
    portfolio = load_portfolio()
    try:
        marks = get_mark_prices()
    except Exception:
        marks = {}
    equity = _compute_equity(portfolio, marks)
    start = portfolio["starting_cash"]
    pnl = equity - start
    pnl_pct = (pnl / start * 100) if start else 0.0

    gross, _ = _exposures(portfolio)
    gross_x = (gross / equity) if equity else 0.0
    print(f"Cash:    ${portfolio['cash']:,.2f}")
    print(f"Equity:  ${equity:,.2f}")
    print(f"All-time PnL: ${pnl:+,.2f} ({pnl_pct:+.2f}%)  — start ${start:,.0f}")
    print(f"Gross exposure: ${gross:,.2f} ({gross_x:.2f}x equity, cap {MAX_GROSS_EXPOSURE:.1f}x)")
    print(f"Open positions: {len(portfolio['open_positions'])} (cap {MAX_OPEN_POSITIONS})")
    for pos in portfolio["open_positions"].values():
        print(
            f"  {pos['side']} {pos['coin']} size={pos['size']:.4f} "
            f"entry=${pos['entry_price']:,.4f} x{pos['leverage']}"
        )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "summary":
        summary()
    else:
        apply_new_signals()
        summary()
