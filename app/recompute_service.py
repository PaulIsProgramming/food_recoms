"""Recompute order recommendations from inventory using a base-stock policy.

Reverse-engineering the provided ``order_recommendations`` (see DATA_NOTES.md)
showed an order-up-to / base-stock policy:

    order = max(0, target_stock - current_stock)
    target_stock = cover_days * estimated_daily_demand

where demand is estimated from inventory draw-down. This module reproduces that
rule so the service can generate its own recommendations and compare them
against the loaded file.
"""

from __future__ import annotations

import pandas as pd

# Default days of demand to stock up to. Calibrated against the file: with the
# consumption-day demand estimate below, cover_days=5 minimizes the median
# |recompute - file| across all rows (~5 pieces) — a realistic fresh-food cover.
DEFAULT_COVER_DAYS = 5.0


def build_recomputed_recommendations(
    store_id: str,
    day: str,
    inventory: pd.DataFrame,
    recommendations: pd.DataFrame | None,
    cover_days: float = DEFAULT_COVER_DAYS,
) -> list[dict]:
    """Recompute recommendations for a store on a given ordering day.

    Args:
        store_id: Store to recompute for.
        day: Ordering day (ISO ``YYYY-MM-DD``); inventory history up to and
            including this day is used.
        inventory: Loaded inventory DataFrame (required).
        recommendations: Loaded order_recommendations DataFrame, or ``None``;
            used only to attach the file's value for comparison.
        cover_days: Days of demand to target (order-up-to horizon).

    Returns:
        One dict per item the store stocks, sorted by item_number. Empty if the
        store has no inventory up to ``day``.

    Side effects: none (read-only).
    """
    # Inventory history for this store up to the ordering day. ISO date strings
    # sort chronologically, so a string comparison is correct here.
    history = inventory[
        (inventory["store_id"] == store_id) & (inventory["day"] <= day)
    ]
    if history.empty:
        return []

    file_quantity = _file_quantities(store_id, day, recommendations)

    results = []
    for item_number, group in history.sort_values("day").groupby("item_number"):
        current_stock = float(group["quantity"].iloc[-1])
        demand, has_signal = _estimate_daily_demand(group["quantity"])
        target_stock = cover_days * demand
        recomputed = max(0, round(target_stock - current_stock))

        item = int(item_number)
        file_q = file_quantity.get(item)
        results.append(
            {
                "item_number": item,
                "current_stock": current_stock,
                "estimated_daily_demand": round(demand, 2),
                "target_stock": round(target_stock, 2),
                "recomputed_quantity": recomputed,
                # True when there's too little history to estimate demand, so a
                # 0 demand/quantity isn't mistaken for genuinely-zero demand.
                "insufficient_history": not has_signal,
                "file_quantity": file_q,
                "delta": (recomputed - file_q) if file_q is not None else None,
            }
        )
    return results


def _estimate_daily_demand(quantities: pd.Series) -> tuple[float, bool]:
    """Estimate daily demand as the mean drop over days when stock *fell*.

    Day-over-day stock changes are split: a decrease is consumption (sales), an
    increase is a delivery. We average the decreases over **only the days that
    had a decrease**, not all days. Averaging over all days would dilute the
    estimate roughly 2x, because on a delivery day the restock masks that day's
    sales (net change is up, so it reads as zero consumption) — and with a 1-2
    day lead time, delivery days are frequent.

    Returns:
        ``(demand, has_signal)``. ``has_signal`` is False when no day shows a
        decrease (a single inventory row, or a perfectly flat/rising series):
        consumption cannot be observed, so demand is reported as ``0.0`` and
        the caller flags ``insufficient_history``.
    """
    drops = (-quantities.diff()).clip(lower=0)
    consumption_days = drops[drops > 0]
    if consumption_days.empty:
        return 0.0, False
    return float(consumption_days.mean()), True


def _file_quantities(
    store_id: str, day: str, recommendations: pd.DataFrame | None
) -> dict[int, float]:
    """Map item_number -> the file's recommended_quantity for this store/day."""
    if recommendations is None:
        return {}
    matches = recommendations[
        (recommendations["store_id"] == store_id)
        & (recommendations["ordering_day"] == day)
    ]
    # On the rare duplicate key, the last row wins (see DATA_NOTES.md).
    return {
        int(row.item_number): float(row.recommended_quantity)
        for row in matches.itertuples(index=False)
    }
