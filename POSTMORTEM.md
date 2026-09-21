# Copytrade — shut down 2026-09-21

The system is dead. All three GitHub Actions workflows have been deleted, so
nothing polls, trades, or posts to Slack any more. The Python modules and every
state file are left in place as the record.

## Final numbers

| | |
|---|---|
| Starting cash | $10,000.00 |
| Peak equity | $16,938.41 (2026-06-06) |
| Final equity | $6,451.66 (2026-09-21) |
| Drawdown from peak | -61.9% |
| Realized PnL (110 closed trades) | +$852.40 |
| Free cash at shutdown | $20.02 |
| Open paper positions at shutdown | 905 |
| Margin locked in those positions | $10,832.39 |
| Signals generated | 1,125 (1,015 NEW / 110 CLOSED) |

## Why it failed

`job_positions.py` iterates the current shortlist only:

```python
for t in shortlist:
    addr = t["address"]
    curr = fetch_positions.get_open_positions(addr)
```

The shortlist is regenerated from scratch every day by `job_daily.py` and
turns over heavily — the 2026-09-21 refresh replaced all five traders. Once a
trader rotates off the list, they are never polled again, so the diff that
produces a `CLOSED` signal never runs for them. The paper position they
triggered stays open forever.

That is the whole failure, and it compounds:

1. **Orphaned positions accumulate.** 904 of the 905 open positions belonged
   to traders no longer being followed. The oldest had been open since
   2026-05-20.
2. **Cash drains to zero.** Each NEW signal deducts margin; nothing ever
   returns it. Free cash fell to $20.02, below the margin required for any new
   position, so `open_position()` began skipping every signal. The engine had
   effectively stopped trading well before the equity curve bottomed out.
3. **The equity curve stopped measuring strategy.** Post-June the number was
   mark-to-market drift on a frozen basket of stale positions, not a read on
   whether copying these traders works. The -62% drawdown is not a verdict on
   the selection logic; it is an accounting artifact.

The 110 trades that did close are the only clean data, and they are net
positive (+$852.40). Nothing here proves the thesis wrong. It proves the
position lifecycle was never tied to the trader lifecycle.

## What a rebuild would need

The follow list is adaptive by design, so the position ledger has to be
decoupled from it:

- Poll every trader holding an open paper position, not just the current
  shortlist. Union of `shortlist ∪ traders_with_open_positions`.
- Force-close positions when a trader is dropped, on the day they are dropped,
  rather than waiting for a `CLOSED` signal that can no longer arrive.
- Cap concurrent positions and reject a NEW signal when free cash is below the
  required margin, instead of silently skipping it.
- Reconcile `portfolio.open_positions` against `state/` on every run and alert
  on any position whose trader has no state file.

## Shutdown checklist

- [x] Delete `.github/workflows/copytrade-daily.yml`
- [x] Delete `.github/workflows/copytrade-positions.yml`
- [x] Delete `.github/workflows/copytrade-report.yml`
- [ ] Delete the three cron-job.org jobs (external — manual)
- [ ] Revoke the `copytrade-claude` GitHub PAT
- [ ] Delete the `SLACK_WEBHOOK_URL` repository secret
- [ ] Remove the Slack incoming webhook / `copytrade-bot` app

No real money was ever deployed. Paper only, as designed.
