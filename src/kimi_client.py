"""
kimi_client.py -- Cliente Kimi com ThreadPool timeout (confiavel no GitHub Actions)
Primario: moonshot-v1-8k (rapido, <30s)  |  Fallback: kimi-k2-6 (lento)
"""
import json
import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dotenv import load_dotenv

load_dotenv()

KIMI_API_KEY = os.environ.get("KIMI_API_KEY", "")
KIMI_BASE_URL = "https://api.moonshot.cn/v1"
KIMI_MODEL_PRIMARY = "moonshot-v1-8k"
KIMI_MODEL_FALLBACK = "kimi-k2-6"

class KimiClient:
    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key or KIMI_API_KEY
        self.base_url = base_url or KIMI_BASE_URL
        self.session = requests.Session()
        if not self.api_key:
            raise ValueError("KIMI_API_KEY nao configurada")

    def _post(self, endpoint, payload, timeout_sec=60):
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        def _do_post():
            try:
                return self.session.post(url, headers=headers, json=payload, timeout=timeout_sec + 15)
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_do_post)
            try:
                r = future.result(timeout=timeout_sec)
                if r is None:
                    raise TimeoutError("Kimi API: connection failed")
                r.raise_for_status()
                return r.json()
            except FutureTimeout:
                raise TimeoutError(f"Kimi API: {timeout_sec}s timeout")

    def _try_model(self, model, messages, max_tokens, response_format):
        payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if response_format:
            payload["response_format"] = response_format
        data = self._post("/chat/completions", payload, timeout_sec=60)
        return data["choices"][0]["message"]["content"]

    def chat(self, messages, model=None, max_tokens=1000, response_format=None):
        models_to_try = [model] if model else [KIMI_MODEL_PRIMARY, KIMI_MODEL_FALLBACK]
        last_error = None
        for m in models_to_try:
            if m is None:
                continue
            for attempt in range(2):
                try:
                    return self._try_model(m, messages, max_tokens, response_format)
                except Exception as e:
                    last_error = e
                    error_str = str(e).lower()
                    if "404" in error_str and "not found" in error_str:
                        print(f"  [Kimi] Modelo {m} nao encontrado (404), tentando proximo...")
                        break
                    print(f"  [Kimi] Erro ({attempt+1}/2) com {m}: {str(e)[:80]}")
                    if attempt < 1:
                        time.sleep(2)
        raise RuntimeError(f"Kimi falhou apos todos os modelos: {last_error}")


def call_kimi(prompt, system=None, max_tokens=4096, response_format=None):
    client = KimiClient()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return client.chat(messages, max_tokens=max_tokens, response_format=response_format)


def call_kimi_json(prompt, system=None, max_tokens=4096):
    import json as _json
    raw = call_kimi(prompt, system=system, max_tokens=max_tokens, response_format={"type": "json_object"})
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) > 2:
            text = "\n".join(lines[1:-1]).strip()
        else:
            text = text.replace("```json", "").replace("```", "").strip()
    return _json.loads(text)
