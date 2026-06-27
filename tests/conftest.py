"""Shared pytest fixtures: a TestClient and small in-memory sample CSVs."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import store

# Minimal valid CSVs covering two stores and a couple of days. Kept tiny so
# tests assert on exact rows rather than fixture-file contents.
RECOMMENDATIONS_CSV = (
    "store_id,item_number,ordering_day,delivery_day,recommended_quantity\n"
    "store_a,1001,2024-01-01,2024-01-02,18\n"
    "store_a,1002,2024-01-01,2024-01-02,5\n"
    "store_a,1001,2024-01-02,2024-01-03,10\n"
    "store_b,1001,2024-01-01,2024-01-02,7\n"
)

ITEMS_CSV = (
    "item_number,name,category,is_bio,purchase_price,suggested_retail_price\n"
    "1001,Organic Bananas,Fruits,False,0.89,1.49\n"
    "1002,Red Apples Gala,Fruits,False,1.2,1.99\n"
)

ORDERABLE_ITEMS_CSV = (
    "store_id,item_number,ordering_day,delivery_day,purchase_price,suggested_retail_price,profit_margin,tags,category\n"
    "store_a,1001,2024-01-01,2024-01-02,0.89,1.49,0.40,,Fruits\n"
    "store_b,1002,2024-01-01,2024-01-02,1.2,1.99,0.40,new,Fruits\n"
)

INVENTORY_CSV = (
    "store_id,item_number,day,quantity\n"
    "store_a,1001,2024-01-01,16.4\n"
    "store_a,1002,2024-01-01,5.0\n"
    "store_b,1001,2024-01-01,3.0\n"
)


@pytest.fixture
def client() -> TestClient:
    """A TestClient with a fresh, empty store for each test."""
    store.items = None
    store.orderable_items = None
    store.inventory = None
    store.order_recommendations = None
    return TestClient(app)


def load_sample(client: TestClient, *, with_items: bool = False):
    """Helper: POST the sample recommendation CSV (optionally items too)."""
    files = {
        "order_recommendations": (
            "order_recommendations.csv",
            RECOMMENDATIONS_CSV,
            "text/csv",
        )
    }
    if with_items:
        files["items"] = ("items.csv", ITEMS_CSV, "text/csv")
    return client.post("/load", files=files)


def load_catalog(client: TestClient, *, with_items: bool = True):
    """Helper: load recommendations + orderable_items + inventory (+ items).

    Set ``with_items=False`` to exercise enrichment without items data loaded.
    """
    files = {
        "order_recommendations": (
            "order_recommendations.csv",
            RECOMMENDATIONS_CSV,
            "text/csv",
        ),
        "orderable_items": ("orderable_items.csv", ORDERABLE_ITEMS_CSV, "text/csv"),
        "inventory": ("inventory.csv", INVENTORY_CSV, "text/csv"),
    }
    if with_items:
        files["items"] = ("items.csv", ITEMS_CSV, "text/csv")
    return client.post("/load", files=files)
