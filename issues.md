# Issues

- [ ] Rule names are built from sanitized service and SLO names, so `x-y` and `x_y` in the same service collide. The tool refuses the file with a duplicate-rule error; it does not rename them.
- [ ] No `for:` is generated, so a single scrape window that crosses the threshold can page immediately once both windows agree.
- [ ] The PromQL in `total`, `errors`, and `good` is not parsed. A malformed expression passes the generator and fails only in `promtool`.
- [ ] `window-longer-than-slo` compares durations only. It does not catch a short window that is too short for the scrape interval.
- [ ] The `budget_consumed_percent` annotation assumes the SLO window is a rolling window. Calendar-window SLOs are not modelled.
