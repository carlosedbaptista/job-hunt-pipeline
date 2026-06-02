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

print("=== HOTFIX DEFINITIVO ===")

# 1. kimi_client.py — requests + signal.alarm(45)
print("\n[1/2] kimi_client.py...")
wf(f"{REPO}/src/kimi_client.py", r'''"""
kimi_client.py — Cliente Kimi via requests + signal.alarm (timeout HARD 45s)
"""
import json
import os
import signal
import time
import requests
from dotenv import load_dotenv

load_dotenv()

KIMI_API_KEY = os.environ.get("KIMI_API_KEY", "")
KIMI_BASE_URL = "https://api.moonshot.cn/v1"
KIMI_MODEL_DEFAULT = "kimi-k2-6"

class TimeoutError(Exception):
    pass

def _timeout_handler(signum, frame):
    raise TimeoutError("Kimi API: 45s timeout")

class KimiClient:
    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key or KIMI_API_KEY
        self.base_url = base_url or KIMI_BASE_URL
        self.model = KIMI_MODEL_DEFAULT
        self.session = requests.Session()
        if not self.api_key:
            raise ValueError("KIMI_API_KEY nao configurada")

    def _post(self, endpoint, payload):
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        old = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(45)
        try:
            r = self.session.post(url, headers=headers, json=payload, timeout=50)
            r.raise_for_status()
            return r.json()
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)

    def chat(self, messages, model=None, max_tokens=1000, response_format=None):
        model = model or self.model
        payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if response_format:
            payload["response_format"] = response_format
        last_error = None
        for attempt in range(3):
            try:
                data = self._post("/chat/completions", payload)
                return data["choices"][0]["message"]["content"]
            except Exception as e:
                last_error = e
                wait = 2 ** attempt
                print(f"  [Kimi] Erro ({attempt+1}/3): {str(e)[:80]}")
                if attempt < 2:
                    time.sleep(wait)
        raise RuntimeError(f"Kimi falhou apos 3 tentativas: {last_error}")

def call_kimi(prompt, system=None, model=KIMI_MODEL_DEFAULT, max_tokens=1000, response_format=None):
    client = KimiClient()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return client.chat(messages, model, max_tokens, response_format)

def call_kimi_json(prompt, system=None, model=KIMI_MODEL_DEFAULT, max_tokens=1000):
    for attempt in range(3):
        raw = call_kimi(prompt, system, model, max_tokens, {"type": "json_object"})
        if raw and raw.strip():
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise
        if attempt < 2:
            time.sleep(2 ** attempt)
    raise RuntimeError("Kimi vazio apos 3 tentativas")
''')

# 2. job_evaluator.py — 1 vaga por chamada + prompt pequeno + delay
print("[2/2] job_evaluator.py...")
wf(f"{REPO}/agents/job_evaluator.py", r'''"""
job_evaluator.py — 1 vaga por chamada, prompt pequeno, delay 5s
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from kimi_client import call_kimi_json

PROFILE = "Candidate: Carlos Eduardo Baptista — Data/Business Analyst, Wallisellen CH (Permit B), 2 weeks notice. Skills: SQL, Python, Power BI, GA4. Languages: PT, EN(C1), ES, DE(A2)."

SYSTEM_PROMPT = """Evaluate job vs candidate. Return JSON: {"score":0-100,"technical_fit":"brief","contextual_fit":"brief","salary_estimate":"range or Not disclosed","culture_fit":"brief","concerns":[],"decision":"APPLY|REVIEW|SKIP","portuguese_comment":"PT brief"}. Rules: >=65 APPLY, 45-64 REVIEW, <45 SKIP. Auto-SKIP: not Zurich/Zug, not English, pure SWE."""

def evaluate_job(job):
    title = job.get("titulo", job.get("title", "Unknown"))
    company = job.get("empresa", job.get("company", "Unknown"))
    location = job.get("localizacao", job.get("location", "Unknown"))
    desc = job.get("descricao", job.get("description", ""))[:100]
    url = job.get("url", "")
    prompt = f"Job: {title} at {company}\nLocation: {location}\nDesc: {desc}\nURL: {url}\nEvaluate."
    try:
        ev = call_kimi_json(prompt, system=PROFILE + "\n" + SYSTEM_PROMPT, max_tokens=1000)
        ev.setdefault("empresa", company)
        ev.setdefault("titulo", title)
        ev.setdefault("url", url)
        ev.setdefault("score", 50)
        ev.setdefault("decision", "REVIEW")
        return ev
    except Exception as e:
        print(f"API timeout -> REVIEW padrao")
        return {"empresa": company, "titulo": title, "url": url, "score": 55, "decision": "REVIEW", "technical_fit": "Nao avaliado (timeout)", "contextual_fit": "Nao avaliado (timeout)", "salary_estimate": "Not disclosed", "culture_fit": "Nao avaliado", "concerns": ["API timeout"], "portuguese_comment": "Verificar manualmente no link", "materials_needed": ["cv"]}

def main():
    os.makedirs("digests", exist_ok=True)
    try:
        with open("digests/new_jobs_latest.json", "r", encoding="utf-8") as f:
            jobs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("No jobs to evaluate."); return
    if not jobs:
        print("No jobs to evaluate."); return

    print(f"Loaded {len(jobs)} jobs. 1 by 1 with 5s delay...\n")
    evaluations = []
    for i, job in enumerate(jobs, 1):
        title = job.get("titulo", job.get("title", "Unknown"))[:50]
        print(f"[{i}/{len(jobs)}] {title}...", end=" ", flush=True)
        ev = evaluate_job(job)
        evaluations.append(ev)
        print(f"score={ev.get('score','?')} ({ev.get('decision','?')})")
        if i < len(jobs):
            time.sleep(5)

    apply = [e for e in evaluations if e.get("score",0) >= 65]
    review = [e for e in evaluations if 45 <= e.get("score",0) < 65]
    skip = [e for e in evaluations if e.get("score",0) < 45]
    print(f"\n{'='*50}")
    print(f"DONE: {len(evaluations)} jobs | APPLY: {len(apply)} | REVIEW: {len(review)} | SKIP: {len(skip)}")
    print(f"{'='*50}")
    with open("digests/job_evaluations_latest.json", "w", encoding="utf-8") as f:
        json.dump(evaluations, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
''')

# Commit e push
print("\nCommitando...")
for cmd in [
    f"cd {REPO} && git add -A",
    f'cd {REPO} && git commit -m "fix DEFINITIVO: requests + signal.alarm + 1 vaga/vez"',
    f"cd {REPO} && git push origin main",
]:
    ok, out, err = run(cmd)
    print(f"  {'OK' if ok else 'ERRO'}: {out[:60] if out else err[:80]}")

print("\n" + "=" * 60)
print("PRONTO! Rode o workflow no GitHub Actions.")
print("=" * 60)
print("\nO que mudou (e por que vai funcionar):\n")
print("1. httpx -> requests (timeout confiavel, sem bug de keep-alive)")
print("2. signal.alarm(45) — o SISTEMA OPERACIONAL mata a chamada em 45s")
print("3. 1 vaga por vez — prompt pequeno = API processa rapido")
print("4. max_tokens=1000 — resposta curta = menos tempo de geracao")
print("5. Delay 5s entre chamadas — evita rate limit da API")
print("\nTempo esperado: 9 vagas × ~30s + delays = ~5min total")
