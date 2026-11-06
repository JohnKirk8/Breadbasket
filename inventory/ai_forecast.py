"""
AI production forecasting.

Formula (enforced entirely by this module, never by Gemini):
    recommended = max(0, forecasted_daily_demand - current_unsold_stock)

Gemini only estimates forecasted_daily_demand from sales history.
Ingredient stock is NOT checked here - only at batch creation time.
"""

import json
import logging
import re

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def _unsold_remaining(product):
    """Sum of remaining_quantity across all active batches for this product."""
    from .models import ProductionBatch
    active = ProductionBatch.objects.filter(
        product=product, status=ProductionBatch.STATUS_ACTIVE
    )
    return sum(int(b.remaining_quantity or 0) for b in active)


def _get_sales_history(product, days=14):
    from .models import SalesRecord
    since = timezone.localdate() - timezone.timedelta(days=days)
    return list(
        SalesRecord.objects.filter(product=product, sale_date__gte=since)
        .order_by("sale_date")
        .values_list("sale_date", "quantity_sold")
    )


def _build_prompt(product, history):
    history_lines = "\n".join(
        f"- {d}: {q} units sold" for d, q in history
    ) or "- No recorded sales yet."
    return (
        f"You are a demand analyst for Bread Basket Bakeshop.\n"
        f"Bread: {product.name}\n"
        f"Stored average daily sales: {product.avg_daily_sales} units\n\n"
        f"Sales history (oldest to newest):\n{history_lines}\n\n"
        "Estimate the expected daily demand (units customers buy per day) "
        "based ONLY on the sales history above.\n"
        "Do NOT consider ingredients. Do NOT subtract unsold stock.\n"
        "Return ONLY this JSON:\n"
        '{"forecasted_daily_demand": <integer>}'
    )


def _call_gemini(prompt):
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set.")

    models = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-flash-latest"]
    primary = getattr(settings, "GEMINI_MODEL", "gemini-2.0-flash")
    candidates = [primary] + [m for m in models if m != primary]

    last_err = None
    for model in candidates:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        try:
            resp = requests.post(
                url,
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=25,
            )
            resp.raise_for_status()
            text = (
                resp.json()
                .get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
            )
            m = re.search(r'"forecasted_daily_demand"\s*:\s*(\d+)', text)
            if m:
                return int(m.group(1))
            cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            return int(json.loads(cleaned)["forecasted_daily_demand"])
        except Exception as exc:
            last_err = exc
            logger.debug("Gemini %s failed: %s", model, exc)

    raise RuntimeError(f"All models failed: {last_err}")


def _fallback_demand(product, history):
    quantities = [q for _, q in history]
    avg = sum(quantities) / len(quantities) if quantities else float(product.avg_daily_sales)
    return round(avg)


def generate_recommendation(product, days=14):
    """
    recommended = max(0, forecasted_daily_demand - unsold_on_shelf)
    No ingredient stock cap. Stock is only checked at batch creation.
    """
    history = _get_sales_history(product, days)
    unsold = _unsold_remaining(product)

    source = "gemini"
    try:
        forecasted = _call_gemini(_build_prompt(product, history))
    except Exception as exc:
        logger.warning("Gemini failed for %s, fallback: %s", product.name, exc)
        forecasted = _fallback_demand(product, history)
        source = "fallback"

    recommended = max(0, forecasted - unsold)
    reason = (
        f"Forecasted daily demand ({forecasted} units) "
        f"minus {unsold} unsold units on shelf."
    )

    return {
        "recommended_quantity": recommended,
        "reason": reason,
        "source": source,
        "basis_period": f"last {days} days of sales",
    }
