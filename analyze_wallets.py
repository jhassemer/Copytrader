"""Filter + score the leaderboard, write the top-5 shortlist."""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path("data")
ACTIVE_WALLETS = Path("active_wallets.json")

MIN_ACCOUNT_VALUE = 100_000
MIN_30D_VOLUME = 5_000_000
MIN_30D_PNL = 50_000
MAX_ABS_DAY_ROI = 5.0
TOP_N = 5

FILTERS = {
    "min_account_value": MIN_ACCOUNT_VALUE,
    "min_30d_volume": MIN_30D_VOLUME,
    "min_30d_pnl": MIN_30D_PNL,
    "day_pnl_gt_0": True,
    "week_pnl_gt_0": True,
    "day_pnl_lt_0.8x_month_pnl": True,
    "abs_day_roi_max": MAX_ABS_DAY_ROI,
}


def _windows(row: dict) -> dict:
    return {name: stats for name, stats in row.get("windowPerformances", [])}


def score_trader(row: dict):
    perfs = _windows(row)
    day = perfs.get("day", {})
    week = perfs.get("week", {})
    month = perfs.get("month", {})

    account_value = float(row.get("accountValue", 0) or 0)
    day_pnl = float(day.get("pnl", 0) or 0)
    day_roi = float(day.get("roi", 0) or 0)
    week_pnl = float(week.get("pnl", 0) or 0)
    week_roi = float(week.get("roi", 0) or 0)
    week_volume = float(week.get("vlm", 0) or 0)
    month_pnl = float(month.get("pnl", 0) or 0)
    month_roi = float(month.get("roi", 0) or 0)
    month_volume = float(month.get("vlm", 0) or 0)

    # --- Filters -------------------------------------------------------
    if account_value < MIN_ACCOUNT_VALUE:
        return None
    if month_volume < MIN_30D_VOLUME:
        return None
    if month_pnl < MIN_30D_PNL:
        return None
    if day_pnl <= 0:
        return None
    if week_pnl <= 0:
        return None
    if not (day_pnl < 0.8 * month_pnl):
        return None
    if abs(day_roi) > MAX_ABS_DAY_ROI:
        return None

    # --- Scoring -------------------------------------------------------
    month_edge_bps = (month_pnl / month_volume) * 10000 if month_volume else 0.0
    week_edge_bps = (week_pnl / week_volume) * 10000 if week_volume else 0.0
    score = month_edge_bps * 2.0 + week_edge_bps * 1.0 + math.log10(max(month_pnl, 1))

    return {
        "address": row.get("ethAddress"),
        "account_value": account_value,
        "day_pnl": day_pnl,
        "day_roi": day_roi,
        "week_pnl": week_pnl,
        "week_roi": week_roi,
        "month_pnl": month_pnl,
        "month_roi": month_roi,
        "month_volume": month_volume,
        "month_edge_bps": month_edge_bps,
        "week_edge_bps": week_edge_bps,
        "score": score,
    }


def _load_latest_leaderboard() -> dict:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = DATA_DIR / f"leaderboard_{today}.json"
    if not path.exists():
        snapshots = sorted(DATA_DIR.glob("leaderboard_*.json"))
        if not snapshots:
            raise FileNotFoundError("No leaderboard snapshot found in data/")
        path = snapshots[-1]
    with path.open() as f:
        return json.load(f)


def main() -> dict:
    data = _load_latest_leaderboard()
    rows = data.get("leaderboardRows", []) if isinstance(data, dict) else data

    scored = []
    for row in rows:
        result = score_trader(row)
        if result is not None:
            scored.append(result)

    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:TOP_N]

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": FILTERS,
        "top_traders": top,
    }
    with ACTIVE_WALLETS.open("w") as f:
        json.dump(out, f, indent=2)
    return out


if __name__ == "__main__":
    result = main()
    print(f"Shortlist updated: {len(result['top_traders'])} traders")
    for i, t in enumerate(result["top_traders"], 1):
        print(
            f"#{i} {t['address']} acc=${t['account_value']:,.0f} "
            f"month=${t['month_pnl']:,.0f} edge={t['month_edge_bps']:.0f}bps "
            f"score={t['score']:.2f}"
        )
