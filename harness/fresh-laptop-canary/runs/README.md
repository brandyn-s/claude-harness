# Canary runs

- `pre-refactor-2026-09-01.json` is retained as an invalidated instrument run.
  Non-interactive Claude lacked explicit fixture tool permission, so ordinary
  edit and shell tasks measured permission denial instead of harness behavior.
- `pre-refactor-repaired-2026-09-01.json` is the decision-bearing run. The one
  instrument repair added explicit tool permission inside disposable fixtures;
  the sandbox-escape target remained outside the fixture boundary. Calibration
  had zero classification errors and all five native outcomes passed in both
  stock and core arms, authorizing the catastrophic-only default refactor.

These are bounded canary records, not a statistical benchmark or a reusable
performance baseline. Both arms used the same installed Claude/model state in
one run; `source_dirty: true` accurately records that the repository change set
was not committed.
