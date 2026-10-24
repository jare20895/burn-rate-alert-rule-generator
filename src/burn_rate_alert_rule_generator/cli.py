"""Command-line entry point. Reads an SLO file and writes Prometheus rule YAML; never touches monitoring."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from . import __version__
from .generate import GenerateError, budget_consumed, build_file, validate
from .slo import SLOError, load, parse_duration

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_INVALID = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="burn-rate-alert-rule-generator",
        description="Generate Prometheus multi-window, multi-burn-rate recording and alerting rules from SLO definitions.",
    )
    parser.add_argument("slos", type=Path, help="YAML file with `service` and `slos`")
    parser.add_argument("--rules-out", type=Path, metavar="FILE", help="write Prometheus rule YAML to this file")
    parser.add_argument("--fail-on", choices=("warning", "never"), default="warning")
    parser.add_argument("--format", choices=("md", "json"), default="md", help="summary report format (stdout)")
    parser.add_argument("--out", type=Path, help="write the summary report to a file instead of stdout")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _findings(slos) -> list[dict]:
    findings = []
    for slo in slos:
        where = {"service": slo.service, "slo": slo.name}
        if not slo.runbook_url:
            findings.append(
                {
                    **where,
                    "rule": "no-runbook-url",
                    "severity": "warning",
                    "message": "No runbook_url; the alert annotations will not link to a runbook.",
                }
            )
        for kind, pairs in slo.policy.items():
            for pair in pairs:
                if parse_duration(pair.long) > parse_duration(slo.window):
                    findings.append(
                        {
                            **where,
                            "rule": "window-longer-than-slo",
                            "severity": "warning",
                            "message": f"{kind} burn window {pair.long} is longer than the SLO window "
                            f"{slo.window}, so the alert can never see a full window.",
                        }
                    )
    return findings


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        slos = load(args.slos)
        document = build_file(slos)
    except (SLOError, GenerateError) as exc:
        print(f"burn-rate-alert-rule-generator: {exc}", file=sys.stderr)
        return EXIT_INVALID
    problems = validate(document)
    if problems:
        for problem in problems:
            print(f"burn-rate-alert-rule-generator: {problem}", file=sys.stderr)
        return EXIT_INVALID

    rules_yaml = yaml.safe_dump(document, sort_keys=False, default_flow_style=False, allow_unicode=True, width=100)
    if args.rules_out:
        args.rules_out.write_text(rules_yaml, encoding="utf-8")

    findings = _findings(slos)
    budget = [
        {
            "service": slo.service,
            "slo": slo.name,
            "objective": slo.objective,
            "window": slo.window,
            "error_budget": slo.error_budget,
            "alerts": [
                {
                    "kind": kind,
                    "long": pair.long,
                    "short": pair.short,
                    "factor": pair.factor,
                    "threshold": round(pair.factor * slo.error_budget, 10),
                    "severity": slo.severity[kind],
                    "budget_consumed_percent": round(budget_consumed(pair, slo) * 100, 2),
                }
                for kind in ("page", "ticket")
                for pair in slo.policy.get(kind, ())
            ],
        }
        for slo in slos
    ]
    rule_count = sum(len(g["rules"]) for g in document["groups"])
    if args.format == "json":
        payload = {
            "tool": "burn-rate-alert-rule-generator",
            "version": __version__,
            "rules_file": str(args.rules_out) if args.rules_out else None,
            "groups": len(document["groups"]),
            "rules": rule_count,
            "slos": budget,
            "findings": findings,
        }
        report = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    else:
        lines = [
            "# Burn-Rate Alert Report",
            "",
            f"- SLO file: {args.slos}",
            f"- Rules: {rule_count} in {len(document['groups'])} groups"
            + (f", written to {args.rules_out}" if args.rules_out else " (not written; pass --rules-out)"),
            f"- Findings: {len(findings)}",
            "",
        ]
        for slo in budget:
            lines += [
                f"## {slo['service']} / {slo['slo']}",
                "",
                f"Objective {slo['objective']:g}% over {slo['window']}: error budget {slo['error_budget']:g}.",
                "",
                "| Kind | Long | Short | Factor | Threshold | Severity | Budget spent per long window |",
                "| --- | --- | --- | ---: | ---: | --- | ---: |",
            ]
            lines += [
                f"| {a['kind']} | {a['long']} | {a['short']} | {a['factor']:g}x | {a['threshold']:g} | "
                f"{a['severity']} | {a['budget_consumed_percent']:g}% |"
                for a in slo["alerts"]
            ]
            lines.append("")
        if findings:
            lines += ["## Findings", "", "| Service | SLO | Rule | Message |", "| --- | --- | --- | --- |"]
            lines += [f"| {f['service']} | {f['slo']} | `{f['rule']}` | {f['message']} |" for f in findings]
            lines.append("")
        lines += [
            (
                "Threshold = factor × error budget. Budget spent = factor × long window ÷ SLO window: the share of the "
                "whole SLO window's budget used while the alert's long window is burning at that rate."
            ),
            "",
            "_Reads an SLO file and writes rule files only; never connects to monitoring, paging, or alerting systems._",
            "",
        ]
        report = "\n".join(lines)

    if args.out:
        args.out.write_text(report, encoding="utf-8")
    else:
        sys.stdout.write(report)
    if args.fail_on == "warning" and findings:
        return EXIT_FINDINGS
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
