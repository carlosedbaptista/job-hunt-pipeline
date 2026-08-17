"""Pytest bootstrap: makes agents/ and src/ importable like the CI scripts do
(they rely on sys.path tricks relative to the repo root)."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in ("src", "agents", "."):
    p = os.path.join(ROOT, d)
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture(autouse=True)
def _no_real_error_log(monkeypatch):
    """Every test runs against a mocked LLM; keep the resulting synthetic
    errors out of digests/evaluation_errors.txt (a real, committed log)."""
    monkeypatch.setattr("job_evaluator.log_error", lambda msg: None)

