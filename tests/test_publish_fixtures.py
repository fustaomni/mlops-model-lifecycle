# tests/test_publish_fixtures.py
"""The publication gate runs the fixture check when the bundle changes, as CI does (D.234).

On 2026-10-19 check:fixtures failed locally with exactly CI's diff, yet the snapshot gate passed
the same commit: it always ran check_all --offline, and the fixture check needs Databricks
credentials. A commit that changes what the fixture is captured from now expects that check
and runs it on the snapshot, and a snapshot that skipped an expected gate is refused. Every
other commit is gated exactly as before.
"""

from __future__ import annotations

from check_all import GATES, selected
from publish_policy import PublishEvidence, expected, judge
from publish_push import plan_gates
from snapshot_gate import GATE

COMMIT = "a" * 40
TREE = "b" * 40
BUNDLE_CHANGE = ("resources/assignment_03_job.yml",)


def test_a_bundle_change_expects_the_fixture_gate() -> None:
    base = expected(())
    assert "fixtures" not in base, base
    for changed in (BUNDLE_CHANGE, ("databricks.yml",)):
        declared, command = plan_gates(changed)
        assert declared == (*base, "fixtures"), declared
        assert command == (*GATE, "--also", "fixtures"), command
    assert plan_gates(("scripts/bundle.py",)) == (base, GATE)


def test_a_snapshot_that_skipped_an_expected_gate_is_refused() -> None:
    declared, _ = plan_gates(BUNDLE_CHANGE)
    base = expected(())
    skipped = PublishEvidence(
        commit=COMMIT, tree=TREE, expected=declared, passed_tests=base, failed_tests=()
    )
    _, refused = judge(skipped)
    assert refused.action == "refuse", refused
    complete = skipped.model_copy(update={"passed_tests": declared})
    _, allowed = judge(complete)
    assert allowed.action == "proceed", allowed


def test_the_offline_gate_adds_only_the_gates_named() -> None:
    offline = {spec.name for spec in selected(GATES, hooks=True)}
    widened = {spec.name for spec in selected(GATES, hooks=True, also=("fixtures",))}
    assert "fixtures" not in offline, offline
    assert widened == offline | {"fixtures"}, widened
