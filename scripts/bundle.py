# scripts/bundle.py
"""bundle:deploy [target] and bundle:run <job> [target] -- the workspace, governed (D.91).

THE RAW TASKS CHECKED NOTHING. They ran databricks directly, so a deploy missing a required
variable failed inside the CLI with its generic message, and nothing said where the value
belongs. Here the target and every variable the bundle requires are observed first, and
runs.bundle_task judges them: an undeclared target, or a variable with no default that the
target does not set and the environment lacks, is refused before anything runs, naming
BUNDLE_VAR_<name> and the user-level mise config, where a personal value stays out of git.

THE PLAN IS DATA. commands() returns the exact argv run, so policy judges what will happen,
not a description of it: a deploy validates --strict first, on the same target.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import yaml
from pydantic import Field, JsonValue

from command_outcome import announce
from contract_base import Contract, Reading
from spine import decide, enforce, evaluate, halted, reasons, refusal_code, schema_verdict

ROOT = Path(__file__).resolve().parent.parent
SUBJECT = "bundle_task"
POLICY = ROOT / "policies" / "runs" / "bundle_task"
ENTRYPOINT = "data.runs.bundle_task.deny"
USAGE = "usage: mise run run bundle:deploy [target]  |  mise run run bundle:run <job> [target]"


class _Variable(Reading):
    default: JsonValue = None


class _Target(Reading):
    variables: dict[str, JsonValue] = Field(default_factory=dict)


class _Bundle(Reading):
    targets: dict[str, _Target] = Field(default_factory=dict)
    variables: dict[str, _Variable] = Field(default_factory=dict)


class _FieldChange(Reading):
    action: str = ""
    old: JsonValue = None
    new: JsonValue = None


class _PlannedResource(Reading):
    action: str
    changes: dict[str, _FieldChange] = Field(default_factory=dict)


class _Plan(Reading):
    """bundle plan -o json: each resource key, its action, and each field it changes."""

    plan: dict[str, _PlannedResource] = Field(default_factory=dict)


class FieldChange(Contract):
    """One field the plan changes, with its value before and after (D.251)."""

    field: str
    action: str
    old: JsonValue = None
    new: JsonValue = None


class PlannedChange(Contract):
    """One resource the plan touches, and each field it changes (D.251)."""

    resource: str
    action: str
    changes: tuple[FieldChange, ...] = ()


class BundleRequest(Contract):
    """What a bundle task observed: facts only, judged by runs.bundle_task (D.91, D.251)."""

    action: str
    target: str
    target_declared: bool
    unset: tuple[str, ...]
    commands: tuple[tuple[str, ...], ...]
    planned: tuple[PlannedChange, ...] = ()


def commands(
    action: str, target: str, job: str | None, plan: str | None = None
) -> tuple[tuple[str, ...], ...]:
    """The exact commands a task runs: a deploy validates strictly first, on its target.

    Given a plan file, the deploy applies exactly that plan (D.251), never a fresh one.
    """
    if action == "deploy":
        deploy = ("databricks", "bundle", "deploy", "-t", target)
        return (
            ("databricks", "bundle", "validate", "--strict", "-t", target),
            (*deploy, "--plan", plan) if plan else deploy,
        )
    return (("databricks", "bundle", "run", "-t", target, job or ""),)


def _unset(bundle: _Bundle, target: str, environ: Mapping[str, str]) -> tuple[str, ...]:
    """Variables with no default that the target does not set and the environment lacks."""
    declared = bundle.targets[target].variables if target in bundle.targets else {}
    return tuple(
        sorted(
            name
            for name, variable in bundle.variables.items()
            if "default" not in variable.model_fields_set
            and name not in declared
            and not environ.get(f"BUNDLE_VAR_{name}")
        )
    )


def observe(
    root: Path, action: str, target: str, job: str | None, environ: Mapping[str, str]
) -> BundleRequest:
    """Everything the decision needs, read before anything runs."""
    text = (root / "databricks.yml").read_text(encoding="utf-8")
    bundle = _Bundle.model_validate(yaml.safe_load(text))
    return BundleRequest(
        action=action,
        target=target,
        target_declared=target in bundle.targets,
        unset=_unset(bundle, target, environ),
        commands=commands(action, target, job),
    )


def _run(argv: tuple[str, ...]) -> int:
    """One command, its output streamed to the console as the raw task's was."""
    return subprocess.run(argv, check=False).returncode


def plan_command(target: str) -> tuple[str, ...]:
    """The plan of what a deploy would change, as data (D.251)."""
    return ("databricks", "bundle", "plan", "-t", target, "-o", "json")


def _read(argv: tuple[str, ...]) -> str:
    """One command whose output is data: captured, and an exit other than 0 raises."""
    return subprocess.run(argv, check=True, capture_output=True, text=True).stdout


def _planned(text: str) -> tuple[PlannedChange, ...]:
    """Each resource the plan touches and each field it changes, read straight into a model."""
    plan = _Plan.model_validate_json(text)
    return tuple(
        PlannedChange(
            resource=key,
            action=entry.action,
            changes=tuple(
                FieldChange(field=name, action=change.action, old=change.old, new=change.new)
                for name, change in entry.changes.items()
            ),
        )
        for key, entry in plan.plan.items()
    )


def _failed(
    planned: Sequence[tuple[str, ...]], run: Callable[[tuple[str, ...]], int]
) -> str | None:
    """The first command that exits other than 0, as a reason; None when all succeed."""
    for argv in planned:
        returned = run(argv)
        if returned != 0:
            return f"{' '.join(argv)} exited {returned}"
    return None


def _deploy(
    root: Path,
    request: BundleRequest,
    run: Callable[[tuple[str, ...]], int],
    read: Callable[[tuple[str, ...]], str],
) -> int:
    """Validate, read the plan as data, judge it, then deploy exactly that plan (D.251)."""
    command, target = "bundle:deploy", request.target
    observed = request.model_dump(mode="json")
    failure = _failed(request.commands[:1], run)
    if failure is not None:
        stopped = halted(SUBJECT, ENTRYPOINT, POLICY, failure)
        return enforce(announce(command, stopped, "bundle_command_failed", failure, observed))
    try:
        text = read(plan_command(target))
        planned = _planned(text)
        plan_file = root / ".artifacts" / "bundle" / f"{target}.plan.json"
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        plan_file.write_text(text, encoding="utf-8")
    except (subprocess.SubprocessError, OSError, ValueError) as unreadable:
        reason = f"the plan could not be read: {unreadable}"
        stopped = halted(SUBJECT, ENTRYPOINT, POLICY, reason)
        return enforce(announce(command, stopped, "evidence_unreadable", reason, observed))
    judged = BundleRequest(
        action=request.action,
        target=target,
        target_declared=request.target_declared,
        unset=request.unset,
        commands=commands("deploy", target, None, str(plan_file)),
        planned=planned,
    )
    observed = judged.model_dump(mode="json")
    found = evaluate(judged, SUBJECT, POLICY, ENTRYPOINT)
    decision = decide(found)
    if decision.action != "proceed":
        code = refusal_code(decision, "bundle_refused")
        return enforce(announce(command, decision, code, reasons(found), observed))
    failure = _failed(judged.commands[1:], run)
    if failure is not None:
        stopped = halted(SUBJECT, ENTRYPOINT, POLICY, failure)
        return enforce(announce(command, stopped, "bundle_command_failed", failure, observed))
    message = f"{command} {target}: validated, {len(planned)} resource(s) planned, deployed"
    return enforce(announce(command, decision, "bundle_done", message, observed))


def _parse(args: list[str]) -> tuple[str, str, str | None] | None:
    if args[:1] == ["deploy"] and len(args) in (1, 2):
        return "deploy", args[1] if len(args) == 2 else "dev", None
    if args[:1] == ["run"] and len(args) in (2, 3):
        return "run", args[2] if len(args) == 3 else "dev", args[1]
    return None


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path = ROOT,
    environ: Mapping[str, str] | None = None,
    run: Callable[[tuple[str, ...]], int] = _run,
    read: Callable[[tuple[str, ...]], str] = _read,
) -> int:
    """bundle.py deploy [target] | run <job> [target] -- observe, judge, then run or refuse."""
    parsed = _parse(list(sys.argv[1:] if argv is None else argv))
    if parsed is None:
        rejected = schema_verdict(SUBJECT, BundleRequest, USAGE)
        return enforce(announce("bundle", decide(rejected), "usage_invalid", reasons(rejected), {}))
    action, target, job = parsed
    command = f"bundle:{action}"
    try:
        request = observe(root, action, target, job, os.environ if environ is None else environ)
    except (OSError, ValueError, yaml.YAMLError) as unreadable:
        reason = f"the bundle could not be read: {unreadable}"
        stopped = halted(SUBJECT, ENTRYPOINT, POLICY, reason)
        return enforce(announce(command, stopped, "evidence_unreadable", reason, {}))
    observed = request.model_dump(mode="json")
    found = evaluate(request, SUBJECT, POLICY, ENTRYPOINT)
    decision = decide(found)
    if decision.action != "proceed":
        code = refusal_code(decision, "bundle_refused")
        return enforce(announce(command, decision, code, reasons(found), observed))
    if action == "deploy":
        return _deploy(root, request, run, read)
    failure = _failed(request.commands, run)
    if failure is not None:
        stopped = halted(SUBJECT, ENTRYPOINT, POLICY, failure)
        return enforce(announce(command, stopped, "bundle_command_failed", failure, observed))
    message = f"{command} {target}: {len(request.commands)} command(s) succeeded"
    return enforce(announce(command, decision, "bundle_done", message, observed))


if __name__ == "__main__":
    raise SystemExit(main())
