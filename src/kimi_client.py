"""
kimi_client.py -- Cliente Kimi com ThreadPool timeout e multi-endpoint
Primario: moonshot-v1-8k (rapido) | Fallback: kimi-k2.6 (inteligente)
Correcao: modelo era "kimi-k2-6" (invalido) -> "kimi-k2.6" (correto)
"""
import json
import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dotenv import load_dotenv

load_dotenv()

KIMI_API_KEY = os.environ.get("KIMI_API_KEY", "")
# Tenta endpoint internacional primeiro, depois China
KIMI_BASE_URLS = [
    os.environ.get("KIMI_BASE_URL", "https://api.moonshot.ai/v1"),
    "https://api.moonshot.cn/v1",
]
KIMI_MODEL_PRIMARY = "moonshot-v1-8k"
KIMI_MODEL_FALLBACK = "kimi-k2.6"  # CORRECAO: era "kimi-k2-6" (com hifen) - invalido!

# Modelos descontinuados (para referencia/debug)
DEPRECATED_MODELS = ["kimi-k2-6", "kimi-k2", "kimi-k2-0905-preview", "kimi-k2-0711-preview",
                     "kimi-k2-turbo-preview", "kimi-k2-thinking", "kimi-k2-thinking-turbo", "kimi-latest"]


class KimiClient:
    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key or KIMI_API_KEY
        self.base_urls = [base_url] if base_url else KIMI_BASE_URLS
        self.session = requests.Session()
        if not self.api_key:
            raise ValueError("KIMI_API_KEY nao configurada. Verifique em https://platform.moonshot.ai ou https://platform.kimi.com")

    def _post(self, endpoint, payload, timeout_sec=60):
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        last_error = None
        for base_url in self.base_urls:
            url = f"{base_url}/{endpoint.lstrip('/')}"

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
                        continue
                    if r.status_code == 401:
                        err = r.json().get("error", {}).get("message", "Invalid Authentication")
                        print(f"  [Kimi] 401 na URL {base_url}: {err}")
                        if "exceeded current quota" in err.lower():
                            print("  [Kimi] -> Conta sem saldo/creditos. Verifique billing em platform.moonshot.ai")
                        elif "not active" in err.lower():
                            print("  [Kimi] -> Conta suspensa. Verifique em platform.moonshot.ai")
                        else:
                            print("  [Kimi] -> API key incorreta ou plataforma errada (tente a outra URL)")
                        continue  # Tenta proxima URL
                    if r.status_code == 404:
                        err_body = r.text[:200]
                        model_in_payload = payload.get("model", "")
                        if model_in_payload in DEPRECATED_MODELS or "kimi-k2-6" in model_in_payload:
                            print(f"  [Kimi] 404: modelo '{model_in_payload}' foi DESCONTINUADO em 25/05/2026.")
                            print(f"  [Kimi] -> Use um dos modelos validos: moonshot-v1-8k, moonshot-v1-32k, kimi-k2.5, kimi-k2.6")
                        else:
                            print(f"  [Kimi] 404 na URL {base_url}: {err_body}")
                        r.raise_for_status()
                    r.raise_for_status()
                    return r.json()
                except FutureTimeout:
                    last_error = TimeoutError(f"Kimi API: {timeout_sec}s timeout")
                    continue
        raise last_error or RuntimeError("Kimi API: todas as URLs falharam")

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
                    if "404" in error_str and ("not found" in error_str or "descontinuado" in error_str):
                        print(f"  [Kimi] Modelo {m} nao encontrado (404), tentando proximo...")
                        break
                    print(f"  [Kimi] Erro ({attempt+1}/2) com {m}: {str(e)[:120]}")
                    if attempt < 1:
                        time.sleep(2)
        raise RuntimeError(f"Kimi falhou apos todos os modelos: {last_error}")


def test_api_key():
    """Testa se a API key funciona com uma chamada simples."""
    try:
        client = KimiClient()
        result = client.chat(
            messages=[{"role": "user", "content": "Hi"}],
            model=KIMI_MODEL_PRIMARY,
            max_tokens=10
        )
        print(f"[Kimi] API key OK! Resposta: {result[:50]}...")
        return True
    except Exception as e:
        print(f"[Kimi] API key FALHOU: {e}")
        print("[Kimi] -> Verifique sua key em https://platform.moonshot.ai")
        return False


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
