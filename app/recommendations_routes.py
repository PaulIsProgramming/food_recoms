"""Routes for retrieving order recommendations."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query, status

from app.enrichment_service import EnrichLevel, enrich_rows
from app.models import RecommendationOut
from app.recompute_service import DEFAULT_COVER_DAYS, build_recomputed_recommendations
from app.store import store

router = APIRouter(tags=["recommendations"])


def _validate_day(day: str) -> str:
    """Validate ``day`` is an ISO ``YYYY-MM-DD`` date; return it unchanged.

    Raises HTTPException 422 with an actionable message otherwise.
    """
    try:
        date.fromisoformat(day)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'day' must be an ISO date (YYYY-MM-DD), got '{day}'",
        ) from exc
    return day


@router.get("/recommendations", response_model=list[RecommendationOut])
def get_recommendations(
    store_id: str = Query(..., description="Store identifier, e.g. 'store_a'"),
    day: str = Query(..., description="Ordering day as ISO date YYYY-MM-DD"),
) -> list[RecommendationOut]:
    """Return order recommendations for a store on a given ordering day.

    Filters the loaded recommendations by ``store_id`` and ``ordering_day``.
    Returns an empty list (200) when no rows match the store/day.

    Raises:
        HTTPException: 409 if no recommendation data has been loaded yet;
            422 if ``day`` is not a valid ISO date.
    """
    if not store.is_loaded:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No recommendation data loaded; POST /load first.",
        )

    _validate_day(day)
    rows = store.get_recommendations(store_id, day)
    return [RecommendationOut(**row) for row in rows]


@router.get("/recommendations/recompute")
def recompute_recommendations(
    store_id: str = Query(..., description="Store identifier, e.g. 'store_a'"),
    day: str = Query(..., description="Ordering day as ISO date YYYY-MM-DD"),
    cover_days: float = Query(
        DEFAULT_COVER_DAYS,
        gt=0,
        description="Days of demand to stock up to (order-up-to horizon).",
    ),
    enrich: EnrichLevel = Query(
        EnrichLevel.no,
        description="no = item_number; basic = item_number -> name; detailed = item_number -> full item object",
    ),
) -> list[dict]:
    """Recompute recommendations from inventory using the base-stock rule.

    For each item the store stocks, estimates daily demand from inventory
    draw-down, targets ``cover_days`` of demand, and orders the gap above
    current stock: ``order = max(0, cover_days*demand - current_stock)``. Where
    the loaded file has a matching row, its value and the delta are included for
    comparison. The ``enrich`` flag controls how ``item_number`` is presented,
    like the other endpoints. See ``app/recompute_service.py`` and DATA_NOTES.md.

    Raises:
        HTTPException: 409 if no inventory data is loaded (or if enrichment is
            requested without items data); 422 if ``day`` is not a valid ISO date.
    """
    if store.inventory is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No inventory data loaded; POST /load first.",
        )

    _validate_day(day)
    recomputed = build_recomputed_recommendations(
        store_id, day, store.inventory, store.order_recommendations, cover_days
    )
    return enrich_rows(recomputed, enrich, store.items)
