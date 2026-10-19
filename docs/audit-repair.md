# Prediction audit repair (2026-10-19)

The existing records and baseline weights are preserved. This change repairs provenance and evaluation; it does not claim improved future returns.

- Legacy SQLite timestamps are UTC; source deadlines without offsets are JST. Equal-to-deadline, later, invalid or missing timestamps are excluded, never deleted.
- Each new run stores a version, fetched time, exhibition stage, model-weight hash and live selection thresholds. Export preparation is not publication. The Pages workflow confirms exact exported version IDs only after successful deployment; confirmation time is never backdated. Evaluation uses the latest confirmed pre-deadline version, with the first legacy snapshot retained for older records. Legacy publication itself cannot be independently proven.
- Recommendation categories are attached to the confirmed version. All-candidate performance and top-three selections remain distinct: the headline aggregate covers all eligible buy candidates, not a top-three-only portfolio.
- Official result reconciliation is bounded to 8 missing records per monitor run, retries no sooner than 24 hours, records source/check time/status, and never overwrites predictions. Unknown pages and unsupported payouts remain unresolved. Explicit cancellation is distinct from unavailable results. Existing official-confirmed results are protected against secondary-source overwrite.
- Coverage now includes 7 base inputs, 3 exhibition inputs and 2 weather fields. The heuristic confidence formula is unchanged and is explicitly not a probability. Odds, calibrated probabilities and expected values remain unavailable, rather than fabricated.
- Weight evaluation uses the saved live selection thresholds and a date-separated holdout. Automatic promotion is disabled while independent forward validation is absent. Existing active weights are retained.
- Monitor and daily notification jobs share the same concurrency group to prevent restored database snapshots overwriting one another.

Verification baseline: 27 tests passed before the change. The repaired suite (35 passing tests) adds deadline boundaries, unpublished/exported versions, snapshot preservation, missing coverage, live selection, official parsing and reconciliation provenance.

Replay of the 2026-10-19 20:02 JST export (7,328 records, 2026-09-02 through 2026-10-19):

| | Completed buy candidates | Hits | Assumed stake | Return | Recovery |
|---|---:|---:|---:|---:|---:|
| Previous | 4,004 | 1,393 | 2,402,400 JPY | 1,864,790 JPY | 77.62% |
| Excluding late records | 3,492 | 1,209 | 2,095,200 JPY | 1,637,450 JPY | 78.15% |

All 831 after-deadline records remain stored; 512 had previously entered the buy-candidate aggregate. Stakes are simulated at 100 JPY per ticket, not actual purchases. The 504 unresolved records included 492 from earlier days; the first bounded official reconciliation recovered 8/8 on a local replay copy. Remaining historical completion depends on subsequent monitor runs.

Recovery: before-change Git bundles and the original exported JSON were retained outside the checkout. Reverting code does not remove the additive version/result-check tables or original history.

Source pushes to main also refresh the existing Pages route without sending notifications. Scheduled notifications keep their existing cadence. Final race weather now prefers the completed result over preview weather.
