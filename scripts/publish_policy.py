# scripts/publish_policy.py
"""Publication is judged on the spine from declared expectations (D.178: R8, R21, R36, R62).

THE EVIDENCE IS A TEST RESULT. Each gate the snapshot ran is listed as passed, warned or
failed, in the fields of in-toto's test-result predicate (passed_tests, warned_tests,
failed_tests); nothing else about a gate is read, so an extension field never decides.

THE VERDICT IS COMPUTED, NEVER SUPPLIED. The snapshot's own pass or fail is not evidence:
runs.publish recomputes it from the lists against contracts/publish-expectations.toml, and
every declared gate must have passed, none more and none less.

NO AGENT-WRITTEN TEXT. The evidence holds the commit and tree ids and the gate lists; no
commit message, branch name or description reaches the policy, so wording cannot decide.
"""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import Field

from check_all import GateRun
from contract_base import Contract, from_document
from spine import Decision, Verdict, decide, evaluate

ROOT = Path(__file__).resolve().parent.parent
EXPECTATIONS = ROOT / "contracts" / "publish-expectations.toml"
POLICY = ROOT / "policies" / "runs" / "publish"
ENTRYPOINT = "data.runs.publish.deny"
SUBJECT = "publish"
PASSING = frozenset({"executed_passed", "reused"})


class Expectations(Contract):
    """publish-expectations/v1: the gates that must pass on the snapshot before publishing."""

    CONTRACT_ID: ClassVar[str] = "publish-expectations/v1"

    contract: Literal["publish-expectations/v1"] = "publish-expectations/v1"
    gates: tuple[str, ...] = Field(min_length=1)
    # GATE TO ITS INPUTS (D.234): expected only when a commit changes one. A plain mapping, so the
    # contract gains one optional property and no nested definition, and v1 documents stay valid.
    conditional: dict[str, tuple[str, ...]] = Field(default_factory=dict)


class PublishEvidence(Contract):
    """publish-evidence/v1: what was gated, and how each gate ended, as a test result (R36)."""

    CONTRACT_ID: ClassVar[str] = "publish-evidence/v1"

    contract: Literal["publish-evidence/v1"] = "publish-evidence/v1"
    commit: str
    tree: str
    expected: tuple[str, ...]
    passed_tests: tuple[str, ...]
    warned_tests: tuple[str, ...] = ()
    failed_tests: tuple[str, ...]


def _touches(path: str, declared: str) -> bool:
    """A changed path is a declared input itself, or lies under a declared folder."""
    return path == declared or (declared.endswith("/") and path.startswith(declared))


def expected(changed: Sequence[str] = ()) -> tuple[str, ...]:
    """The declared gates, and each conditional one whose inputs the changes touch (D.234)."""
    text = EXPECTATIONS.read_text(encoding="utf-8")
    declared = from_document(Expectations, tomllib.loads(text))
    touched = tuple(
        gate
        for gate, inputs in declared.conditional.items()
        if any(_touches(path, entry) for path in changed for entry in inputs)
    )
    return (*declared.gates, *touched)


def evidence(
    commit: str, tree: str, gates: tuple[GateRun, ...], declared: tuple[str, ...]
) -> PublishEvidence:
    """The snapshot's gate runs as passed and failed tests; a timeout is never a pass."""
    passed = tuple(ran.name for ran in gates if ran.state in PASSING)
    failed = tuple(ran.name for ran in gates if ran.state not in PASSING)
    return PublishEvidence(
        commit=commit,
        tree=tree,
        expected=declared,
        passed_tests=passed,
        failed_tests=failed,
    )


def judge(found: PublishEvidence) -> tuple[Verdict, Decision]:
    """runs.publish's verdict on the evidence, and the decision taken from it."""
    verdict = evaluate(found, SUBJECT, POLICY, ENTRYPOINT)
    return verdict, decide(verdict)
