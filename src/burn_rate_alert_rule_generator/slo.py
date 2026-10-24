"""Load SLO definitions and their burn-rate alert policies from YAML."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PLACEHOLDER = "{{window}}"
_DURATION = re.compile(r"(\d+)(ms|s|m|h|d|w|y)")
_UNIT_SECONDS = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "y": 31536000}
_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]*$")

# Google SRE Workbook, chapter 5, "Multiwindow, Multi-Burn-Rate Alerts".
DEFAULT_POLICY = {
    "page": [{"long": "1h", "short": "5m", "factor": 14.4}, {"long": "6h", "short": "30m", "factor": 6}],
    "ticket": [{"long": "1d", "short": "2h", "factor": 3}, {"long": "3d", "short": "6h", "factor": 1}],
}
DEFAULT_SEVERITY = {"page": "critical", "ticket": "warning"}


class SLOError(ValueError):
    pass


def parse_duration(text: object) -> float:
    value = str(text).strip()
    if not value or _DURATION.sub("", value):
        raise SLOError(f"invalid duration {text!r}")
    return sum(int(number) * _UNIT_SECONDS[unit] for number, unit in _DURATION.findall(value))


@dataclass(frozen=True)
class WindowPair:
    long: str
    short: str
    factor: float

    @property
    def long_seconds(self) -> float:
        return parse_duration(self.long)


@dataclass(frozen=True)
class SLO:
    service: str
    name: str
    objective: float  # percent, for example 99.9
    window: str  # the SLO compliance window, for example 30d
    total: str
    good: str | None
    errors: str | None
    description: str
    runbook_url: str | None
    labels: dict[str, str]
    policy: dict[str, tuple[WindowPair, ...]]
    severity: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SEVERITY))

    @property
    def error_budget(self) -> float:
        return round(1 - self.objective / 100, 10)

    @property
    def windows(self) -> list[str]:
        seen = {w for pairs in self.policy.values() for p in pairs for w in (p.long, p.short)}
        return sorted(seen, key=parse_duration)


def _text(value: object, where: str, key: str, required: bool = True) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise SLOError(f"{where}: missing `{key}`")
        return None
    if not isinstance(value, str):
        raise SLOError(f"{where}: `{key}` must be a string")
    return value.strip()


def _expression(slo: dict, key: str, where: str, required: bool) -> str | None:
    expr = _text(slo.get(key), where, key, required)
    if expr is not None and PLACEHOLDER not in expr:
        raise SLOError(
            f"{where}: `{key}` must contain {PLACEHOLDER} where the range goes, for example rate(x[{{{{window}}}}])"
        )
    return expr


def _policy(raw: object, where: str) -> dict[str, tuple[WindowPair, ...]]:
    if raw is None:
        raw = DEFAULT_POLICY
    if not isinstance(raw, dict) or not raw:
        raise SLOError(f"{where}: `burn_rates` must map `page` and/or `ticket` to window pairs")
    policy = {}
    for kind, pairs in raw.items():
        if kind not in DEFAULT_POLICY:
            raise SLOError(f"{where}: unknown burn rate kind {kind!r}; use `page` or `ticket`")
        if not isinstance(pairs, list) or not pairs:
            raise SLOError(f"{where}: `burn_rates.{kind}` must be a non-empty list")
        built = []
        for i, pair in enumerate(pairs):
            here = f"{where} burn_rates.{kind}[{i}]"
            if not isinstance(pair, dict):
                raise SLOError(f"{here}: expected a mapping with long, short, and factor")
            try:
                long_s, short_s = parse_duration(pair.get("long")), parse_duration(pair.get("short"))
                factor = float(pair.get("factor"))
            except (SLOError, TypeError, ValueError) as exc:
                raise SLOError(f"{here}: {exc}") from exc
            if short_s >= long_s:
                raise SLOError(f"{here}: the short window must be shorter than the long window")
            if factor <= 0:
                raise SLOError(f"{here}: factor must be greater than zero")
            built.append(WindowPair(str(pair["long"]), str(pair["short"]), factor))
        policy[kind] = tuple(built)
    return {kind: policy[kind] for kind in DEFAULT_POLICY if kind in policy}


def load(path: Path) -> list[SLO]:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise SLOError(f"{path}: cannot read SLO file ({exc})") from exc
    except yaml.YAMLError as exc:
        raise SLOError(f"{path}: invalid YAML ({exc})") from exc
    if not isinstance(document, dict):
        raise SLOError(f"{path}: expected a mapping with `service` and `slos`")
    service = _text(document.get("service"), str(path), "service")
    if not _NAME.match(service):
        raise SLOError(f"{path}: `service` must be letters, digits, `_`, or `-`")
    raw_slos = document.get("slos")
    if not isinstance(raw_slos, list) or not raw_slos:
        raise SLOError(f"{path}: `slos` must be a non-empty list")
    shared_labels = document.get("labels") or {}
    slos, names = [], set()
    for index, raw in enumerate(raw_slos):
        where = f"{path} slos[{index}]"
        if not isinstance(raw, dict):
            raise SLOError(f"{where}: expected a mapping")
        name = _text(raw.get("name"), where, "name")
        where = f"{path} slo {name!r}"
        if not _NAME.match(name):
            raise SLOError(f"{where}: `name` must be letters, digits, `_`, or `-`")
        if name in names:
            raise SLOError(f"{where}: duplicate SLO name")
        names.add(name)
        try:
            objective = float(raw.get("objective"))
        except (TypeError, ValueError):
            raise SLOError(f"{where}: `objective` must be a percentage such as 99.9") from None
        if not 0 < objective < 100:
            raise SLOError(f"{where}: `objective` must be between 0 and 100 (exclusive)")
        window = str(raw.get("window", "30d"))
        try:
            parse_duration(window)
        except SLOError as exc:
            raise SLOError(f"{where}: `window`: {exc}") from exc
        good = _expression(raw, "good", where, required=False)
        errors = _expression(raw, "errors", where, required=False)
        if (good is None) == (errors is None):
            raise SLOError(f"{where}: give exactly one of `good` or `errors`")
        labels = {**shared_labels, **(raw.get("labels") or {})}
        if not isinstance(labels, dict):
            raise SLOError(f"{where}: `labels` must be a mapping")
        severity = dict(DEFAULT_SEVERITY)
        severity.update({k: str(v) for k, v in (raw.get("severity") or {}).items() if k in DEFAULT_SEVERITY})
        slos.append(
            SLO(
                service=service,
                name=name,
                objective=objective,
                window=window,
                total=_expression(raw, "total", where, required=True),
                good=good,
                errors=errors,
                description=_text(raw.get("description"), where, "description", required=False) or name,
                runbook_url=_text(raw.get("runbook_url") or document.get("runbook_url"), where, "runbook_url", False),
                labels={str(k): str(v) for k, v in labels.items()},
                policy=_policy(raw.get("burn_rates"), where),
                severity=severity,
            )
        )
    return slos
