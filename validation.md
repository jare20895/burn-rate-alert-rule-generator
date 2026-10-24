# Validation

Run from the project folder on Linux with Python 3.12, PyYAML 6.0.3, and Docker 29.1.3 running the official `prom/prometheus:v3.5.0` image for `promtool`. Tests and lint ran in a virtualenv with `pip install -e ".[dev]"`-equivalent packages (PyYAML, pytest, ruff) and `PYTHONPATH=src`. CLI checks ran from a separate fresh virtualenv with a non-editable `pip install .`. The SLO file is synthetic.

## Commands Run

```bash
pytest -q
ruff check src tests
ruff format --check src tests

burn-rate-alert-rule-generator examples/slos.yaml --rules-out examples/burn-rate-rules.yaml
burn-rate-alert-rule-generator examples/slos.yaml --format json --rules-out <scratch>/rules.yaml
burn-rate-alert-rule-generator examples/invalid-slos.yaml          # exit code checked
burn-rate-alert-rule-generator --version

docker run --rm --entrypoint sh -v "$PWD/examples:/data:ro" prom/prometheus:v3.5.0 \
    -c 'promtool check rules /data/burn-rate-rules.yaml'
```

## Input Used

`examples/slos.yaml`: service `checkout-api` with a shared runbook URL and team label, and two SLOs over a 30-day window:
- `availability` at 99.9%, with `errors` (5xx count) over `total`.
- `latency` at 99.5%, with `good` (requests at or under 0.5s) over `total`, and an extra `tier` label.

`examples/invalid-slos.yaml`: an objective of 120, which is outside (0, 100).

## Output Produced

### Tests and lint

- `pytest -q`: `29 passed in 0.08s`
- `ruff check src tests`: `All checks passed!`
- `ruff format --check src tests`: `9 files already formatted`

### promtool

```
Checking /data/burn-rate-rules.yaml
  SUCCESS: 22 rules found
```

### Generated rules (excerpt, from `examples/burn-rate-rules.yaml`)

```yaml
- record: slo:checkout_api_availability:error_ratio_1h
  expr: (sum(rate(http_requests_total{service="checkout-api", code=~"5.."}[1h]))) / (sum(rate(http_requests_total{service="checkout-api"}[1h])))
- alert: checkout_api_availability_page_burn_1h
  expr: slo:checkout_api_availability:error_ratio_1h > 0.0144 and slo:checkout_api_availability:error_ratio_5m > 0.0144
  labels: {team: payments, severity: critical, service: checkout-api, slo: availability, burn_rate_kind: page}
  annotations: {budget_consumed_percent: '2.00', runbook_url: https://runbooks.example.com/checkout-api, ...}
```

Two groups, `slo-checkout_api-availability` and `slo-checkout_api-latency`, with seven recording rules and four alerts each (22 rules total).

### Summary report (excerpt, from `examples/expected-report.md`)

```
| Kind | Long | Short | Factor | Threshold | Severity | Budget spent per long window |
| page | 1h | 5m | 14.4x | 0.0144 | critical | 2% |
| page | 6h | 30m | 6x | 0.006 | critical | 5% |
| ticket | 1d | 2h | 3x | 0.003 | warning | 10% |
| ticket | 3d | 6h | 1x | 0.001 | warning | 10% |
```

### Other runs

| Command | Exit | Result |
| --- | --- | --- |
| `examples/slos.yaml --format json` | 0 | `rules: 22`, `findings: []` |
| `examples/invalid-slos.yaml` | 2 | `examples/invalid-slos.yaml slo 'availability': \`objective\` must be between 0 and 100 (exclusive)` |
| `--version` | 0 | `burn-rate-alert-rule-generator 0.1.0` |

## Why This Demonstrates Correct Behavior

- Thresholds: 0.001 budget × 14.4 = 0.0144, and × 6 = 0.006, which match the SRE Workbook's 14.4× and 6× pairs for a 99.9% objective. The latency SLO at 99.5% gets 0.072 and 0.03, scaled from its 0.005 budget.
- Budget shares: 14.4 × 1h / 30d = 2% and 6 × 6h / 30d = 5%. The ticket pairs each spend 10% (3 × 1d / 30d and 1 × 3d / 30d). These match the Workbook's table.
- Every alert references only recording rules the same group defines (for example the 1h and 5m ratios for the 1h page alert), and `promtool` confirms the references and syntax.
- The `good` form is `1 − good/total`; the test checks the exact expression.
- Duplicate names are refused: `x-y` and `x_y` both sanitize to the same rule names and fail with `duplicate rule name`.
- The invalid objective is rejected before any file is written.

## Not Verified

- Alert behaviour against real traffic, or whether these thresholds suit a particular service.
- Rule evaluation in a running Prometheus (promtool checks syntax and references only).
- Calendar SLO windows, which the tool does not support.
