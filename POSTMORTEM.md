# Copytrade — shut down 2026-09-21

All three GitHub Actions workflows are deleted, so once this lands on `main`
nothing polls, trades, or posts to Slack any more. The Python modules and every
state file are left in place as the record.

The jobs keep running until this merges, so the figures below are a snapshot
taken at 2026-09-21T18:45Z and will drift slightly until then.

## Final numbers

| | |
|---|---|
| Starting cash | $10,000.00 |
| Peak equity | $16,938.41 (2026-06-06) |
| Final equity | $6,774.35 (2026-09-21T18:45Z) |
| Drawdown from peak | -60.0% |
| Realized PnL (110 closed trades) | +$852.40 |
| Free cash at shutdown | $10.82 |
| Open paper positions at shutdown | 917 (904 orphaned) |
| Margin locked in those positions | $10,841.59 |
| Signals generated | 1,137 (1,027 NEW / 110 CLOSED) |

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

1. **Orphaned positions accumulate.** 904 of the 917 open positions belonged
   to traders no longer being followed. The oldest had been open since
   2026-05-20.
2. **Cash drains toward zero, and sizing shrinks with it.** Each NEW signal
   deducts margin; nothing ever returns it. Free cash fell from $10,000 to
   $10.82. Because `open_position()` sizes at `cash * POSITION_PCT`, the
   position size is a fraction of whatever cash is *left*, so it never hits
   the `margin > cash` guard and never stops — it just opens ever-smaller,
   economically meaningless positions. The 18:45Z poll on the final day
   opened 12 positions using $9.20 of margin between them. The engine had
   effectively stopped trading long before the equity curve bottomed out; it
   was still going through the motions.
3. **The equity curve stopped measuring strategy.** Post-June the number was
   mark-to-market drift on a frozen basket of stale positions, not a read on
   whether copying these traders works. The -60% drawdown is not a verdict on
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
- Size positions against *starting* equity or a fixed risk unit, not against
  remaining cash, so sizing cannot asymptote toward zero.
- Cap concurrent positions and reject a NEW signal outright when free cash is
  below a sane floor, instead of opening a dust position.
- Reconcile `portfolio.open_positions` against `state/` on every run and alert
  on any position whose trader has no state file.

## Shutdown checklist

- [x] Delete `.github/workflows/copytrade-daily.yml`
- [x] Delete `.github/workflows/copytrade-positions.yml`
- [x] Delete `.github/workflows/copytrade-report.yml`
- [ ] Merge this PR to `main` — nothing actually stops until then
- [ ] Delete the three cron-job.org jobs (external — manual)
- [ ] Revoke the `copytrade-claude` GitHub PAT
- [ ] Delete the `SLACK_WEBHOOK_URL` repository secret
- [ ] Remove the Slack incoming webhook / `copytrade-bot` app

No real money was ever deployed. Paper only, as designed.
