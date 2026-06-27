"""Pydantic response models for the FreshFlow API."""

from __future__ import annotations

from pydantic import BaseModel


class RecommendationOut(BaseModel):
    """A single order recommendation row (raw, as ingested)."""

    store_id: str
    item_number: int
    ordering_day: str
    delivery_day: str
    recommended_quantity: int


class LoadResponse(BaseModel):
    """Result of a ``/load`` call.

    ``ingested`` is the row count stored per dataset. ``skipped`` lists, per
    dataset, how many malformed rows were dropped during parsing (only
    datasets with skips appear).
    """

    ingested: dict[str, int]
    skipped: dict[str, int] = {}
