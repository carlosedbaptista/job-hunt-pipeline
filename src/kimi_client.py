"""
kimi_client.py -- Kimi client with ThreadPool timeout and multi-endpoint
Primary: kimi-k2.6 (moonshot-v1-* sunsets on 2026-08-31) | Fallback: moonshot-v1-8k
Fix: model was "kimi-k2-6" (invalid) -> "kimi-k2.6" (correct)
"""
import json
import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dotenv import load_dotenv

load_dotenv()

KIMI_API_KEY = os.environ.get("KIMI_API_KEY", "")
# Try international endpoint first, then China.
# Set KIMI_BASE_URL to force the platform where YOUR key was created
# (a .cn key returns 401 on .ai and vice versa).
KIMI_BASE_URLS = [
    os.environ.get("KIMI_BASE_URL") or "https://api.moonshot.ai/v1",
    "https://api.moonshot.cn/v1",
]
# moonshot-v1-* sunsets on 2026-08-31 -> kimi-k2.6 becomes the primary
KIMI_MODEL_PRIMARY = os.environ.get("KIMI_MODEL", "kimi-k2.6")
KIMI_MODEL_FALLBACK = "moonshot-v1-8k"  # FIX: was "kimi-k2-6" (with hyphen) - invalid!

# Deprecated models (for reference/debug)
DEPRECATED_MODELS = ["kimi-k2-6", "kimi-k2", "kimi-k2-0905-preview", "kimi-k2-0711-preview",
                     "kimi-k2-turbo-preview", "kimi-k2-thinking", "kimi-k2-thinking-turbo", "kimi-latest"]


class KimiClient:
    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key or KIMI_API_KEY
        self.base_urls = [base_url] if base_url else KIMI_BASE_URLS
        self.session = requests.Session()
        if not self.api_key:
            raise ValueError("KIMI_API_KEY not configured. Check https://platform.moonshot.ai or https://platform.kimi.com")

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
                        print(f"  [Kimi] 401 at URL {base_url}: {err}")
                        if "exceeded current quota" in err.lower():
                            print("  [Kimi] -> Account has no balance/credits. Check billing at platform.moonshot.ai")
                        elif "not active" in err.lower():
                            print("  [Kimi] -> Account suspended. Check platform.moonshot.ai")
                        else:
                            print("  [Kimi] -> Incorrect API key or wrong platform (try the other URL)")
                        continue  # Try next URL
                    if r.status_code == 404:
                        err_body = r.text[:200]
                        model_in_payload = payload.get("model", "")
                        if model_in_payload in DEPRECATED_MODELS or "kimi-k2-6" in model_in_payload:
                            print(f"  [Kimi] 404: model '{model_in_payload}' was DISCONTINUED on 2026-05-25.")
                            print(f"  [Kimi] -> Use a valid model: kimi-k2.6 (current). kimi-k2.5 and moonshot-v1-* sunset on 2026-08-31")
                        else:
                            print(f"  [Kimi] 404 at URL {base_url}: {err_body}")
                        r.raise_for_status()
                    r.raise_for_status()
                    return r.json()
                except FutureTimeout:
                    last_error = TimeoutError(f"Kimi API: {timeout_sec}s timeout")
                    continue
        raise last_error or RuntimeError("Kimi API: all URLs failed")

    def _try_model(self, model, messages, max_tokens, response_format, temperature=None):
        payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if response_format:
            payload["response_format"] = response_format
        if temperature is not None:
            payload["temperature"] = temperature
        # kimi-k2.* models think by default and reasoning tokens eat the
        # max_tokens budget, which can leave "content" empty (JSONDecodeError).
        # Disable thinking: this pipeline needs short, structured outputs.
        if str(model).startswith("kimi-k2"):
            payload["thinking"] = {"type": "disabled"}
        data = self._post("/chat/completions", payload, timeout_sec=60)
        return data["choices"][0]["message"]["content"]

    def chat(self, messages, model=None, max_tokens=1000, response_format=None, temperature=None):
        models_to_try = [model] if model else [KIMI_MODEL_PRIMARY, KIMI_MODEL_FALLBACK]
        last_error = None
        for m in models_to_try:
            if m is None:
                continue
            for attempt in range(2):
                try:
                    return self._try_model(m, messages, max_tokens, response_format, temperature)
                except Exception as e:
                    last_error = e
                    error_str = str(e).lower()
                    if "404" in error_str and ("not found" in error_str or "descontinuado" in error_str):
                        print(f"  [Kimi] Model {m} not found (404), trying next...")
                        break
                    print(f"  [Kimi] Error ({attempt+1}/2) with {m}: {str(e)[:120]}")
                    if attempt < 1:
                        time.sleep(2)
        raise RuntimeError(f"Kimi failed after all models: {last_error}")


def test_api_key():
    """Tests whether the API key works with a simple call."""
    try:
        client = KimiClient()
        result = client.chat(
            messages=[{"role": "user", "content": "Hi"}],
            model=KIMI_MODEL_PRIMARY,
            max_tokens=10
        )
        print(f"[Kimi] API key OK! Response: {result[:50]}...")
        return True
    except Exception as e:
        print(f"[Kimi] API key FAILED: {e}")
        print("[Kimi] -> Check your key at https://platform.moonshot.ai")
        return False


def call_kimi(prompt, system=None, max_tokens=4096, response_format=None, temperature=None):
    client = KimiClient()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return client.chat(messages, max_tokens=max_tokens, response_format=response_format, temperature=temperature)


def call_kimi_json(prompt, system=None, max_tokens=4096, temperature=None):
    import json as _json
    raw = call_kimi(prompt, system=system, max_tokens=max_tokens, response_format={"type": "json_object"}, temperature=temperature)
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) > 2:
            text = "\n".join(lines[1:-1]).strip()
        else:
            text = text.replace("```json", "").replace("```", "").strip()
    return _json.loads(text)
