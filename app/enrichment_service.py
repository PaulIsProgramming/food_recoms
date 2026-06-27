"""Item-enrichment logic shared by the catalog endpoints.

Both ``/orderable-items`` and ``/inventory`` can replace the bare
``item_number`` in each row with item details from the ``items`` dataset,
controlled by an ``enrich`` flag:

- ``no``       — rows unchanged.
- ``basic``    — ``item_number`` replaced by the item's ``name``.
- ``detailed`` — ``item_number`` replaced by a nested ``item`` object holding
  every column from ``items.csv``.
"""

from __future__ import annotations

from enum import Enum

import pandas as pd
from fastapi import HTTPException, status

from app.store import to_records


class EnrichLevel(str, Enum):
    """Allowed values for the ``enrich`` query flag."""

    no = "no"
    basic = "basic"
    detailed = "detailed"


def enrich_rows(
    rows: list[dict],
    level: EnrichLevel,
    items: pd.DataFrame | None,
) -> list[dict]:
    """Enrich row dicts with item info according to ``level``.

    Args:
        rows: JSON-safe row dicts, each containing an ``item_number`` key.
        level: The requested enrichment level.
        items: The loaded items DataFrame, or ``None`` if not loaded.

    Returns:
        New list of row dicts. For ``no`` the input rows are returned as-is.

    Raises:
        HTTPException: 409 if ``basic``/``detailed`` is requested but no
            items data has been loaded.
    """
    if level is EnrichLevel.no:
        return rows

    if items is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Enrichment requires items data; POST /load with items.csv first.",
        )

    # item_number -> full item record, built once for the whole batch.
    item_lookup = {record["item_number"]: record for record in to_records(items)}

    if level is EnrichLevel.basic:
        return [
            _replace_item_number(row, "name", _lookup_name(item_lookup, row))
            for row in rows
        ]

    # detailed
    return [
        _replace_item_number(row, "item", item_lookup.get(row.get("item_number")))
        for row in rows
    ]


def _lookup_name(item_lookup: dict, row: dict) -> str | None:
    """Return the item name for a row, or None if the item is unknown."""
    item = item_lookup.get(row.get("item_number"))
    return item["name"] if item is not None else None


def _replace_item_number(row: dict, new_key: str, new_value: object) -> dict:
    """Return a copy of ``row`` with the ``item_number`` entry swapped out.

    The new key/value takes the position ``item_number`` occupied, so column
    order stays intuitive. Rows without ``item_number`` are returned unchanged.
    """
    return {
        (new_key if key == "item_number" else key): (
            new_value if key == "item_number" else value
        )
        for key, value in row.items()
    }
