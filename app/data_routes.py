"""Routes for ingesting the FreshFlow CSV datasets."""

from __future__ import annotations

from fastapi import APIRouter, File, UploadFile

from app.ingestion_service import parse_csv
from app.models import LoadResponse
from app.store import store

router = APIRouter(tags=["data"])

# Required columns per dataset, used to validate uploads on ingestion.
_REQUIRED_COLUMNS = {
    "items": {
        "item_number",
        "name",
        "category",
        "is_bio",
        "purchase_price",
        "suggested_retail_price",
    },
    "orderable_items": {
        "store_id",
        "item_number",
        "ordering_day",
        "delivery_day",
    },
    "inventory": {"store_id", "item_number", "day", "quantity"},
    "order_recommendations": {
        "store_id",
        "item_number",
        "ordering_day",
        "delivery_day",
        "recommended_quantity",
    },
}


@router.post("/load", response_model=LoadResponse)
def load_data(
    order_recommendations: UploadFile = File(
        ..., description="order_recommendations.csv (required)"
    ),
    items: UploadFile | None = File(None, description="items.csv (optional)"),
    orderable_items: UploadFile | None = File(
        None, description="orderable_items.csv (optional)"
    ),
    inventory: UploadFile | None = File(None, description="inventory.csv (optional)"),
) -> LoadResponse:
    """Ingest the FreshFlow CSV files into the in-memory store.

    ``order_recommendations`` is required (it backs the retrieve endpoint);
    the other three datasets are optional. Each provided file is validated
    and stored, replacing any previously loaded version.

    Returns the number of rows ingested per provided dataset.
    Side effect: mutates the shared in-memory store.
    """
    # Map each known dataset name to its uploaded file (skipping omitted ones).
    uploads = {
        "items": items,
        "orderable_items": orderable_items,
        "inventory": inventory,
        "order_recommendations": order_recommendations,
    }

    ingested: dict[str, int] = {}
    skipped: dict[str, int] = {}
    for name, upload in uploads.items():
        if upload is None:
            continue
        frame, skipped_rows = parse_csv(upload, _REQUIRED_COLUMNS[name])
        setattr(store, name, frame)
        ingested[name] = len(frame)
        if skipped_rows:
            skipped[name] = skipped_rows

    return LoadResponse(ingested=ingested, skipped=skipped)
