"""
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
