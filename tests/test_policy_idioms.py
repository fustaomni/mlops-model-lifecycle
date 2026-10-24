# tests/test_policy_idioms.py
"""Policies use string interpolation wherever Regal 0.43 can tell it is equivalent (D.252).

Regal 0.43.0 added prefer-string-interpolation, which reports a sprintf or concat call only when
every argument is a bound name, so interpolation can never leave the result undefined. This runs
exactly that rule, through Regal itself, over every policy. The 35 calls it reported here were
rewritten with their messages unchanged, and a new one is refused by this proof as well as by
check:policy. Files scanned and the exit code are asserted too, so an empty or failed scan can
never pass as clean.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from contract_base import Reading

ROOT = Path(__file__).resolve().parent.parent
RULE = "prefer-string-interpolation"
LINT = ("regal", "lint", "--disable-all", "--enable", RULE, "--format", "json", "policies")


class _Summary(Reading):
    files_scanned: int


class _Violation(Reading):
    title: str


class _Report(Reading):
    violations: tuple[_Violation, ...] = ()
    summary: _Summary


def test_no_policy_formats_what_interpolation_could_write() -> None:
    done = subprocess.run(LINT, cwd=ROOT, capture_output=True, text=True, check=False)
    report = _Report.model_validate_json(done.stdout)
    assert report.summary.files_scanned > 0, done.stdout
    assert [violation.title for violation in report.violations] == [], done.stdout
    assert done.returncode == 0, done.stderr
