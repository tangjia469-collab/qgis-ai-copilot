# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline USD estimates from a dated official Standard API rate card.

This is a list-price comparison, never a router invoice. No model aliases are
guessed. Missing cache breakdowns produce bounds, not invented zero counts.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING
import re

PRICE_SOURCE = "https://developers.openai.com/api/docs/pricing"
PRICE_DATE = "2026-09-07"
MAX_COST_ROUNDS = 32
LONG_CONTEXT_THRESHOLD = 272000

# USD per million: ordinary input, cache read, cache write, output.
# Sources and long-context rules are recorded in docs/PRICING.md.
RATES = {
    "gpt-6-astra": ("10", "1", "12.5", "50"),
    "gpt-5.6-sol": ("4", "0.4", "5", "20"),
    "gpt-5.6-terra": ("2", "0.2", "2.5", "12"),
    "gpt-5.6-luna": ("0.2", "0.02", "0.25", "1.2"),
    "gpt-5.5": ("5", "0.5", None, "30"),
    "gpt-5.5-pro": ("30", None, None, "180"),
    "gpt-5.4": ("2.5", "0.25", None, "15"),
    "gpt-5.4-pro": ("30", None, None, "180"),
    "gpt-5.4-mini": ("0.75", "0.075", None, "4.5"),
    "gpt-5.4-nano": ("0.2", "0.02", None, "1.25"),
    "gpt-5.2": ("1.75", "0.175", None, "14"),
    "gpt-5.2-pro": ("21", None, None, "168"),
    "gpt-5.1": ("1.25", "0.125", None, "10"),
    "gpt-5": ("1.25", "0.125", None, "10"),
    "gpt-5-mini": ("0.25", "0.025", None, "2"),
    "gpt-5-nano": ("0.05", "0.005", None, "0.4"),
    "gpt-5-pro": ("15", None, None, "120"),
    "gpt-4.1": ("2", "0.5", None, "8"),
    "gpt-4.1-mini": ("0.4", "0.1", None, "1.6"),
    "gpt-4.1-nano": ("0.1", "0.025", None, "0.4"),
    "gpt-4o": ("2.5", "1.25", None, "10"),
    "gpt-4o-2024-05-13": ("5", None, None, "15"),
    "gpt-4o-mini": ("0.15", "0.075", None, "0.6"),
    "o1": ("15", "7.5", None, "60"),
    "o1-pro": ("150", None, None, "600"),
    "o3-pro": ("20", None, None, "80"),
    "o3": ("2", "0.5", None, "8"),
    "o4-mini": ("1.1", "0.275", None, "4.4"),
    "o3-mini": ("1.1", "0.55", None, "4.4"),
    "gpt-5.3-codex": ("1.75", "0.175", None, "14"),
    "gpt-4-turbo-2024-04-09": ("10", None, None, "30"),
    "gpt-4-0613": ("30", None, None, "60"),
    "gpt-3.5-turbo": ("0.5", None, None, "1.5"),
    "gpt-3.5-turbo-0125": ("0.5", None, None, "1.5"),
    "gpt-3.5-turbo-1106": ("1", None, None, "2"),
}
LONG_CONTEXT_MODELS = {
    "gpt-6-astra",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
    "gpt-5.5-pro",
    "gpt-5.4",
    "gpt-5.4-pro",
}
REASONS = {
    "unknown_model": "No verified official price for this exact model ID.",
    "missing_usage": "A model call did not report usable usage details.",
    "invalid_usage": "Reported usage is inconsistent or invalid.",
    "incomplete": "The request stopped or failed; complete usage is unknown.",
    "legacy_rounds": "This older multi-step answer has no per-call breakdown for long-context pricing.",
    "invalid_estimate": "The saved cost estimate is unavailable or invalid.",
}


def unavailable(reason):
    return {
        "status": "unavailable",
        "reason": reason if isinstance(reason, str) and reason in REASONS else "invalid_estimate",
    }


def _count(usage, key, required=False):
    if key not in usage:
        if required:
            raise KeyError(key)
        return None
    value = usage[key]
    if type(value) is not int or not 0 <= value <= 2_000_000_000:
        raise ValueError("Invalid usage")
    return value


def _counts(usage):
    if not isinstance(usage, dict):
        raise KeyError("usage")
    inputs = _count(usage, "input_tokens" if "input_tokens" in usage else "prompt_tokens", True)
    outputs = _count(
        usage, "output_tokens" if "output_tokens" in usage else "completion_tokens", True
    )
    total = _count(usage, "total_tokens")
    if total is not None and total != inputs + outputs:
        raise ValueError("Inconsistent total")
    for key, expected in (("prompt_tokens", inputs), ("completion_tokens", outputs)):
        if key in usage and _count(usage, key) != expected:
            raise ValueError("Inconsistent aliases")
    return inputs, outputs, _count(usage, "cached_tokens"), _count(usage, "cache_write_tokens")


def estimate_cost(model, usage_rounds):
    """Estimate each completed call separately from normalized numeric counters."""
    if not isinstance(model, str) or model not in RATES:
        return unavailable("unknown_model")
    if not isinstance(usage_rounds, list) or not 1 <= len(usage_rounds) <= MAX_COST_ROUNDS:
        return unavailable("missing_usage")
    lower = upper = Decimal(0)
    missing_cache = False
    try:
        for usage in usage_rounds:
            inputs, outputs, cached, written = _counts(usage)
            rates = [Decimal(value) if value is not None else None for value in RATES[model]]
            if model in LONG_CONTEXT_MODELS and inputs > LONG_CONTEXT_THRESHOLD:
                rates = [
                    value * (Decimal("1.5") if i == 3 else 2) if value is not None else None
                    for i, value in enumerate(rates)
                ]
            ordinary_rate, cached_rate, write_rate, output_rate = rates
            if (cached and cached_rate is None) or (written and write_rate is None):
                raise ValueError("No matching cache rate")
            if cached_rate is None:
                cached = 0
            if write_rate is None:
                written = 0
            remaining = inputs - (cached or 0) - (written or 0)
            if remaining < 0:
                raise ValueError("Cache counts exceed input")
            known = (
                outputs * output_rate
                + (cached or 0) * (cached_rate or 0)
                + (written or 0) * (write_rate or 0)
            )
            possible_rates = [ordinary_rate]
            if cached is None:
                possible_rates.append(cached_rate)
            if written is None:
                possible_rates.append(write_rate)
            missing_cache |= cached is None or written is None
            lower += (known + remaining * min(possible_rates)) / 1_000_000
            upper += (known + remaining * max(possible_rates)) / 1_000_000
    except KeyError:
        return unavailable("missing_usage")
    except (TypeError, ValueError, InvalidOperation):
        return unavailable("invalid_usage")
    return {
        "status": "estimated",
        "currency": "USD",
        "model": model,
        "pricing_date": PRICE_DATE,
        "source_url": PRICE_SOURCE,
        "min_usd": format(lower.normalize(), "f"),
        "max_usd": format(upper.normalize(), "f"),
        "rounds": len(usage_rounds),
        "cache_details_missing": missing_cache,
    }


def sanitize_cost_estimate(value):
    """Persist exact decimal amounts and a small, non-secret provenance record."""
    if not isinstance(value, dict):
        return unavailable("invalid_estimate")
    if value.get("status") == "unavailable":
        return unavailable(value.get("reason"))
    try:
        if (
            value.get("status") != "estimated"
            or value.get("currency") != "USD"
            or value.get("model") not in RATES
            or value.get("source_url") != PRICE_SOURCE
        ):
            raise ValueError
        checked = value.get("pricing_date")
        if checked != PRICE_DATE:
            raise ValueError
        amounts = []
        for key in ("min_usd", "max_usd"):
            raw = value.get(key)
            if not isinstance(raw, str) or not re.fullmatch(
                r"(?:0|[1-9][0-9]{0,9})(?:\.[0-9]{1,18})?", raw
            ):
                raise ValueError
            amount = Decimal(raw)
            if not amount.is_finite() or not 0 <= amount <= 1_000_000_000:
                raise ValueError
            amounts.append(amount)
        if (
            amounts[0] > amounts[1]
            or type(value.get("rounds")) is not int
            or not 1 <= value["rounds"] <= MAX_COST_ROUNDS
        ):
            raise ValueError
        return {
            "status": "estimated",
            "currency": "USD",
            "model": value["model"],
            "pricing_date": checked,
            "source_url": PRICE_SOURCE,
            "min_usd": format(amounts[0], "f"),
            "max_usd": format(amounts[1], "f"),
            "rounds": value["rounds"],
            "cache_details_missing": value.get("cache_details_missing") is True,
        }
    except (ValueError, TypeError, InvalidOperation):
        return unavailable("invalid_estimate")


def cost_for_message(message):
    if message.get("status") not in {"complete", "non_streaming"}:
        return unavailable("incomplete")
    request = message.get("request") or {}
    model = request.get("model") or ""
    if "cost_estimate" in message:
        result = sanitize_cost_estimate(message["cost_estimate"])
        if result.get("status") == "estimated" and result["model"] != model:
            return unavailable("invalid_estimate")
        return result
    rounds = message.get("usage_rounds")
    if rounds is None:
        usage = message.get("usage") or {}
        try:
            inputs, _, _, _ = _counts(usage)
        except (ValueError, KeyError):
            return unavailable("missing_usage")
        # Older small aggregates can only contain short-context calls. Larger
        # aggregates cannot reveal whether any individual call crossed the tier.
        if (
            isinstance(model, str)
            and model in LONG_CONTEXT_MODELS
            and inputs > LONG_CONTEXT_THRESHOLD
            and (request.get("inspect") or request.get("execute"))
        ):
            return unavailable("legacy_rounds")
        rounds = [usage]
    return estimate_cost(model, rounds)


def cost_display(message):
    if message.get("status") in {"pending", "streaming"}:
        return "", ""
    result = cost_for_message(message)
    if result["status"] != "estimated":
        return "Cost unavailable", REASONS[result["reason"]]
    minimum, maximum = Decimal(result["min_usd"]), Decimal(result["max_usd"])
    unit = Decimal("0.0001")
    if 0 < maximum < unit:
        label = "Est. <$0.0001"
    elif minimum == maximum:
        label = f"Est. ${maximum.quantize(unit, rounding=ROUND_HALF_UP):.4f}"
    else:
        low = minimum.quantize(unit, rounding=ROUND_FLOOR)
        high = maximum.quantize(unit, rounding=ROUND_CEILING)
        label = f"Est. ${low:.4f}–${high:.4f}" if low != high else f"Est. ≈${high:.4f}"
    tooltip = (
        f"{label} USD · OpenAI Standard API list-price estimate, checked {result['pricing_date']}. "
        "Not your router bill; excludes router markups, service-tier/region adjustments and hosted-tool fees. "
    )
    if result["cache_details_missing"]:
        tooltip += "Unreported cache details are bounded by the applicable official rates. "
    tooltip += f"Source: {result['source_url']}"
    return label, tooltip
