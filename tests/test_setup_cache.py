# tests/test_setup_cache.py
"""setup refills uv's cache in the running uv's format, for every group the lock pins (D.253).

uv 0.13.0 changed the format of many cache entries, so after a lock refresh landed it, every
generated-gate fixture failed its offline sync: the wheels uv 0.12 cached could not be reused,
and setup's uv sync --locked found the venv current and fetched nothing. Reinstalling every
group installs each pinned package from the running uv's cache, downloading what it lacks.
--locked stays, so a stale lock is still refused and never rewritten (D.9). The line is
matched whole, so a flag that forbade the download, such as --offline, cannot slip in.
"""

from __future__ import annotations

from test_lockfile_drift import bodies

SYNC = "uv sync --locked --all-groups --reinstall"


def test_setup_refills_the_cache_for_every_group() -> None:
    body = bodies()["setup"]
    assert SYNC in body.splitlines(), body
