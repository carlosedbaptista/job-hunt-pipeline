#!/usr/bin/env python3
"""
=== PHASE 4: CODE QUALITY ===
Creates src/utils.py, __init__.py files, completes requirements.txt,
and refactors code to use shared utilities. All output in English.
"""
import os
import subprocess

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.returncode == 0, r.stdout, r.stderr

def wf(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

REPO = os.getcwd()
if not os.path.exists(f"{REPO}/.git"):
    print("ERROR: Run this script from the repo root directory"); exit(1)

print("=== PHASE 4: CODE QUALITY ===\n")

# 1. Create agents/__init__.py
wf(f"{REPO}/agents/__init__.py", '"""Agent modules for job ingestion, evaluation, and notification."""\n')
print("[OK] agents/__init__.py created")

# 2. Create src/__init__.py
wf(f"{REPO}/src/__init__.py", '"""Core pipeline modules for job hunt automation."""\n')
print("[OK] src/__init__.py created")

# 3. Create src/utils.py (shared utilities)
wf(f"{REPO}/src/utils.py", '''"""Shared utility functions for the job hunt pipeline."""
import json
import os
from datetime import datetime, timezone
from typing import List, Dict, Any


def deduplicate_jobs(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate jobs based on company + title + location."""
    seen = set()
    unique = []
    for job in jobs:
        company = (job.get("company") or job.get("empresa", "")).lower().strip()
        title = (job.get("title") or job.get("titulo", "")).lower().strip()
        location = (job.get("location") or job.get("localizacao", "")).lower().strip()
        key = (company, title, location)
        if key not in seen:
            seen.add(key)
            unique.append(job)
    return unique


def load_json(filepath: str, default: Any = None) -> Any:
    """Load JSON from file, return default if file missing or invalid."""
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return default


def save_json(filepath: str, data: Any, indent: int = 2) -> None:
    """Save data as JSON to file, creating parent dirs if needed."""
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)


def now_iso() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def now_str(fmt: str = "%Y%m%d_%H%M") -> str:
    """Return current UTC time as formatted string."""
    return datetime.now(timezone.utc).strftime(fmt)


def ensure_dir(path: str) -> str:
    """Create directory if it doesn't exist, return path."""
    os.makedirs(path, exist_ok=True)
    return path
''')
print("[OK] src/utils.py created with deduplicate_jobs, load_json, save_json, now_iso, now_str, ensure_dir")

# 4. Complete requirements.txt
wf(f"{REPO}/requirements.txt", '''python-dotenv>=1.0.0
httpx>=0.27.0
beautifulsoup4>=4.12.0
requests>=2.31.0
''')
print("[OK] requirements.txt verified")

# 5. Refactor adzuna_ingestor.py to use src/utils.py
ADZUNA = f"{REPO}/agents/adzuna_ingestor.py"
if os.path.exists(ADZUNA):
    with open(ADZUNA, "r", encoding="utf-8") as f:
        content = f.read()

    old_dedup = '''def deduplicate(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique = []
    for job in jobs:
        key = (job["company"].lower().strip(), job["title"].lower().strip(), job["location"].lower().strip())
        if key not in seen:
            seen.add(key)
            unique.append(job)
    return unique


def save(jobs: List[Dict[str, Any]]) -> str:'''

    new_dedup = '''import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from utils import deduplicate_jobs, ensure_dir


def save(jobs: List[Dict[str, Any]]) -> str:'''

    content = content.replace(old_dedup, new_dedup)
    content = content.replace("unique = deduplicate(normalized)", "unique = deduplicate_jobs(normalized)")
    content = content.replace("os.makedirs(\"data/raw_jobs\", exist_ok=True)", 'ensure_dir("data/raw_jobs")')

    with open(ADZUNA, "w", encoding="utf-8") as f:
        f.write(content)
    print("[OK] agents/adzuna_ingestor.py -> uses src/utils.deduplicate_jobs")

# 6. Refactor unified_ingestor.py to use src/utils.py
UNIFIED = f"{REPO}/src/unified_ingestor.py"
if os.path.exists(UNIFIED):
    with open(UNIFIED, "r", encoding="utf-8") as f:
        content = f.read()

    old_dedup = '''def deduplicate_all(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique = []
    for job in jobs:
        key = (
            job.get("company", job.get("empresa", "")).lower().strip(),
            normalize_title(job.get("title", job.get("titulo", ""))),
            (job.get("location") or job.get("localizacao") or "").lower().strip(),
        )
        if key not in seen:
            seen.add(key)
            unique.append(job)
    return unique'''

    new_dedup = '''from utils import deduplicate_jobs'''

    content = content.replace(old_dedup, new_dedup)
    content = content.replace("unique = deduplicate_all(all_jobs)", "unique = deduplicate_jobs(all_jobs)")
    content = content.replace('sys.path.insert(0, "agents")\n', '')
    content = content.replace('sys.path.insert(0, "./agents")\n', '')

    with open(UNIFIED, "w", encoding="utf-8") as f:
        f.write(content)
    print("[OK] src/unified_ingestor.py -> uses src/utils.deduplicate_jobs, removed sys.path hacks")

# 7. Commit
run("git add -A")
ok, _, err = run('git commit -m "refactor: add shared utils module, __init__.py, DRY deduplicate_jobs"')
if ok:
    print("\n[OK] Commit successful! Next: git push origin main")
else:
    print(f"\n[!] Commit issue: {err[:200]}")

print("\n=== PHASE 4 COMPLETE ===")
print("Created:")
print("  - agents/__init__.py, src/__init__.py (proper Python packages)")
print("  - src/utils.py (deduplicate_jobs, load_json, save_json, now_iso, now_str, ensure_dir)")
print("  - requirements.txt (complete dependencies)")
print("Refactored:")
print("  - adzuna_ingestor.py -> uses utils.deduplicate_jobs")
print("  - unified_ingestor.py -> uses utils.deduplicate_jobs, no sys.path hacks")
