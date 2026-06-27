"""FastAPI application entrypoint for the FreshFlow service.

Wires the data-ingestion and recommendation-retrieval routers into a single
app and exposes a root info route and a health check. Interactive docs are
served at ``/docs``.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.data_routes import router as data_router
from app.inventory_routes import router as inventory_router
from app.inventory_summary_routes import router as inventory_summary_router
from app.orderable_items_routes import router as orderable_items_router
from app.recommendations_routes import router as recommendations_router

app = FastAPI(
    title="FreshFlow Order Recommendations",
    description=(
        "Load grocery fresh-food CSV data and retrieve per-store, per-day "
        "order recommendations."
    ),
    version="1.0.0",
)

app.include_router(data_router)
app.include_router(recommendations_router)
app.include_router(orderable_items_router)
app.include_router(inventory_router)
app.include_router(inventory_summary_router)


@app.get("/", tags=["meta"])
def root() -> dict:
    """Service info and pointers to the main endpoints."""
    return {
        "service": "FreshFlow Order Recommendations",
        "docs": "/docs",
        "endpoints": {
            "load": "POST /load",
            "recommendations": "GET /recommendations?store_id=&day=",
            "recompute": "GET /recommendations/recompute?store_id=&day=&cover_days=",
            "orderable_items": "GET /orderable-items?store_id=&enrich=no|basic|detailed",
            "inventory": "GET /inventory?store_id=&enrich=no|basic|detailed",
            "inventory_summary": "GET /inventory-summary?store_id=",
        },
    }


@app.get("/health", tags=["meta"])
def health() -> dict:
    """Liveness probe."""
    return {"status": "ok"}
