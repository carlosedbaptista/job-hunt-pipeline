"""Pytest bootstrap: makes agents/ and src/ importable like the CI scripts do
(they rely on sys.path tricks relative to the repo root)."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Order matters, and it is reversed on purpose: each insert(0) pushes to the
# front, so the LAST entry here ends up first on sys.path. src/ must win,
# because agents/gdrive_uploader.py is a stale duplicate of
# src/gdrive_uploader.py -- different env var names, an older Drive scope,
# and nothing imports it. With agents/ first, `import gdrive_uploader` in a
# test silently loaded the dead copy and asserted against the wrong module.
for d in (".", "agents", "src"):
    p = os.path.join(ROOT, d)
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture(autouse=True)
def _no_real_error_log(monkeypatch):
    """Every test runs against a mocked LLM; keep the resulting synthetic
    errors out of digests/evaluation_errors.txt (a real, committed log)."""
    monkeypatch.setattr("job_evaluator.log_error", lambda msg: None)

