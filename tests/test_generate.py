import pytest

from burn_rate_alert_rule_generator.generate import GenerateError, budget_consumed, build_file, validate
from burn_rate_alert_rule_generator.slo import load


@pytest.fixture
def slos(examples):
    return load(examples / "slos.yaml")


def rules(group):
    return {r.get("record") or r["alert"]: r for r in group["rules"]}


def test_recording_rules_for_every_window(slos):
    group = build_file(slos)["groups"][0]
    assert group["name"] == "slo-checkout_api-availability"
    records = [r["record"] for r in group["rules"] if "record" in r]
    assert records == [
        f"slo:checkout_api_availability:error_ratio_{w}" for w in ("5m", "30m", "1h", "2h", "6h", "1d", "3d")
    ]


def test_ratio_expressions_substitute_window(slos):
    rule = rules(build_file(slos)["groups"][0])["slo:checkout_api_availability:error_ratio_1h"]
    assert rule["expr"] == (
        '(sum(rate(http_requests_total{service="checkout-api", code=~"5.."}[1h]))) / '
        '(sum(rate(http_requests_total{service="checkout-api"}[1h])))'
    )


def test_good_form_is_one_minus_good_over_total(slos):
    group = build_file(slos)["groups"][1]
    expr = rules(group)["slo:checkout_api_latency:error_ratio_5m"]["expr"]
    assert expr == (
        '(1 - (sum(rate(http_request_duration_seconds_bucket{service="checkout-api", le="0.5"}[5m]))) / '
        '(sum(rate(http_request_duration_seconds_count{service="checkout-api"}[5m]))))'
    )


def test_page_alert_thresholds_and_windows(slos):
    alert = rules(build_file(slos)["groups"][0])["checkout_api_availability_page_burn_1h"]
    assert alert["expr"] == (
        "slo:checkout_api_availability:error_ratio_1h > 0.0144 and "
        "slo:checkout_api_availability:error_ratio_5m > 0.0144"
    )
    assert alert["labels"]["severity"] == "critical" and alert["labels"]["burn_rate_kind"] == "page"
    assert alert["annotations"]["runbook_url"] == "https://runbooks.example.com/checkout-api"


def test_ticket_alerts_present(slos):
    names = set(rules(build_file(slos)["groups"][0]))
    assert {"checkout_api_availability_ticket_burn_1d", "checkout_api_availability_ticket_burn_3d"} <= names


def test_budget_consumption_matches_sre_workbook(slos):
    availability = slos[0]
    shares = [round(budget_consumed(p, availability) * 100, 2) for p in availability.policy["page"]]
    assert shares == [2.0, 5.0]  # 14.4 x 1h / 30d and 6 x 6h / 30d
    tickets = [round(budget_consumed(p, availability) * 100, 2) for p in availability.policy["ticket"]]
    assert tickets == [10.0, 10.0]


def test_generated_file_is_valid(slos):
    assert validate(build_file(slos)) == []


def test_validate_catches_bad_names_and_duplicates():
    doc = {
        "groups": [
            {
                "name": "g",
                "rules": [
                    {"record": "bad-name", "expr": "up"},
                    {"record": "ok:name", "expr": "up"},
                    {"record": "ok:name", "expr": "up"},
                    {"alert": "A", "expr": "", "labels": {"bad-label": "x"}},
                ],
            }
        ]
    }
    problems = validate(doc)
    assert any("bad-name" in p for p in problems)
    assert any("duplicate record name 'ok:name'" in p for p in problems)
    assert any("no expr" in p for p in problems)
    assert any("bad-label" in p for p in problems)


def test_duplicate_alert_names_across_slos_are_refused(tmp_path):
    from burn_rate_alert_rule_generator.slo import load as load_slos

    path = tmp_path / "s.yaml"
    path.write_text(
        "service: a\nslos:\n"
        "- name: x-y\n  objective: 99\n  total: t[{{window}}]\n  errors: e[{{window}}]\n"
        "- name: x_y\n  objective: 99\n  total: t[{{window}}]\n  errors: e[{{window}}]\n"
    )
    with pytest.raises(GenerateError, match="duplicate rule name"):
        build_file(load_slos(path))
