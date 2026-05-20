"""Hyperliquid leaderboard fetcher."""
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

LEADERBOARD_URL = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
DATA_DIR = Path("data")


def fetch() -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }
    resp = requests.get(LEADERBOARD_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def save_snapshot(payload: dict) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = DATA_DIR / f"leaderboard_{today}.json"
    with path.open("w") as f:
        json.dump(payload, f)
    return path


if __name__ == "__main__":
    data = fetch()
    p = save_snapshot(data)
    rows = data.get("leaderboardRows", []) if isinstance(data, dict) else data
    print(f"Saved leaderboard snapshot ({len(rows)} traders) to {p}")
