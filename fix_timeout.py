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

print("=== HOTFIX: Timeout 45s + prompt menor ===")

# 1. kimi_client.py — timeout 45s + timeout explícito no post
print("\n[1/2] kimi_client.py...")
with open(f"{REPO}/src/kimi_client.py", "r", encoding="utf-8") as f:
    c = f.read()

c = c.replace(
    'self.client = httpx.Client(timeout=90.0)',
    'self.client = httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0, read=45.0))'
)
c = c.replace(
    'r = self.client.post(url, headers=headers, json=payload)',
    'r = self.client.post(url, headers=headers, json=payload, timeout=45.0)'
)
wf(f"{REPO}/src/kimi_client.py", c)

# 2. job_evaluator.py — batch de 2 + desc 150 chars + fallback skip
print("[2/2] job_evaluator.py...")
with open(f"{REPO}/agents/job_evaluator.py", "r", encoding="utf-8") as f:
    c = f.read()

c = c.replace(
    'desc = job.get("descricao", job.get("description", ""))[:300]',
    'desc = job.get("descricao", job.get("description", ""))[:150]'
)
c = c.replace(
    '    BATCH_SIZE = 3',
    '    BATCH_SIZE = 2'
)
c = c.replace(
    'print(f"Loaded {len(jobs)} jobs. Mini-batches of 3...\\n")',
    'print(f"Loaded {len(jobs)} jobs. Mini-batches of 2...\\n")'
)

# Substitui fallback_individual completo
old = '''def fallback_individual(jobs):
    print("  -> Fallback individual...")
    evaluations = []
    for i, job in enumerate(jobs):
        title = job.get("titulo", job.get("title", "Unknown"))[:40]
        print(f"    [{i+1}/{len(jobs)}] {title}...", end=" ", flush=True)
        try:
            ev = evaluate_single(job)
            evaluations.append(ev); print(f"score={ev.get('score','?')}")
        except Exception as e:
            print(f"ERRO: {str(e)[:50]}")
            evaluations.append({"empresa": job.get("empresa", job.get("company","")), "titulo": title, "url": job.get("url",""), "score": 50, "decision": "REVIEW", "technical_fit": "Error", "contextual_fit": "Error", "salary_estimate": "Not disclosed", "culture_fit": "Unknown", "concerns": [str(e)[:80]], "materials_needed": ["cv"], "portuguese_comment": "Erro"})
    return evaluations'''

new = '''def fallback_individual(jobs):
    print("  -> API lenta. Atribuindo REVIEW padrao para", len(jobs), "jobs.")
    evaluations = []
    for job in jobs:
        evaluations.append({
            "empresa": job.get("empresa", job.get("company","")),
            "titulo": job.get("titulo", job.get("title", "Unknown")),
            "url": job.get("url",""),
            "score": 55, "decision": "REVIEW",
            "technical_fit": "Nao avaliado (API timeout)",
            "contextual_fit": "Nao avaliado (API timeout)",
            "salary_estimate": "Not disclosed", "culture_fit": "Nao avaliado",
            "concerns": ["API Kimi timeout — verificar manualmente"],
            "materials_needed": ["cv"],
            "portuguese_comment": "API lenta — verificar vaga manualmente no link"
        })
    return evaluations'''

c = c.replace(old, new)
wf(f"{REPO}/agents/job_evaluator.py", c)

# Commit e push
print("\nCommitando...")
for cmd in [
    f"cd {REPO} && git add -A",
    f'cd {REPO} && git commit -m "fix: timeout 45s + batch 2 + prompt menor + skip fallback"',
    f"cd {REPO} && git push origin main",
]:
    ok, out, err = run(cmd)
    print(f"  {'OK' if ok else 'ERRO'}: {out[:60] if out else err[:80]}")

print("\n=== PRONTO ===")
print("Rode o workflow no GitHub Actions.")
