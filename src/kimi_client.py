"""
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
