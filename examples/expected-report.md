# Burn-Rate Alert Report

- SLO file: examples/slos.yaml
- Rules: 22 in 2 groups, written to examples/burn-rate-rules.yaml
- Findings: 0

## checkout-api / availability

Objective 99.9% over 30d: error budget 0.001.

| Kind | Long | Short | Factor | Threshold | Severity | Budget spent per long window |
| --- | --- | --- | ---: | ---: | --- | ---: |
| page | 1h | 5m | 14.4x | 0.0144 | critical | 2% |
| page | 6h | 30m | 6x | 0.006 | critical | 5% |
| ticket | 1d | 2h | 3x | 0.003 | warning | 10% |
| ticket | 3d | 6h | 1x | 0.001 | warning | 10% |

## checkout-api / latency

Objective 99.5% over 30d: error budget 0.005.

| Kind | Long | Short | Factor | Threshold | Severity | Budget spent per long window |
| --- | --- | --- | ---: | ---: | --- | ---: |
| page | 1h | 5m | 14.4x | 0.072 | critical | 2% |
| page | 6h | 30m | 6x | 0.03 | critical | 5% |
| ticket | 1d | 2h | 3x | 0.015 | warning | 10% |
| ticket | 3d | 6h | 1x | 0.005 | warning | 10% |

Threshold = factor × error budget. Budget spent = factor × long window ÷ SLO window: the share of the whole SLO window's budget used while the alert's long window is burning at that rate.

_Reads an SLO file and writes rule files only; never connects to monitoring, paging, or alerting systems._
