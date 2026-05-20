"""Wrappers around the Hyperliquid `info` endpoint."""
import requests

INFO_URL = "https://api.hyperliquid.xyz/info"
HEADERS = {"Content-Type": "application/json"}

_SIDE_MAP = {"B": "BUY", "A": "SELL"}


def get_open_positions(address: str) -> dict:
    payload = {"type": "clearinghouseState", "user": address}
    resp = requests.post(INFO_URL, json=payload, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    positions = []
    for ap in data.get("assetPositions", []):
        p = ap.get("position", {})
        szi = float(p.get("szi", 0))
        if szi == 0:
            continue
        positions.append({
            "coin": p["coin"],
            "side": "LONG" if szi > 0 else "SHORT",
            "size": abs(szi),
            "entry_price": float(p["entryPx"]),
            "position_value_usd": float(p["positionValue"]),
            "leverage": p["leverage"]["value"],
            "unrealized_pnl": float(p["unrealizedPnl"]),
            "liquidation_price": float(p["liquidationPx"] or 0),
        })

    return {
        "account_value": float(data["marginSummary"]["accountValue"]),
        "positions": positions,
        "timestamp_ms": data["time"],
    }


def get_recent_fills(address: str, limit: int = 50) -> list:
    """Optional helper — not used by the current jobs."""
    payload = {"type": "userFills", "user": address}
    resp = requests.post(INFO_URL, json=payload, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    fills = resp.json()

    out = []
    for f in fills[:limit]:
        out.append({
            "coin": f.get("coin"),
            "side": _SIDE_MAP.get(f.get("side"), f.get("side")),
            "px": float(f.get("px", 0)),
            "sz": float(f.get("sz", 0)),
            "time": f.get("time"),
            "closed_pnl": float(f.get("closedPnl", 0)),
        })
    return out
