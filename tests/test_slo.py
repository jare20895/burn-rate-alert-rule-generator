import pytest

from burn_rate_alert_rule_generator.slo import DEFAULT_POLICY, SLOError, load, parse_duration


def write(tmp_path, body):
    path = tmp_path / "s.yaml"
    path.write_text(body)
    return path


def test_example_loads_with_defaults(examples):
    slos = load(examples / "slos.yaml")
    assert [s.name for s in slos] == ["availability", "latency"]
    availability, latency = slos
    assert availability.error_budget == pytest.approx(0.001)
    assert latency.labels == {"team": "payments", "tier": "2"}
    assert availability.windows == ["5m", "30m", "1h", "2h", "6h", "1d", "3d"]
    assert availability.policy["page"][0].factor == 14.4


def test_defaults_apply_when_burn_rates_missing(tmp_path):
    slo = load(
        write(
            tmp_path, "service: a\nslos:\n- name: s\n  objective: 99\n  total: x[{{window}}]\n  errors: y[{{window}}]\n"
        )
    )[0]
    assert {k: [(p.long, p.short, p.factor) for p in v] for k, v in slo.policy.items()} == {
        k: [(p["long"], p["short"], p["factor"]) for p in v] for k, v in DEFAULT_POLICY.items()
    }
    assert slo.severity == {"page": "critical", "ticket": "warning"}


def test_parse_duration():
    assert parse_duration("30d") == 2592000
    assert parse_duration("1h30m") == 5400
    with pytest.raises(SLOError):
        parse_duration("a day")


BASE = "service: a\nslos:\n- name: s\n  objective: 99.9\n  total: t[{{window}}]\n"


@pytest.mark.parametrize(
    "extra, message",
    [
        ("  errors: e[{{window}}]\n  good: g[{{window}}]\n", "exactly one of `good` or `errors`"),
        ("  errors: e[5m]\n", "must contain {{window}}"),
        ("  errors: e[{{window}}]\n  objective: 100\n", "between 0 and 100"),
        ("  errors: e[{{window}}]\n  objective: high\n", "must be a percentage"),
        ("  errors: e[{{window}}]\n  window: forever\n", "`window`"),
        (
            "  errors: e[{{window}}]\n  burn_rates:\n    urgent: [{long: 1h, short: 5m, factor: 2}]\n",
            "unknown burn rate kind",
        ),
        (
            "  errors: e[{{window}}]\n  burn_rates:\n    page: [{long: 5m, short: 1h, factor: 2}]\n",
            "shorter than the long",
        ),
        ("  errors: e[{{window}}]\n  burn_rates:\n    page: [{long: 1h, short: 5m, factor: 0}]\n", "greater than zero"),
        ("  errors: e[{{window}}]\n  burn_rates:\n    page: []\n", "non-empty list"),
    ],
)
def test_invalid_slo_fields(tmp_path, extra, message):
    with pytest.raises(SLOError, match=message.replace("{{", "{{").replace("(", r"\(")):
        load(write(tmp_path, BASE + extra))


def test_duplicate_names_and_bad_service(tmp_path):
    dup = (
        BASE + "  errors: e[{{window}}]\n- name: s\n  objective: 99\n  total: t[{{window}}]\n  errors: e[{{window}}]\n"
    )
    with pytest.raises(SLOError, match="duplicate SLO name"):
        load(write(tmp_path, dup))
    with pytest.raises(SLOError, match="`service` must be"):
        load(write(tmp_path, "service: 'a b'\nslos: []\n"))


def test_invalid_example_fails(examples):
    with pytest.raises(SLOError, match="objective"):
        load(examples / "invalid-slos.yaml")
