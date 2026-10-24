# tests/test_bundle_plan.py
"""bundle:deploy reads the plan first, records what it changes, refuses a deletion (D.251).

On 2026-10-19 a deploy updated Assignment 1's schema and raw volume though nothing in that work
touched them, and nothing recorded which fields changed. bundle plan -o json reports each
resource's action and each field's old and new values. The deploy now reads it between
validate and deploy, judges it, records it, and applies exactly that plan with --plan.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from bundle import main

BUNDLE = "\n".join(
    (
        "bundle:",
        "  name: probe",
        "targets:",
        "  dev:",
        "    default: true",
        "variables:",
        "  catalog:",
        "    default: probe_catalog",
        "",
    )
)
COMMENT_CHANGE = {
    "plan": {
        "resources.schemas.assignment_01": {
            "action": "update",
            "changes": {"comment": {"action": "update", "old": "before", "new": "after"}},
        }
    }
}


def _deploy(tmp_path: Path, plan: Mapping[str, object]) -> tuple[int, list[tuple[str, ...]]]:
    (tmp_path / "databricks.yml").write_text(BUNDLE, encoding="utf-8")
    events: list[tuple[str, ...]] = []

    def run(argv: tuple[str, ...]) -> int:
        events.append(argv)
        return 0

    def read(argv: tuple[str, ...]) -> str:
        events.append(argv)
        return json.dumps(plan)

    code = main(["deploy", "dev"], root=tmp_path, environ={}, run=run, read=read)
    return code, events


def test_a_deploy_reads_the_plan_before_it_deploys(tmp_path: Path) -> None:
    code, events = _deploy(tmp_path, COMMENT_CHANGE)
    assert code == 0
    assert [argv[2] for argv in events] == ["validate", "plan", "deploy"], events
    assert {argv[argv.index("-t") + 1] for argv in events} == {"dev"}, events
    deploy = events[2]
    plan_file = Path(deploy[deploy.index("--plan") + 1])
    assert json.loads(plan_file.read_text(encoding="utf-8")) == COMMENT_CHANGE


def test_a_plan_that_deletes_a_resource_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A delete or a recreate loses data: refused after the plan, before anything deploys."""
    for action in ("delete", "recreate"):
        doomed = {"plan": {"resources.volumes.assignment_01_raw": {"action": action}}}
        code, events = _deploy(tmp_path, doomed)
        assert code == 2, action
        assert [argv[2] for argv in events] == ["validate", "plan"], events
        assert "ERR_BUNDLE_TASK_DESTRUCTIVE" in json.loads(capsys.readouterr().out)["message"]


def test_every_planned_change_is_recorded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _ = _deploy(tmp_path, COMMENT_CHANGE)
    assert code == 0
    planned = json.loads(capsys.readouterr().out)["data"]["planned"]
    assert planned == [
        {
            "resource": "resources.schemas.assignment_01",
            "action": "update",
            "changes": [{"field": "comment", "action": "update", "old": "before", "new": "after"}],
        }
    ], planned
