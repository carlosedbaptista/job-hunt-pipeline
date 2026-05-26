#!/usr/bin/env python3
import os, time, json
from typing import Optional, List, Dict, Any
import httpx

KIMI_BASE_URL = "https://api.moonshot.cn/v1"
KIMI_MODEL_DEFAULT = "kimi-k2-6"
PRICING = {"kimi-k2-6": {"input": 0.60, "output": 2.50}}

class KimiClient:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.environ.get("KIMI_API_KEY", "")
        if not self.api_key:
            raise ValueError("KIMI_API_KEY nao configurada.")
        self.base_url = KIMI_BASE_URL.rstrip("/")
        self.headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        self.client = httpx.Client(timeout=120.0)

    def chat_completion(self, messages, model=KIMI_MODEL_DEFAULT, temperature=0.3, max_tokens=4096, system=None, response_format=None):
        payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if system: payload["messages"] = [{"role": "system", "content": system}] + messages
        if response_format: payload["response_format"] = response_format
        for attempt in range(3):
            try:
                r = self.client.post(f"{self.base_url}/chat/completions", headers=self.headers, json=payload)
                r.raise_for_status()
                d = r.json()
                content = d["choices"][0]["message"]["content"]
                u = d.get("usage", {})
                cost = self._estimate_cost(model, u.get("prompt_tokens",0), u.get("completion_tokens",0))
                print(f"  [Kimi] {u.get('prompt_tokens',0)}in/{u.get('completion_tokens',0)}out | ${cost:.4f}")
                return content.strip()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    time.sleep(2**attempt); continue
                raise
            except Exception as e:
                if attempt < 2: time.sleep(2**attempt); continue
                raise RuntimeError(f"Falha: {e}")
        raise RuntimeError("Falha inesperada")

    def _estimate_cost(self, model, inp, out):
        p = PRICING.get(model, PRICING[KIMI_MODEL_DEFAULT])
        return (inp/1e6*p["input"]) + (out/1e6*p["output"])
    def close(self): self.client.close()
    def __enter__(self): return self
    def __exit__(self, *a): self.close()

def call_kimi(prompt, system=None, model=KIMI_MODEL_DEFAULT, temperature=0.3, max_tokens=4096, response_format=None):
    c = KimiClient()
    return c.chat_completion([{"role":"user","content":prompt}], system=system, model=model, temperature=temperature, max_tokens=max_tokens, response_format=response_format)

def call_kimi_json(prompt, system=None, model=KIMI_MODEL_DEFAULT, temperature=0.1, max_tokens=4096):
    return json.loads(call_kimi(prompt, system, model, temperature, max_tokens, {"type":"json_object"}))
