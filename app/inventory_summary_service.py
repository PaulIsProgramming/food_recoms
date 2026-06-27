"""Build a per-store inventory summary.

For one store, produces one entry per unique item with:
- ``current_stock``  — quantity on the most recent recorded day,
- ``stock_status``   — low / normal / high, relative to the item's own average,
- ``last_orders``    — up to 5 most recent orders (newest first), each with the
  order ``date`` and ``current_quantity_in_store`` on that day.

Order dates come from ``orderable_items.ordering_day``; current stock, the
average, and each order's stock level come from ``inventory``.
(``current_quantity_in_store`` is the stock on hand on the order day — what
triggered the order — not an "amount ordered", which the data does not record.)
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

# Stock-status bands, relative to the item's own average daily stock.
LOW_STOCK_RATIO = 0.5
HIGH_STOCK_RATIO = 1.5

# How many recent order dates to include per item.
MAX_LAST_ORDERS = 5


def build_inventory_summary(
    store_id: str,
    inventory: pd.DataFrame,
    orderable_items: pd.DataFrame | None,
) -> list[dict]:
    """Build the inventory summary for a store.

    Args:
        store_id: Store to summarize.
        inventory: The loaded inventory DataFrame (required).
        orderable_items: The orderable-items DataFrame, or ``None`` if not
            loaded — in which case ``last_orders`` is empty for every item.

    Returns:
        List of summary dicts, one per item, sorted by ``item_number``.
        Empty list if the store has no inventory rows.

    Side effects: none (read-only over the passed DataFrames).
    """
    store_inventory = inventory[inventory["store_id"] == store_id]
    # Drop rows with no usable date: ingestion sets unparseable dates to None,
    # and such rows would otherwise sort *after* real dates (None/NaN last) and
    # be wrongly picked as the latest day's stock.
    store_inventory = store_inventory[store_inventory["day"].notna()]
    if store_inventory.empty:
        return []

    # Average daily stock per item (for the status bands) and the latest
    # recorded quantity per item (current stock). Day is a canonical ISO string,
    # so lexicographic ordering matches chronological ordering.
    average_by_item = store_inventory.groupby("item_number")["quantity"].mean()
    latest_by_item = (
        store_inventory.sort_values("day").groupby("item_number")["quantity"].last()
    )

    # (item_number, day) -> stock quantity, to attach the stock level to each
    # order date below. A NaN quantity maps to None (kept JSON-safe).
    stock_by_item_day = {
        (int(row.item_number), row.day): (
            float(row.quantity) if pd.notna(row.quantity) else None
        )
        for row in store_inventory.itertuples(index=False)
    }

    orders_by_item = _recent_orders_by_item(
        store_id, orderable_items, stock_by_item_day
    )

    summary = []
    for item_number in sorted(average_by_item.index):
        current_stock = float(latest_by_item[item_number])
        average_stock = float(average_by_item[item_number])
        summary.append(
            {
                "item_number": int(item_number),
                "current_stock": current_stock,
                "stock_status": _stock_status(current_stock, average_stock),
                "last_orders": orders_by_item.get(int(item_number), []),
            }
        )
    return summary


def _stock_status(current_stock: float, average_stock: float) -> str:
    """Classify current stock relative to the item's average daily stock."""
    if average_stock <= 0:
        return "normal"
    if current_stock < LOW_STOCK_RATIO * average_stock:
        return "low"
    if current_stock > HIGH_STOCK_RATIO * average_stock:
        return "high"
    return "normal"


def _recent_orders_by_item(
    store_id: str,
    orderable_items: pd.DataFrame | None,
    stock_by_item_day: dict[tuple[int, str], float],
) -> dict[int, list[dict]]:
    """Map each item to its most recent orders (newest first).

    Each order is ``{"date": <YYYY-MM-DD HH:MM, naive>,
    "current_quantity_in_store": <stock on that day>}``, the stock on hand on
    the order day (``None`` if no inventory row exists for that exact day).

    Returns an empty mapping if orderable-items data isn't loaded.
    """
    if orderable_items is None:
        return {}

    store_orders = orderable_items[orderable_items["store_id"] == store_id]
    orders_by_item: dict[int, list[dict]] = {}
    for item_number, group in store_orders.groupby("item_number"):
        item = int(item_number)
        # Distinct ordering days, newest first, capped. Skip null dates
        # (unparseable on ingest) — they can't be sorted against real dates
        # and would crash the formatter.
        valid_days = {day for day in group["ordering_day"] if pd.notna(day)}
        recent = sorted(valid_days, reverse=True)[:MAX_LAST_ORDERS]
        orders_by_item[item] = [
            {
                "date": _format_order_datetime(day),
                "current_quantity_in_store": stock_by_item_day.get((item, day)),
            }
            for day in recent
        ]
    return orders_by_item


def _format_order_datetime(day: str) -> str:
    """Format a canonical ISO date as ``YYYY-MM-DD HH:MM`` (naive, no timezone).

    The source data is date-only, so the time component is always ``00:00`` —
    this is *not* a timezone conversion. Input is expected to be a valid ISO
    date (ingestion canonicalizes/null-filters dates), and callers skip nulls.
    """
    return datetime.strptime(day, "%Y-%m-%d").strftime("%Y-%m-%d %H:%M")
