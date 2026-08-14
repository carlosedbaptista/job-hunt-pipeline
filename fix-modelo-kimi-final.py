#!/usr/bin/env python3
"""
=== FINAL HOTFIX: Fix Kimi model k2-6 -> k2.6 + fallback ===

Problem: The kimi-k2 series was discontinued on 2026-05-25.
The model 'kimi-k2-6' (with a hyphen) returns 404.
The correct name is 'kimi-k2.6' (with a dot).

This script overwrites src/kimi_client.py with the definitive fix.
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
    print("ERROR: Run this from inside the repo folder"); exit(1)

print("=== FINAL HOTFIX: Kimi model k2-6 -> k2.6 ===")

# New kimi_client.py: requests + signal.alarm + correct model + fallback
wf(f"{REPO}/src/kimi_client.py", r'''"""
kimi_client.py — Kimi client via requests + signal.alarm (HARD 45s timeout)
Model: kimi-k2.6 (with a dot) — the k2-6 series was discontinued on 2026-05-25
Fallback: moonshot-v1-8k if k2.6 fails
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
KIMI_MODEL_PRIMARY = "kimi-k2.6"       # <-- FIX: dot, not hyphen
KIMI_MODEL_FALLBACK = "moonshot-v1-8k" # Fallback in case k2.6 fails

class TimeoutError(Exception):
    pass

def _timeout_handler(signum, frame):
    raise TimeoutError("Kimi API: 45s timeout")

class KimiClient:
    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key or KIMI_API_KEY
        self.base_url = base_url or KIMI_BASE_URL
        self.session = requests.Session()
        if not self.api_key:
            raise ValueError("KIMI_API_KEY not configured")

    def _post(self, endpoint, payload):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
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

    def _try_model(self, model, messages, max_tokens, response_format):
        """Tries a call with a specific model."""
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens
        }
        if response_format:
            payload["response_format"] = response_format
        data = self._post("/chat/completions", payload)
        return data["choices"][0]["message"]["content"]

    def chat(self, messages, model=None, max_tokens=1000, response_format=None):
        models_to_try = [model] if model else [KIMI_MODEL_PRIMARY, KIMI_MODEL_FALLBACK]
        last_error = None

        for m in models_to_try:
            if m is None:
                continue
            for attempt in range(3):
                try:
                    return self._try_model(m, messages, max_tokens, response_format)
                except Exception as e:
                    last_error = e
                    error_str = str(e).lower()
                    # If it's a 404 model-not-found, skip to the next model
                    if "404" in error_str and "not found" in error_str and attempt == 0:
                        print(f"  [Kimi] Model {m} not found (404), trying fallback...")
                        break  # Exit the retry loop, move to the next model
                    wait = 2 ** attempt
                    print(f"  [Kimi] Error ({attempt+1}/3) with {m}: {str(e)[:80]}")
                    if attempt < 2:
                        time.sleep(wait)

        raise RuntimeError(f"Kimi failed after all models: {last_error}")


def call_kimi(prompt, system=None, max_tokens=1000, response_format=None):
    """Calls the Kimi API and returns the response string."""
    client = KimiClient()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return client.chat(messages, max_tokens=max_tokens, response_format=response_format)


def call_kimi_json(prompt, system=None, max_tokens=1000):
    """Calls the Kimi API and returns the response parsed as JSON."""
    import json as _json
    raw = call_kimi(prompt, system=system, max_tokens=max_tokens, response_format={"type": "json_object"})
    # If it comes wrapped in a markdown code block, strip it
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove the first line (```json) and the last one (```)
        if len(lines) > 2:
            text = "\n".join(lines[1:-1]).strip()
        else:
            text = text.replace("```json", "").replace("```", "").strip()
    return _json.loads(text)
''')

# Commit and push
print("\nCommitting...")
for cmd in [
    f"cd {REPO} && git add -A",
    f'cd {REPO} && git commit -m "FINAL fix: kimi-k2.6 model (dot) + moonshot-v1-8k fallback"',
    f"cd {REPO} && git push origin main",
]:
    ok, out, err = run(cmd)
    if ok:
        print(f"  OK")
    else:
        print(f"  ERROR: {err[:150]}")
        if "rejected" in err.lower():
            print("  Trying rebase...")
            run(f"cd {REPO} && git pull --rebase origin main")
            ok2, out2, err2 = run(f"cd {REPO} && git push origin main")
            print(f"  {'OK' if ok2 else 'ERROR'}: {err2[:100] if not ok2 else 'push done'}")

print("\n" + "=" * 60)
print("DONE!")
print("=" * 60)
print("\nBEFORE: model='kimi-k2-6'  (with hyphen) -> DISCONTINUED -> 404")
print("AFTER:  model='kimi-k2.6'  (with dot)    -> CURRENT MODEL")
print("        fallback='moonshot-v1-8k'          -> IF k2.6 FAILS")
