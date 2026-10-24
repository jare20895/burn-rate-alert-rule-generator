"""Build Prometheus recording and alerting rule groups for multi-window, multi-burn-rate SLO alerts."""

from __future__ import annotations

import re

from .slo import PLACEHOLDER, SLO, WindowPair, parse_duration

METRIC_NAME = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
LABEL_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class GenerateError(ValueError):
    pass


def sanitize(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", text).strip("_").lower()


def budget_consumed(pair: WindowPair, slo: SLO) -> float:
    """Share of the whole SLO window's error budget spent during the long window of a burn-rate alert that fires."""
    return pair.factor * parse_duration(pair.long) / parse_duration(slo.window)


def _ratio(slo: SLO, window: str) -> str:
    total = slo.total.replace(PLACEHOLDER, window)
    if slo.errors is not None:
        return f"({slo.errors.replace(PLACEHOLDER, window)}) / ({total})"
    good = slo.good.replace(PLACEHOLDER, window)
    return f"(1 - ({good}) / ({total}))"


def record_name(slo: SLO, window: str) -> str:
    return f"slo:{sanitize(slo.service)}_{sanitize(slo.name)}:error_ratio_{window}"


def alert_name(slo: SLO, kind: str, pair: WindowPair) -> str:
    return f"{sanitize(slo.service)}_{sanitize(slo.name)}_{kind}_burn_{pair.long}"


def build_group(slo: SLO) -> dict:
    """One rule group per SLO: recording rules for each window, then the alerts that read them."""
    rules: list[dict] = []
    for window in slo.windows:
        rules.append({"record": record_name(slo, window), "expr": _ratio(slo, window)})

    names: set[str] = set()
    for kind in ("page", "ticket"):
        for pair in slo.policy.get(kind, ()):
            name = alert_name(slo, kind, pair)
            if name in names:
                raise GenerateError(f"{slo.service}/{slo.name}: duplicate alert name {name}")
            names.add(name)
            threshold = round(pair.factor * slo.error_budget, 10)
            expr = (
                f"{record_name(slo, pair.long)} > {_fmt(threshold)} "
                f"and {record_name(slo, pair.short)} > {_fmt(threshold)}"
            )
            labels = {
                **slo.labels,
                "severity": slo.severity[kind],
                "service": slo.service,
                "slo": slo.name,
                "burn_rate_kind": kind,
            }
            annotations = {
                "summary": f"{slo.description}: {_fmt(pair.factor)}x burn over {pair.long} and {pair.short}",
                "description": (
                    f"Error ratio is above {_fmt(threshold)} ({_fmt(pair.factor)}x the {_fmt(slo.error_budget)} "
                    f"error budget) over both {pair.long} and {pair.short}. At this rate about "
                    f"{budget_consumed(pair, slo) * 100:.2f}% of the {slo.window} error budget is spent every "
                    f"{pair.long}."
                ),
                "budget_consumed_percent": f"{budget_consumed(pair, slo) * 100:.2f}",
            }
            if slo.runbook_url:
                annotations["runbook_url"] = slo.runbook_url
            rules.append({"alert": name, "expr": expr, "labels": labels, "annotations": annotations})
    return {"name": f"slo-{sanitize(slo.service)}-{sanitize(slo.name)}", "rules": rules}


def build_file(slos: list[SLO]) -> dict:
    groups = [build_group(slo) for slo in slos]
    seen: dict[str, str] = {}
    for group in groups:
        for rule in group["rules"]:
            key = rule.get("record") or rule["alert"]
            if key in seen:
                raise GenerateError(f"duplicate rule name {key} in groups {seen[key]} and {group['name']}")
            seen[key] = group["name"]
    return {"groups": groups}


def validate(document: dict) -> list[str]:
    """Structural checks on generated rules, the same ones promtool would fail on first. Returns problems."""
    problems: list[str] = []
    for group in document.get("groups", []):
        names: set[str] = set()
        for rule in group.get("rules", []):
            kind = "record" if "record" in rule else "alert"
            name = rule.get(kind, "")
            if not METRIC_NAME.match(name):
                problems.append(f"{group['name']}: {kind} name {name!r} is not a valid metric name")
            if name in names:
                problems.append(f"{group['name']}: duplicate {kind} name {name!r}")
            names.add(name)
            if not rule.get("expr"):
                problems.append(f"{group['name']}: {name} has no expr")
            for label in rule.get("labels", {}):
                if not LABEL_NAME.match(label):
                    problems.append(f"{group['name']}: label name {label!r} is not valid")
    return problems


def _fmt(value: float) -> str:
    return f"{value:g}"
