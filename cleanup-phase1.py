#!/usr/bin/env python3
"""
=== PHASE 1: IMMEDIATE CLEANUP ===
Remove dead artifacts, move scripts to the correct folder, update .gitignore.
"""
import os
import shutil
import subprocess

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.returncode == 0, r.stdout, r.stderr

REPO = os.getcwd()
if not os.path.exists(f"{REPO}/.git"):
    print("ERROR: Run inside the repo folder"); exit(1)

print("=== PHASE 1: IMMEDIATE CLEANUP ===\n")

# 1. Create required folders
for d in ["scripts", "docs/legacy", "config", "data/history"]:
    os.makedirs(os.path.join(REPO, d), exist_ok=True)
print("[OK] Folders created: scripts/, docs/legacy/, config/, data/history/")

# 2. Remove fix_*.py and hotfix_*.py from the root
removed = []
for f in os.listdir(REPO):
    if f.startswith("fix_") and f.endswith(".py"):
        os.remove(os.path.join(REPO, f))
        removed.append(f)
    elif f.startswith("hotfix_") and f.endswith(".py"):
        os.remove(os.path.join(REPO, f))
        removed.append(f)
if removed:
    print(f"[OK] Removed {len(removed)} fix files: {', '.join(removed)}")
else:
    print("[OK] No fix files found in the root")

# 3. Remove package.json and setup-gmail.js
for f in ["package.json", "setup-gmail.js"]:
    fp = os.path.join(REPO, f)
    if os.path.exists(fp):
        os.remove(fp)
        print(f"[OK] Removed: {f}")
    else:
        print(f"[OK] Already gone: {f}")

# 4. Move debug scripts to scripts/
for f in ["debug_jsearch.py", "add_followup_columns.py"]:
    src = os.path.join(REPO, f)
    dst = os.path.join(REPO, "scripts", f)
    if os.path.exists(src):
        shutil.move(src, dst)
        print(f"[OK] Moved: {f} -> scripts/")
    else:
        print(f"[OK] Not present in root: {f}")

# 5. Move outdated .md files to docs/legacy/
legacy_docs = ["GUIDE.md", "FOLLOWUPS.md", "ANALYTICS.md"]
for f in legacy_docs:
    src = os.path.join(REPO, f)
    dst = os.path.join(REPO, "docs/legacy", f)
    if os.path.exists(src):
        shutil.move(src, dst)
        print(f"[OK] Moved: {f} -> docs/legacy/")
    else:
        print(f"[OK] Not present in root: {f}")

# 6. Update .gitignore
gitignore_path = os.path.join(REPO, ".gitignore")
if os.path.exists(gitignore_path):
    with open(gitignore_path, "r") as f:
        content = f.read()
    additions = """
# Temporary scripts and artifacts
scripts/
docs/legacy/
fix_*.py
hotfix_*.py
debug_*.py

# Fix scripts in the root (do not commit)
/*fix*.py
/*hotfix*.py
"""
    if "scripts/" not in content:
        with open(gitignore_path, "a") as f:
            f.write(additions)
        print("[OK] .gitignore updated")
    else:
        print("[OK] .gitignore already has the rules")

# 7. Stage and commit
run("git add -A")
ok, out, err = run('git commit -m "chore: cleanup dead artifacts, move legacy docs to docs/legacy/"')
if ok:
    print("\n[OK] Commit successful!")
    print("     Next step: git push origin main")
else:
    print(f"\n[!] Commit failed (maybe nothing to commit): {err[:200]}")

print("\n=== PHASE 1 COMPLETE ===")
print("Artifacts removed, folders organized, .gitignore updated.")
print("Run 'git push origin main' to push the changes.")
