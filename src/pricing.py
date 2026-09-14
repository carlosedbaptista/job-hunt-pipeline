"""
pricing.py -- Turns token counts into money, or admits it cannot.

Why this exists
---------------
The pipeline had a cost CONTROL (`max_evaluations_per_run`, a cap of 30 calls)
but no cost ACCOUNTING. Tokens were visible only for the orchestrator, which
is one call per run, while the evaluations -- up to thirty of them -- recorded
nothing at all. Estimating a run's cost meant measuring prompt strings by hand.

The one rule here
-----------------
A price that is not configured returns None, never a guess. A fabricated
number is worse than no number: it would be averaged, charted and believed.
`config/model_pricing.json` ships with every price null on purpose -- fill it
from the provider's own dashboard, because published prices change and a
hardcoded one silently rots.

`unknown_share` in summarise() is the honesty signal: it reports what fraction
of the spend could not be priced, the same way the netzdenker runtime's soak
report does.
"""
import json
import os

PRICING_PATH = os.environ.get(
    "MODEL_PRICING_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "config", "model_pricing.json"))

_cache = None


def load_pricing(path=None):
    """Reads the pricing table. A missing or malformed file is not an error:
    it means "no prices known", and the pipeline must keep running."""
    global _cache
    if path is None and _cache is not None:
        return _cache
    try:
        with open(path or PRICING_PATH, encoding="utf-8") as f:
            table = (json.load(f) or {}).get("models") or {}
    except (OSError, ValueError):
        table = {}
    if path is None:
        _cache = table
    return table


def cost_usd(model, prompt_tokens, completion_tokens, path=None):
    """USD for one call, or None when the model has no configured price.

    Both directions must be priced: charging input at a known rate while
    silently treating output as free would understate every number.
    """
    entry = (load_pricing(path) or {}).get(str(model or ""))
    if not entry:
        return None
    pin = entry.get("input_per_1m_usd")
    pout = entry.get("output_per_1m_usd")
    if pin is None or pout is None:
        return None
    try:
        return (float(prompt_tokens or 0) * float(pin)
                + float(completion_tokens or 0) * float(pout)) / 1_000_000
    except (TypeError, ValueError):
        return None


def summarise(usages):
    """Aggregates evaluation `usage` blocks into one report.

    `unknown_share` is the fraction of CALLS whose cost could not be computed,
    so a summary can never read as complete when it is not.
    """
    total = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
             "known_usd": 0.0, "unpriced_calls": 0}
    for u in usages or []:
        if not isinstance(u, dict):
            continue
        total["calls"] += int(u.get("calls") or 0)
        total["prompt_tokens"] += int(u.get("prompt_tokens") or 0)
        total["completion_tokens"] += int(u.get("completion_tokens") or 0)
        if u.get("cost_usd") is None:
            total["unpriced_calls"] += int(u.get("calls") or 0)
        else:
            total["known_usd"] += float(u["cost_usd"])
    total["unknown_share"] = (total["unpriced_calls"] / total["calls"]
                              if total["calls"] else 0.0)
    return total
