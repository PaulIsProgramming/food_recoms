"""Route for retrieving a store's inventory, with optional item enrichment."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.enrichment_service import EnrichLevel, enrich_rows
from app.store import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT, store

router = APIRouter(tags=["inventory"])


@router.get("/inventory")
def get_inventory(
    store_id: str = Query(..., description="Store identifier, e.g. 'store_a'"),
    enrich: EnrichLevel = Query(
        EnrichLevel.no,
        description="no = raw rows; basic = item_number -> name; detailed = item_number -> full item object",
    ),
    limit: int = Query(
        DEFAULT_PAGE_LIMIT,
        ge=1,
        le=MAX_PAGE_LIMIT,
        description="Max rows to return (pagination).",
    ),
    offset: int = Query(0, ge=0, description="Rows to skip (pagination)."),
) -> list[dict]:
    """Return a page of inventory for a store, optionally enriched.

    Results are paginated (``limit``/``offset``); enrichment is applied only
    to the returned page.

    Raises:
        HTTPException: 409 if no inventory data is loaded, or if enrichment
            is requested without items data (see enrich_rows).
    """
    if store.inventory is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No inventory data loaded; POST /load first.",
        )

    rows = store.get_inventory(store_id, offset=offset, limit=limit)
    return enrich_rows(rows, enrich, store.items)
