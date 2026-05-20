# Copytrade

Automatically find the most profitable and consistent traders on
[Hyperliquid](https://hyperliquid.xyz) (a perp DEX) every day, and mirror their
position entries as **paper trades**. No real money — the goal is to validate
the signal for two weeks before considering going live.

The system is **adaptive**: there is no static wallet list. The leaderboard is
re-scored daily, and the follow list changes as the winners change.

## How it works

| Job | Cadence | What it does |
| :-- | :-- | :-- |
| `job_daily.py` | once a day | Fetch leaderboard → filter + score → write `active_wallets.json` |
| `job_positions.py` | every 5 min | Poll each trader's open positions → diff → emit signals → apply paper trades |
| `daily_report.py` | every 30 min | Compute 24h PnL + activity → post a summary to Slack |

State (`active_wallets.json`, `signals.json`, `portfolio.json`,
`paper_trades.json`, `state/`, `NOTES.md`) is committed back to the repo so that
each GitHub Actions run shares continuity with the last.

## Selection logic

Traders are filtered (min account value, min 30d volume, min 30d PnL, daily &
weekly PnL positive) and ranked by **volume-normalized edge** — bps of PnL
earned per dollar traded — rather than ROI, which Hyperliquid reports
unreliably for accounts with deposits/withdrawals. Top 5 by score are followed.

## Paper trading rules

- Starting cash: `$10,000`
- Position size: 5% of cash per signal, leverage capped at 3×
- Slippage: +5 bps per fill

## Running locally

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python job_daily.py            # produce shortlist
python job_positions.py        # position diff + paper trade
python paper_engine.py summary # portfolio summary

DRY_RUN=1 python daily_report.py   # print the report without sending to Slack
```

See [`CLAUDE.md`](CLAUDE.md) for the full design, scoring details, and setup
protocol (GitHub Actions + cron-job.org scheduler + Slack webhook).
