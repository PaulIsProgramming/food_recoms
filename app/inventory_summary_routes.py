"""Route for the per-store inventory summary."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.enrichment_service import EnrichLevel, enrich_rows
from app.inventory_summary_service import build_inventory_summary
from app.store import store

router = APIRouter(tags=["inventory-summary"])


@router.get("/inventory-summary")
def get_inventory_summary(
    store_id: str = Query(..., description="Store identifier, e.g. 'store_a'"),
    enrich: EnrichLevel = Query(
        EnrichLevel.no,
        description="no = item_number; basic = item_number -> name; detailed = item_number -> full item object",
    ),
) -> list[dict]:
    """Return a per-item inventory summary for a store.

    Each entry has the item, its current stock (latest day), its stock status
    (low/normal/high relative to the item's own average), and up to 5 most
    recent order dates. ``last_orders`` is empty if orderable-items data isn't
    loaded. The ``enrich`` flag controls how ``item_number`` is presented, just
    like the other catalog endpoints.

    Raises:
        HTTPException: 409 if no inventory data is loaded, or if enrichment is
            requested without items data (see enrich_rows).
    """
    if store.inventory is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No inventory data loaded; POST /load first.",
        )

    summary = build_inventory_summary(store_id, store.inventory, store.orderable_items)
    return enrich_rows(summary, enrich, store.items)
