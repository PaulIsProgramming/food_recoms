"""Route for retrieving orderable items, with optional item enrichment."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.enrichment_service import EnrichLevel, enrich_rows
from app.store import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT, store

router = APIRouter(tags=["orderable-items"])


@router.get("/orderable-items")
def get_orderable_items(
    store_id: str | None = Query(
        None, description="Optional store filter, e.g. 'store_a'. Omit for all stores."
    ),
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
    """Return a page of orderable items, optionally filtered and enriched.

    Results are paginated (``limit``/``offset``) because the full dataset is
    large; enrichment is applied only to the returned page.

    Raises:
        HTTPException: 409 if no orderable-items data is loaded, or if
            enrichment is requested without items data (see enrich_rows).
    """
    if store.orderable_items is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No orderable-items data loaded; POST /load first.",
        )

    rows = store.get_orderable_items(store_id, offset=offset, limit=limit)
    return enrich_rows(rows, enrich, store.items)
