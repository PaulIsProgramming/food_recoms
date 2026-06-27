"""In-memory data store for ingested FreshFlow CSV data.

Holds the four datasets as pandas DataFrames in process memory. A single
module-level ``store`` instance is shared across requests. Data does not
survive a process restart, which is acceptable for this challenge.
"""

from __future__ import annotations

import json

import pandas as pd


# Pagination defaults for the list endpoints (orderable-items, inventory).
DEFAULT_PAGE_LIMIT = 100
MAX_PAGE_LIMIT = 1000


def to_records(frame: pd.DataFrame) -> list[dict]:
    """Convert a DataFrame to JSON-safe row dicts.

    Round-trips through pandas' JSON writer so numpy scalar types become
    native Python types and missing values (NaN) become ``None`` — both
    required for clean serialization by FastAPI.

    Args:
        frame: The DataFrame to convert.

    Returns:
        List of row dicts with JSON-native values.
    """
    return json.loads(frame.to_json(orient="records"))


class DataStore:
    """Process-local container for the ingested datasets.

    Each dataset is an optional pandas DataFrame, ``None`` until loaded via
    the ``/load`` endpoint. Mutating methods replace the stored DataFrames
    in place (side effect: changes shared process state).
    """

    def __init__(self) -> None:
        self.items: pd.DataFrame | None = None
        self.orderable_items: pd.DataFrame | None = None
        self.inventory: pd.DataFrame | None = None
        self.order_recommendations: pd.DataFrame | None = None

    @property
    def is_loaded(self) -> bool:
        """True once recommendation data is present (required for retrieval)."""
        return self.order_recommendations is not None

    def get_recommendations(self, store_id: str, day: str) -> list[dict]:
        """Return recommendation rows for a store on a given ordering day.

        Args:
            store_id: Store identifier, e.g. ``"store_a"``.
            day: Ordering day as ISO date string ``YYYY-MM-DD``; matched
                against the ``ordering_day`` column.

        Returns:
            JSON-safe row dicts (numpy scalars / NaN normalized via
            ``to_records``), empty if no rows match. Assumes recommendation
            data has been loaded — callers should check ``is_loaded`` first.
        """
        recommendations = self.order_recommendations
        matches = recommendations[
            (recommendations["store_id"] == store_id)
            & (recommendations["ordering_day"] == day)
        ]
        return to_records(matches)

    def get_orderable_items(
        self,
        store_id: str | None = None,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> list[dict]:
        """Return a page of orderable-item rows, optionally filtered by store.

        Args:
            store_id: If given, return only rows for that store; otherwise
                consider every row.
            offset: Number of rows to skip (after filtering).
            limit: Maximum number of rows to return.

        Returns:
            JSON-safe row dicts for the requested page. Assumes
            orderable-items data is loaded.
        """
        frame = self.orderable_items
        if store_id is not None:
            frame = frame[frame["store_id"] == store_id]
        # Slice before conversion so only the page is materialized.
        page = frame.iloc[offset : offset + limit]
        return to_records(page)

    def get_inventory(
        self,
        store_id: str,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> list[dict]:
        """Return a page of inventory rows for a store.

        Args:
            store_id: Store identifier to filter by.
            offset: Number of rows to skip (after filtering).
            limit: Maximum number of rows to return.

        Returns:
            JSON-safe row dicts for the requested page. Assumes inventory
            data is loaded.
        """
        frame = self.inventory[self.inventory["store_id"] == store_id]
        page = frame.iloc[offset : offset + limit]
        return to_records(page)


# Module-level singleton shared by all request handlers.
store = DataStore()
