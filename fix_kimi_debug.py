#!/usr/bin/env python3
import os, subprocess
def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.returncode == 0, r.stdout, r.stderr
def wf(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

REPO = os.getcwd()
if not os.path.exists(f"{REPO}/.git"):
    print("ERRO: Rode dentro da pasta do repo"); exit(1)

print("=== HOTFIX: Kimi debug + delay ===")

# 1. job_evaluator.py — delay entre batches + verificacao API key
print("\n[1/2] job_evaluator.py...")
with open(f"{REPO}/agents/job_evaluator.py", "r", encoding="utf-8") as f:
    c = f.read()

c = c.replace(
    "import json\nimport os\nimport sys\nfrom datetime import datetime, timezone",
    "import json\nimport os\nimport sys\nimport time\nfrom datetime import datetime, timezone"
)

c = c.replace(
    """    BATCH_SIZE = 3
    evaluations = []
    total_batches = (len(jobs) + BATCH_SIZE - 1) // BATCH_SIZE
    for i in range(0, len(jobs), BATCH_SIZE):
        print(f\"Batch {i//BATCH_SIZE + 1}/{(len(jobs) + BATCH_SIZE - 1)//BATCH_SIZE}:\")
        batch_evals = evaluate_mini_batch(jobs[i:i + BATCH_SIZE])
        evaluations.extend(batch_evals)""",
    """    BATCH_SIZE = 3
    evaluations = []
    total_batches = (len(jobs) + BATCH_SIZE - 1) // BATCH_SIZE
    for i in range(0, len(jobs), BATCH_SIZE):
        print(f\"Batch {i//BATCH_SIZE + 1}/{total_batches}:\")
        batch_evals = evaluate_mini_batch(jobs[i:i + BATCH_SIZE])
        evaluations.extend(batch_evals)
        if i + BATCH_SIZE < len(jobs):
            print(\"  Aguardando 3s...\")
            time.sleep(3)"""
)

c = c.replace(
    "def main():\n    os.makedirs(\"digests\", exist_ok=True)\n\n    try:",
    "def main():\n    os.makedirs(\"digests\", exist_ok=True)\n    api_key = os.environ.get(\"KIMI_API_KEY\", \"\")\n    if not api_key:\n        print(\"ERRO: KIMI_API_KEY nao configurada!\"); return\n    print(f\"API Key: {api_key[:8]}...{api_key[-4:]}\")\n\n    try:"
)

wf(f"{REPO}/agents/job_evaluator.py", c)

# 2. kimi_client.py — debug URL
print("[2/2] kimi_client.py...")
with open(f"{REPO}/src/kimi_client.py", "r", encoding="utf-8") as f:
    c = f.read()

c = c.replace(
    "    def _post(self, endpoint, payload):\n        headers = {\"Authorization\": f\"Bearer {self.api_key}\", \"Content-Type\": \"application/json\"}\n        url = f\"{self.base_url}/{endpoint.lstrip('/')}\"\n        r = self.client.post(url, headers=headers, json=payload)",
    "    def _post(self, endpoint, payload):\n        headers = {\"Authorization\": f\"Bearer {self.api_key}\", \"Content-Type\": \"application/json\"}\n        url = f\"{self.base_url}/{endpoint.lstrip('/')}\"\n        print(f\"  [Debug] URL: {url}\")\n        r = self.client.post(url, headers=headers, json=payload)"
)

wf(f"{REPO}/src/kimi_client.py", c)

# Commit e push
print("\nCommitando...")
for cmd in [
    f"cd {REPO} && git add -A",
    f'cd {REPO} && git commit -m "debug: delay + verificacao API key + debug URL"',
    f"cd {REPO} && git push origin main",
]:
    ok, out, err = run(cmd)
    print(f"  {'OK' if ok else 'ERRO'}: {out[:60] if out else err[:80]}")

print("\n=== PRONTO ===")
print("Verifique sua KIMI_API_KEY em https://platform.moonshot.cn")
print("Depois rode o workflow no GitHub Actions novamente.")
