"""
kimi_client.py — Cliente Kimi via requests + signal.alarm (timeout HARD 120s)
Modelo: kimi-k2.6 (com ponto) — serie k2-6 foi descontinuada em 25/05/2026
Fallback: moonshot-v1-8k se k2.6 falhar
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
KIMI_MODEL_PRIMARY = "kimi-k2.6"       # <-- CORRECAO: ponto, nao hifen
KIMI_MODEL_FALLBACK = "moonshot-v1-8k" # Fallback caso k2.6 falhe

class TimeoutError(Exception):
    pass

def _timeout_handler(signum, frame):
    raise TimeoutError("Kimi API: 120s timeout")

class KimiClient:
    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key or KIMI_API_KEY
        self.base_url = base_url or KIMI_BASE_URL
        self.session = requests.Session()
        if not self.api_key:
            raise ValueError("KIMI_API_KEY nao configurada")

    def _post(self, endpoint, payload):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        old = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(120)
        try:
            r = self.session.post(url, headers=headers, json=payload, timeout=130)
            r.raise_for_status()
            return r.json()
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)

    def _try_model(self, model, messages, max_tokens, response_format):
        """Tenta uma chamada com um modelo especifico."""
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
                    # Se for 404 de modelo nao encontrado, pula pro proximo modelo
                    if "404" in error_str and "not found" in error_str and attempt == 0:
                        print(f"  [Kimi] Modelo {m} nao encontrado (404), tentando fallback...")
                        break  # Sai do retry, vai pro proximo modelo
                    wait = 2 ** attempt
                    print(f"  [Kimi] Erro ({attempt+1}/3) com {m}: {str(e)[:80]}")
                    if attempt < 2:
                        time.sleep(wait)

        raise RuntimeError(f"Kimi falhou apos todos os modelos: {last_error}")


def call_kimi(prompt, system=None, max_tokens=4096, response_format=None):
    """Chama a API Kimi e retorna a string de resposta."""
    client = KimiClient()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return client.chat(messages, max_tokens=max_tokens, response_format=response_format)


def call_kimi_json(prompt, system=None, max_tokens=4096):
    """Chama a API Kimi e retorna a resposta parseada como JSON."""
    import json as _json
    response_format = {"type": "json_object"}
    raw = call_kimi(prompt, system=system, max_tokens=max_tokens, response_format=response_format)
    # Se vier com markdown code block, remove
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove primeira linha (```json) e ultima (```)
        if len(lines) > 2:
            text = "\n".join(lines[1:-1]).strip()
        else:
            text = text.replace("```json", "").replace("```", "").strip()
    return _json.loads(text)
