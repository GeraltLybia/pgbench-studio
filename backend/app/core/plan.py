"""Run plan: RunConfig -> pgbench argv, script files, findings and required confirmations.

Used by preview, dry run and start, so the three always agree.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import LimitsSettings
from app.core.command import BenchOptions, ScenarioRef, script_file_names
from app.core.limits import LoadShape, check_limits
from app.core.validator import validate_script
from app.schemas import BuiltinScenario, Finding, RunConfig, Scenario

# Levels that must be listed in confirmed_rules before a run or a dry run.
CONFIRM_LEVELS = frozenset({"danger", "warning"})


@dataclass(frozen=True)
class Plan:
    options: BenchOptions
    files: dict[str, str]
    findings: list[Finding]

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def required_confirmations(self) -> list[str]:
        return sorted({f.rule_id for f in self.findings if f.level in CONFIRM_LEVELS})

    def missing_confirmations(self, confirmed: list[str]) -> list[str]:
        given = set(confirmed)
        return [rule for rule in self.required_confirmations if rule not in given]


def scenario_refs(scenarios: list[Scenario]) -> tuple[list[ScenarioRef], dict[str, str]]:
    names = script_file_names([s.name for s in scenarios if not isinstance(s, BuiltinScenario)])
    refs: list[ScenarioRef] = []
    files: dict[str, str] = {}
    it = iter(names)
    for scenario in scenarios:
        if isinstance(scenario, BuiltinScenario):
            refs.append(ScenarioRef("builtin", scenario.name, scenario.weight))
        else:
            file_name = next(it)
            files[file_name] = scenario.body
            refs.append(ScenarioRef("file", file_name, scenario.weight))
    return refs, files


def script_findings(
    scenarios: list[Scenario], server_major: int | None, variables: frozenset[str]
) -> list[Finding]:
    found: list[Finding] = []
    for scenario in scenarios:
        if isinstance(scenario, BuiltinScenario):
            continue
        result = validate_script(scenario.body, server_major, variables)
        for d in result.diagnostics:
            level = {"error": "error", "danger": "danger", "warning": "attention"}[d.severity]
            found.append(
                Finding(
                    rule_id=f"sql.{d.rule or 'syntax'}@{scenario.name}:{d.line}",
                    level=level,
                    message=d.message,
                    scenario=scenario.name,
                    line=d.line,
                )
            )
    return found


def build_plan(
    config: RunConfig,
    limits: LimitsSettings,
    *,
    progress_interval_s: int,
    free_connections: int | None,
    cpu_count: int,
    server_major: int | None,
    pgbench_major: int | None,
) -> Plan:
    refs, files = scenario_refs(config.scenarios)
    options = BenchOptions(
        mode=config.mode,
        clients=config.clients,
        threads=config.threads,
        protocol=config.protocol,
        scenarios=refs,
        duration_s=config.duration_s,
        transactions=config.transactions,
        rate_tps=config.rate_tps,
        latency_limit_ms=config.latency_limit_ms,
        vacuum=config.vacuum,
        variables=[(v.name, v.value) for v in config.variables],
        detailed_log=config.detailed_log,
        sampling_rate=config.sampling_rate,
        progress_interval_s=progress_interval_s,
    )
    shape = LoadShape(
        mode=config.mode,
        clients=config.clients,
        threads=config.threads,
        duration_s=config.duration_s,
        transactions=config.transactions,
        rate_tps=config.rate_tps,
        latency_limit_ms=config.latency_limit_ms,
    )
    findings = [
        Finding(rule_id=f.rule_id, level=f.level, message=f.message, field=f.field)
        for f in check_limits(
            shape,
            limits,
            free_connections=free_connections,
            cpu_count=cpu_count,
            server_major=server_major,
            pgbench_major=pgbench_major,
        )
    ]
    variables = frozenset(v.name for v in config.variables)
    findings += script_findings(config.scenarios, server_major, variables)
    return Plan(options=options, files=files, findings=findings)
