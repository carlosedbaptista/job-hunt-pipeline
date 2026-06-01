#!/usr/bin/env python3
import os, subprocess, json

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

print("=== HOTFIX: Corrige nome do modelo Kimi ===")

# Novo kimi_client.py com modelo correto + fallback
wf(f"{REPO}/src/kimi_client.py", r'''"""
kimi_client.py — Cliente Kimi. Timeout: 90s. Retry: 3x.
Modelo: kimi-k2.6 (com ponto). Fallback: moonshot-v1-8k
"""

import json
import os
import time
import httpx
from dotenv import load_dotenv

load_dotenv()

KIMI_API_KEY = os.environ.get("KIMI_API_KEY", "")
KIMI_BASE_URL = "https://api.moonshot.cn/v1"
KIMI_MODEL_PRIMARY = "kimi-k2.6"
KIMI_MODEL_FALLBACK = "moonshot-v1-8k"

class KimiClient:
    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key or KIMI_API_KEY
        self.base_url = base_url or KIMI_BASE_URL
        self.client = httpx.Client(timeout=90.0)
        if not self.api_key:
            raise ValueError("KIMI_API_KEY nao configurada")

    def _post(self, endpoint, payload):
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        r = self.client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()

    def chat(self, messages, model=None, max_tokens=4096, response_format=None):
        model = model or KIMI_MODEL_PRIMARY
        payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if response_format:
            payload["response_format"] = response_format

        last_error = None
        for attempt in range(3):
            try:
                data = self._post("/chat/completions", payload)
                return data["choices"][0]["message"]["content"]
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                body = e.response.text[:200]
                print(f"  [Kimi] HTTP {status}: {body}")
                if status == 404 and model == KIMI_MODEL_PRIMARY:
                    print(f"  [Kimi] Modelo {model} nao encontrado. Tentando fallback {KIMI_MODEL_FALLBACK}...")
                    model = KIMI_MODEL_FALLBACK
                    payload["model"] = model
                    continue
                last_error = e
                wait = 2 ** attempt
                time.sleep(wait)
            except Exception as e:
                last_error = e
                wait = 2 ** attempt
                print(f"  [Kimi] Erro ({attempt+1}/3): {str(e)[:80]}")
                time.sleep(wait)
        raise RuntimeError(f"Kimi falhou apos 3 tentativas: {last_error}")

def call_kimi(prompt, system=None, model=None, max_tokens=4096, response_format=None):
    client = KimiClient()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return client.chat(messages, model, max_tokens, response_format)

def call_kimi_json(prompt, system=None, model=None, max_tokens=4096):
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

def list_models():
    """Lista modelos disponiveis na conta."""
    client = KimiClient()
    headers = {"Authorization": f"Bearer {client.api_key}", "Content-Type": "application/json"}
    try:
        r = client.client.get(f"{client.base_url}/models", headers=headers)
        r.raise_for_status()
        data = r.json()
        models = [m.get("id", m.get("name", "unknown")) for m in data.get("data", [])]
        return models
    except Exception as e:
        print(f"  [Kimi] Erro ao listar modelos: {e}")
        return []

if __name__ == "__main__":
    print("Modelos disponiveis:")
    for m in list_models():
        print(f"  - {m}")
''')

# Atualiza o job_evaluator para usar o modelo correto
print("[1/2] Atualizando job_evaluator.py...")
with open(f"{REPO}/agents/job_evaluator.py", "r", encoding="utf-8") as f:
    c = f.read()

# Troca a importacao para nao forcar modelo antigo
if "from kimi_client import call_kimi_json" in c:
    pass  # ja esta ok

# Remove verificacao de API key que mostra parcial da key (seguranca)
c = c.replace(
    '    api_key = os.environ.get("KIMI_API_KEY", "")\n    if not api_key:\n        print("ERRO: KIMI_API_KEY nao configurada!"); return\n    print(f"API Key: {api_key[:8]}...{api_key[-4:]}")\n\n    try:',
    '    try:'
)

wf(f"{REPO}/agents/job_evaluator.py", c)

# Commit e push
print("\nCommitando...")
for cmd in [
    f"cd {REPO} && git add -A",
    f'cd {REPO} && git commit -m "fix: corrige nome do modelo Kimi para kimi-k2.6 + fallback moonshot-v1-8k"',
    f"cd {REPO} && git push origin main",
]:
    ok, out, err = run(cmd)
    print(f"  {'OK' if ok else 'ERRO'}: {out[:60] if out else err[:80]}")

print("\n=== PRONTO ===")
print("Rode o workflow no GitHub Actions novamente.")
print("Se continuar 404, execute localmente: python src/kimi_client.py")
print("para listar os modelos disponiveis na sua conta.")
