"""
kimi_client.py -- Kimi (Moonshot) client with retry/backoff and multi-endpoint.
Primary: kimi-k2.6. Fallback configurable via KIMI_MODEL_FALLBACK.
NOTE: moonshot-v1-* and kimi-k2.5 sunset on 2026-08-31 -- do not use them as fallback.
"""
import os
import time
import requests
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
DEFAULT_MODEL = "kimi-k2.6"


def _model_from_env(name, default):
    """Model id from the environment, treating EMPTY as unset.

    A GitHub Actions `vars.X` that was never defined arrives as an empty
    string, not as an absent variable, so os.environ.get would hand back ""
    and every call would ask for a model called "". Same trap that once made
    a blank workflow input crash the cost guard on int("").
    """
    return (os.environ.get(name) or "").strip() or default


KIMI_MODEL_PRIMARY = _model_from_env("KIMI_MODEL", DEFAULT_MODEL)
# Fallback defaults to the primary family; override via env if Moonshot
# publishes a newer model. moonshot-v1-8k was removed: it sunsets 2026-08-31
# and a dead fallback silently kills the pipeline's resilience.
KIMI_MODEL_FALLBACK = _model_from_env("KIMI_MODEL_FALLBACK", DEFAULT_MODEL)

# Deprecated models (for reference/debug)
DEPRECATED_MODELS = ["kimi-k2-6", "kimi-k2", "kimi-k2-0905-preview", "kimi-k2-0711-preview",
                     "kimi-k2-turbo-preview", "kimi-k2-thinking", "kimi-k2-thinking-turbo", "kimi-latest",
                     "moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k", "kimi-k2.5"]

# Statuses worth retrying with backoff (rate limit / transient server errors)
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


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
            try:
                r = self.session.post(url, headers=headers, json=payload, timeout=timeout_sec)
            except requests.RequestException as e:
                # Keep the real cause (DNS, TLS, timeout...) instead of swallowing it
                last_error = e
                print(f"  [Kimi] Network error at {base_url}: {type(e).__name__}: {str(e)[:120]}")
                continue

            if r.status_code == 401:
                try:
                    err = r.json().get("error", {}).get("message", "Invalid Authentication")
                except ValueError:
                    err = "Invalid Authentication"
                print(f"  [Kimi] 401 at URL {base_url}: {err}")
                if "exceeded current quota" in err.lower():
                    print("  [Kimi] -> Account has no balance/credits. Check billing at platform.moonshot.ai")
                elif "not active" in err.lower():
                    print("  [Kimi] -> Account suspended. Check platform.moonshot.ai")
                else:
                    print("  [Kimi] -> Incorrect API key or wrong platform (try the other URL)")
                last_error = RuntimeError(f"401 at {base_url}: {err}")
                continue  # Try next URL

            if r.status_code == 404:
                model_in_payload = payload.get("model", "")
                if model_in_payload in DEPRECATED_MODELS:
                    print(f"  [Kimi] 404: model '{model_in_payload}' was discontinued. Use kimi-k2.6 or newer.")
                else:
                    print(f"  [Kimi] 404 at URL {base_url}: {r.text[:200]}")
                r.raise_for_status()

            if r.status_code in RETRYABLE_STATUSES:
                # Bubble up as HTTPError so chat() can back off and retry
                r.raise_for_status()

            r.raise_for_status()
            return r.json()
        raise last_error or RuntimeError("Kimi API: all URLs failed")

    def _try_model(self, model, messages, max_tokens, response_format, temperature=None):
        payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if response_format:
            payload["response_format"] = response_format
        if temperature is not None:
            payload["temperature"] = temperature
        # Kimi models think by default, and reasoning tokens are spent from the
        # same max_tokens budget as the answer -- so the content comes back
        # empty or cut mid-string, surfacing as a JSONDecodeError. This
        # pipeline wants short structured output, never a visible chain of
        # thought, so thinking is disabled for the whole family.
        #
        # The check used to read startswith("kimi-k2"), which silently excluded
        # every newer model. Measured 2026-08-23: on kimi-k3, 8 of 9 scoring
        # calls failed with "Expecting value: line 1 column 1" (empty content)
        # or "Unterminated string" -- not because the model was worse, but
        # because it alone was still thinking into a 1000-token budget.
        if str(model).startswith("kimi-"):
            payload["thinking"] = {"type": "disabled"}
        data = self._post("/chat/completions", payload, timeout_sec=60)
        return data["choices"][0]["message"]["content"]

    def chat(self, messages, model=None, max_tokens=1000, response_format=None, temperature=None):
        if model:
            models_to_try = [model]
        else:
            models_to_try = [KIMI_MODEL_PRIMARY]
            if KIMI_MODEL_FALLBACK and KIMI_MODEL_FALLBACK != KIMI_MODEL_PRIMARY:
                models_to_try.append(KIMI_MODEL_FALLBACK)

        last_error = None
        max_attempts = 3
        for m in models_to_try:
            for attempt in range(max_attempts):
                try:
                    return self._try_model(m, messages, max_tokens, response_format, temperature)
                except Exception as e:
                    last_error = e
                    error_str = str(e).lower()
                    if "404" in error_str and "not found" in error_str:
                        print(f"  [Kimi] Model {m} not found (404), trying next...")
                        break
                    if "401" in error_str:
                        # Auth/billing problems never fix themselves mid-run
                        break
                    print(f"  [Kimi] Error ({attempt+1}/{max_attempts}) with {m}: {str(e)[:120]}")
                    if attempt < max_attempts - 1:
                        time.sleep(2 ** (attempt + 1))  # 2s, 4s
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
