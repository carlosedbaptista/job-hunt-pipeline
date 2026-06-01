#!/usr/bin/env python3
"""Corrige lentidao: mini-batches + timeout 90s + retry + batch email parsing"""

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
    print("ERRO: Rode dentro da pasta do repo"); exit(1)

print("=== HOTFIX: Mini-batches + Timeout 90s + Retry ===")

# 1. kimi_client.py — timeout 90s + retry 3x
print("\n[1/3] kimi_client.py...")
wf(f"{REPO}/src/kimi_client.py", r'''"""
kimi_client.py — Cliente Kimi K2-6. Timeout: 90s. Retry: 3x com backoff.
"""

import json
import os
import time
import httpx
from dotenv import load_dotenv

load_dotenv()

KIMI_API_KEY = os.environ.get("KIMI_API_KEY", "")
KIMI_BASE_URL = "https://api.moonshot.cn/v1"
KIMI_MODEL_DEFAULT = "kimi-k2-6"

class KimiClient:
    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key or KIMI_API_KEY
        self.base_url = base_url or KIMI_BASE_URL
        self.model = KIMI_MODEL_DEFAULT
        self.client = httpx.Client(timeout=90.0)
        if not self.api_key:
            raise ValueError("KIMI_API_KEY nao configurada")

    def _post(self, endpoint, payload):
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        r = self.client.post(f"{self.base_url}/{endpoint.lstrip('/')}", headers=headers, json=payload)
        r.raise_for_status()
        return r.json()

    def chat(self, messages, model=None, max_tokens=4096, response_format=None):
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
                time.sleep(wait)
        raise RuntimeError(f"Kimi falhou apos 3 tentativas: {last_error}")

def call_kimi(prompt, system=None, model=KIMI_MODEL_DEFAULT, max_tokens=4096, response_format=None):
    client = KimiClient()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return client.chat(messages, model, max_tokens, response_format)

def call_kimi_json(prompt, system=None, model=KIMI_MODEL_DEFAULT, max_tokens=4096):
    for attempt in range(3):
        raw = call_kimi(prompt, system, model, max_tokens, {"type": "json_object"})
        if raw and raw.strip():
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                if attempt < 2:
                    wait = 2 ** attempt
                    print(f"  [Kimi] JSON invalido, retry em {wait}s ({attempt+1}/3)...")
                    time.sleep(wait)
                    continue
                raise
        if attempt < 2:
            wait = 2 ** attempt
            print(f"  [Kimi] Vazio, retry em {wait}s ({attempt+1}/3)...")
            time.sleep(wait)
    raise RuntimeError("Kimi retornou vazio apos 3 tentativas")
''')

# 2. job_evaluator.py — mini-batches de 3
print("[2/3] job_evaluator.py...")
wf(f"{REPO}/agents/job_evaluator.py", r'''"""
job_evaluator.py — Mini-batches de 3 vagas por chamada Kimi
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from kimi_client import call_kimi_json

PROFILE = """
Candidate Profile:
- Name: Carlos Eduardo Duarte Baptista
- Role: Data and Business Analysis Professional
- Location: Wallisellen, Switzerland (Permit B)
- Notice period: 2 weeks
- Languages: PT (native), EN (C1), ES (B2), DE (A2)
- Skills: SQL, Python, Power BI, GA4, automation with AI
- Experience: QUOD (40% manual reduction), netzdenker.com (Analytics)
- Education: Postgraduate Data Science (Oct 2026), Bachelor Systems
- Certifications: Google AI Essentials, Anthropic Claude, GA4
"""

SYSTEM_PROMPT = """You are a job fit evaluator. Evaluate each job against the candidate profile.
Respond ONLY with a valid JSON array. Each element must be an object with:
{
  "empresa": "same as input", "titulo": "same as input", "url": "same as input",
  "score": 0-100, "technical_fit": "brief justification", "contextual_fit": "brief justification",
  "salary_estimate": "salary range if mentioned, else 'Not disclosed'",
  "culture_fit": "brief note", "concerns": ["list or empty"],
  "decision": "APPLY" or "REVIEW" or "SKIP",
  "materials_needed": ["cv", "cover_letter", "recommendation"],
  "portuguese_comment": "brief comment in Portuguese"
}
Scoring: >=65 APPLY, 45-64 REVIEW, <45 SKIP.
Hard constraints (auto-SKIP): NOT Zurich/Zug -> SKIP. NOT English -> SKIP. Pure SWE -> SKIP."""

def build_prompt(jobs):
    prompt = "Evaluate ALL jobs against this candidate profile:\n\n" + PROFILE + "\n\n=== JOBS ===\n\n"
    for i, job in enumerate(jobs, 1):
        title = job.get("titulo", job.get("title", "Unknown"))
        company = job.get("empresa", job.get("company", "Unknown"))
        location = job.get("localizacao", job.get("location", "Unknown"))
        desc = job.get("descricao", job.get("description", ""))[:300]
        url = job.get("url", "")
        prompt += f"\n--- JOB {i} ---\nTitle: {title}\nCompany: {company}\nLocation: {location}\nDescription: {desc}\nURL: {url}\n"
    prompt += "\n\nRespond with a JSON array of one evaluation object per job, in SAME order."
    return prompt

def evaluate_mini_batch(jobs):
    if not jobs:
        return []
    print(f"  Batch: {len(jobs)} jobs...", end=" ", flush=True)
    try:
        result = call_kimi_json(build_prompt(jobs), system=SYSTEM_PROMPT, max_tokens=3000)
        if isinstance(result, list) and len(result) == len(jobs):
            for i, ev in enumerate(result):
                ev.setdefault("empresa", jobs[i].get("empresa", jobs[i].get("company", "")))
                ev.setdefault("titulo", jobs[i].get("titulo", jobs[i].get("title", "")))
                ev.setdefault("url", jobs[i].get("url", ""))
                ev.setdefault("score", 50); ev.setdefault("decision", "REVIEW")
                ev.setdefault("technical_fit", ""); ev.setdefault("contextual_fit", "")
                ev.setdefault("salary_estimate", "Not disclosed"); ev.setdefault("culture_fit", "")
                ev.setdefault("concerns", []); ev.setdefault("materials_needed", ["cv"])
                ev.setdefault("portuguese_comment", "")
            print(f"OK (scores: {[e.get('score','?') for e in result]})")
            return result
    except Exception as e:
        print(f"ERRO: {str(e)[:80]}")
    return fallback_individual(jobs)

def fallback_individual(jobs):
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
    return evaluations

def evaluate_single(job):
    title = job.get("titulo", job.get("title", "Unknown"))
    company = job.get("empresa", job.get("company", "Unknown"))
    location = job.get("localizacao", job.get("location", "Unknown"))
    desc = job.get("descricao", job.get("description", ""))[:500]
    url = job.get("url", "")
    user_prompt = f"Evaluate this job:\nTitle: {title}\nCompany: {company}\nLocation: {location}\nDescription: {desc}\nURL: {url}\n"
    ev = call_kimi_json(user_prompt, system=SYSTEM_PROMPT, max_tokens=1500)
    ev.setdefault("empresa", company); ev.setdefault("titulo", title); ev.setdefault("url", url)
    ev.setdefault("score", 50); ev.setdefault("decision", "REVIEW")
    return ev

def main():
    os.makedirs("digests", exist_ok=True)
    try:
        with open("digests/new_jobs_latest.json", "r", encoding="utf-8") as f:
            jobs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("No jobs to evaluate."); return
    if not jobs:
        print("No jobs to evaluate."); return

    print(f"Loaded {len(jobs)} jobs. Mini-batches of 3...\n")
    BATCH_SIZE = 3
    evaluations = []
    total_batches = (len(jobs) + BATCH_SIZE - 1) // BATCH_SIZE
    for i in range(0, len(jobs), BATCH_SIZE):
        print(f"Batch {i//BATCH_SIZE + 1}/{total_batches}:")
        evaluations.extend(evaluate_mini_batch(jobs[i:i + BATCH_SIZE]))

    apply = [e for e in evaluations if e.get("score",0) >= 65]
    review = [e for e in evaluations if 45 <= e.get("score",0) < 65]
    skip = [e for e in evaluations if e.get("score",0) < 45]
    print(f"\n{'='*50}")
    print(f"COMPLETE: {len(evaluations)} jobs | APPLY: {len(apply)} | REVIEW: {len(review)} | SKIP: {len(skip)}")
    print(f"{'='*50}")

    with open("digests/job_evaluations_latest.json", "w", encoding="utf-8") as f:
        json.dump(evaluations, f, ensure_ascii=False, indent=2)
    print("Saved to digests/job_evaluations_latest.json")

if __name__ == "__main__":
    main()
''')

# 3. email_parser.py — batch de 5 emails
print("[3/3] email_parser.py...")
wf(f"{REPO}/agents/email_parser.py", r'''"""
email_parser.py — Batch parsing: 5 emails por chamada Kimi
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from kimi_client import call_kimi_json

SYSTEM_PROMPT = """You are a job extraction assistant. Extract job listings from job alert emails.
For each job: company, title, location, description (max 300 chars), url, source.
Respond ONLY with a valid JSON array of job objects.
If no jobs found, return []."""

def parse_batch(emails):
    if not emails:
        return []
    combined = ""
    for i, email in enumerate(emails[:5], 1):
        subject = email.get("subject", "No subject")
        from_addr = email.get("from", "Unknown")
        preview = email.get("snippet", "")
        body = (email.get("html_body", "") or email.get("text_body", ""))[:1500]
        combined += f"\n=== EMAIL {i} ===\nSubject: {subject}\nFrom: {from_addr}\nPreview: {preview}\nContent: {body}\n"

    prompt = f"Extract ALL job listings from these emails. For each: company, title, location, description, url, source.\n\n{combined}\n\nReturn JSON array of ALL jobs found."
    try:
        result = call_kimi_json(prompt, system=SYSTEM_PROMPT, max_tokens=4000)
        if isinstance(result, list):
            for job in result:
                job.setdefault("url", ""); job.setdefault("portal", job.get("source", "email"))
                job.setdefault("idioma", "en"); job.setdefault("data_post", datetime.now(timezone.utc).isoformat())
            return result
    except Exception as e:
        print(f"  Batch failed: {str(e)[:80]}")
    return []

def main():
    os.makedirs("digests", exist_ok=True)
    try:
        with open("digests/raw_emails_full.json", "r", encoding="utf-8") as f:
            emails = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("No emails to parse."); return
    if not emails:
        print("No emails to parse."); return

    print(f"Parsing {len(emails)} emails in batch mode...\n")
    all_jobs = []
    chunk_size = 5
    for i in range(0, len(emails), chunk_size):
        chunk = emails[i:i + chunk_size]
        print(f"  Chunk {i//chunk_size + 1}/{(len(emails) + chunk_size - 1)//chunk_size}: {len(chunk)} emails...", end=" ", flush=True)
        jobs = parse_batch(chunk)
        all_jobs.extend(jobs); print(f"{len(jobs)} jobs")

    print(f"\nTotal: {len(all_jobs)} jobs from {len(emails)} emails")
    with open("digests/parsed_jobs_latest.json", "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
''')

# Commit e push
print("\nCommitando...")
for cmd in [
    f"cd {REPO} && git add -A",
    f'cd {REPO} && git commit -m "perf: mini-batches + timeout 90s + retry + batch email parsing"',
    f"cd {REPO} && git push origin main",
]:
    ok, out, err = run(cmd)
    if ok:
        print(f"  OK: {out[:80] if out else 'done'}")
    else:
        print(f"  ERRO: {err[:150]}")

print("\n" + "=" * 50)
print("HOTFIX APLICADO! RODE O WORKFLOW NO GITHUB.")
print("Tempo esperado: 3-5 minutos (era 15-20min)")
print("=" * 50)
