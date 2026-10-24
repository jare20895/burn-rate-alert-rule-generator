# burn-rate-alert-rule-generator

`burn-rate-alert-rule-generator` is a Python CLI that turns SLO definitions into Prometheus rule files for multi-window, multi-burn-rate alerting, following the approach in the Google SRE Workbook. From an SLO file that gives the PromQL for good and total events (or for errors and total), it writes recording rules for the error ratio over 5m, 30m, 1h, 2h, 6h, 1d, and 3d, and alerting rules that fire only when a long and a short window both exceed a burn-rate threshold. It also prints, for each alert, how much of the SLO's error budget that burn rate spends.

## Safe Public Boundary

Reads an SLO YAML file and writes rule YAML and a report to disk. The tool never connects to Prometheus, Alertmanager, a paging service, or chat, and it makes no network requests. Rule files are only written; load them into your own monitoring yourself. The example SLO is synthetic.

## Install

```bash
pip install .
# or, for development
pip install -e ".[dev]"
```

Requires Python 3.11+ and PyYAML.

## SLO File

```yaml
service: checkout-api            # letters, digits, _ or -
runbook_url: https://runbooks.example.com/checkout-api   # optional; used by every SLO unless it sets its own
labels:                          # optional; added to every alert
  team: payments
slos:
  - name: availability           # unique within the file
    description: Checkout API availability
    objective: 99.9              # percent, strictly between 0 and 100
    window: 30d                  # SLO compliance window; default 30d
    total: sum(rate(http_requests_total{service="checkout-api"}[{{window}}]))
    errors: sum(rate(http_requests_total{service="checkout-api", code=~"5.."}[{{window}}]))
    # or, instead of errors:
    # good: sum(rate(http_request_duration_seconds_bucket{le="0.5"}[{{window}}]))
    labels: {tier: "1"}          # optional; merged over the file-level labels
    severity: {page: critical, ticket: warning}   # optional; these are the defaults
    burn_rates:                  # optional; defaults are the SRE Workbook pairs below
      page:
        - {long: 1h, short: 5m, factor: 14.4}
        - {long: 6h, short: 30m, factor: 6}
      ticket:
        - {long: 1d, short: 2h, factor: 3}
        - {long: 3d, short: 6h, factor: 1}
```

- `{{window}}` in `total`, `errors`, or `good` marks where each recording window goes. Every expression must contain it.
- Give exactly one of `errors` (the bad events) or `good` (the good events). With `good` the error ratio is `1 - good / total`.
- Each burn-rate pair needs `long` and `short` durations (short must be shorter than long) and a positive `factor`.

## Usage

```bash
burn-rate-alert-rule-generator SLOS.yaml --rules-out rules.yaml
    [--format md|json] [--out FILE] [--fail-on warning|never]
```

Demo, from the project folder:

```bash
burn-rate-alert-rule-generator examples/slos.yaml --rules-out examples/burn-rate-rules.yaml
burn-rate-alert-rule-generator examples/slos.yaml --format json --rules-out rules.yaml --out report.json
```

Run from source without installing:

```bash
PYTHONPATH=src python -m burn_rate_alert_rule_generator examples/slos.yaml --rules-out rules.yaml
```

Check the output with Prometheus's own validator (the demo output passes it, see `validation.md`):

```bash
promtool check rules rules.yaml
```

`examples/expected-report.md` and `examples/burn-rate-rules.yaml` are the outputs of the first command, and tests check both byte for byte.

## What Gets Generated

For each SLO, one rule group `slo-<service>-<name>` (with `-` in names turned into `_` where needed for metric names):

- **Recording rules** `slo:<service>_<name>:error_ratio_<window>` for every window the policy uses.
- **Alerts** `<service>_<name>_<kind>_burn_<long>`, one per burn-rate pair. Each fires when both `error_ratio_<long>` and `error_ratio_<short>` are above `factor × (1 − objective/100)`.

Labels on each alert: your labels, `severity`, `service`, `slo`, and `burn_rate_kind`. Annotations: `summary`, `description`, `budget_consumed_percent`, and `runbook_url` when one is set.

No `for:` is generated. The two windows already filter out short spikes; add `for:` in your own rules if you want more.

## How Factors Map to Budget

- Threshold = factor × error budget. For 99.9% the budget is 0.001, so 14.4× is an error ratio of 0.0144.
- Budget spent = factor × long window ÷ SLO window. An alert that has been firing for its whole long window has used that share of the SLO's budget. 14.4× over 1h of a 30-day SLO is 14.4 × 1 / 720 = 2%. 6× over 6h is 5%. 3× over 1d and 1× over 3d are both 10%.

The report prints this table for every SLO.

## Findings

| Rule | Severity | Meaning |
| --- | --- | --- |
| `no-runbook-url` | warning | No `runbook_url` on the SLO or the file. |
| `window-longer-than-slo` | warning | A burn-rate long window is longer than the SLO window, so the alert can never see a full window. |

`--fail-on warning` (the default) exits 1 when there are findings; `--fail-on never` always exits 0 when the rules were generated.

## Exit Codes

| Code | Meaning |
| --- | --- |
| 0 | Rules generated and no finding (or `--fail-on never`). |
| 1 | Rules generated, and there is at least one finding with `--fail-on warning`. |
| 2 | The SLO file is unreadable or invalid, a field is out of range, a rule name would collide, or a generated rule fails the structural check. |

## Non-goals

- Connecting to monitoring, paging, or chat systems, or deploying rules.
- Choosing SLO targets or windows for you.
- Multi-burn-rate rules for latency SLOs that use histograms other than the `good` form shown above (any PromQL can be given, but the tool does not check it).
- Hosted dashboards.

## Development

```bash
pip install -e ".[dev]"
pytest -q
ruff check src tests
```

See [validation.md](validation.md) for the executed evidence, [issues.md](issues.md) for known defects, and [backlog.md](backlog.md) for planned work.
