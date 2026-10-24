import json

import yaml

from burn_rate_alert_rule_generator.cli import main


def test_writes_rules_and_json_report(examples, tmp_path, capsys):
    rules = tmp_path / "rules.yaml"
    assert main([str(examples / "slos.yaml"), "--rules-out", str(rules), "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["rules"] == 22 and data["groups"] == 2
    assert data["findings"] == []
    doc = yaml.safe_load(rules.read_text())
    assert len(doc["groups"]) == 2


def test_example_markdown_matches_expected_report(examples, monkeypatch, capsys):
    monkeypatch.chdir(examples.parent)
    assert main(["examples/slos.yaml", "--rules-out", "examples/burn-rate-rules.yaml"]) == 0
    assert capsys.readouterr().out == (examples / "expected-report.md").read_text()


def test_rules_file_matches_committed_example(examples, tmp_path, capsys):
    out = tmp_path / "r.yaml"
    main([str(examples / "slos.yaml"), "--rules-out", str(out)])
    capsys.readouterr()
    assert out.read_text() == (examples / "burn-rate-rules.yaml").read_text()


def test_no_runbook_is_a_warning_and_fail_on_never_passes(tmp_path, capsys):
    slo = tmp_path / "s.yaml"
    slo.write_text("service: a\nslos:\n- name: s\n  objective: 99\n  total: t[{{window}}]\n  errors: e[{{window}}]\n")
    assert main([str(slo), "--format", "json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert [f["rule"] for f in data["findings"]] == ["no-runbook-url"]
    assert main([str(slo), "--fail-on", "never"]) == 0
    capsys.readouterr()


def test_window_longer_than_slo_is_a_finding(tmp_path, capsys):
    slo = tmp_path / "s.yaml"
    slo.write_text(
        "service: a\nrunbook_url: https://r.example.com\nslos:\n- name: s\n  objective: 99\n  window: 2d\n"
        "  total: t[{{window}}]\n  errors: e[{{window}}]\n"
    )
    main([str(slo), "--format", "json"])
    rules = [f["rule"] for f in json.loads(capsys.readouterr().out)["findings"]]
    assert rules.count("window-longer-than-slo") == 1  # the 3d ticket window


def test_invalid_inputs_exit_two(examples, tmp_path, capsys):
    assert main([str(examples / "invalid-slos.yaml")]) == 2
    assert "objective" in capsys.readouterr().err
    assert main([str(tmp_path / "missing.yaml")]) == 2
    capsys.readouterr()
