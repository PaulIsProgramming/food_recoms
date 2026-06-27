"""Tests for the /orderable-items and /inventory endpoints + enrichment flag."""

from __future__ import annotations

from tests.conftest import load_catalog


# --- inventory ---------------------------------------------------------------


def test_inventory_requires_loaded_data(client):
    """409 when no inventory data has been loaded."""
    response = client.get("/inventory", params={"store_id": "store_a"})
    assert response.status_code == 409


def test_inventory_enrich_no_returns_raw_rows(client):
    """Default (enrich=no) returns raw inventory rows with item_number."""
    load_catalog(client)

    response = client.get("/inventory", params={"store_id": "store_a"})

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2  # store_a has items 1001 and 1002
    assert all("item_number" in r and "name" not in r for r in rows)
    assert {r["item_number"] for r in rows} == {1001, 1002}


def test_inventory_enrich_basic_replaces_id_with_name(client):
    """basic swaps item_number for the item name."""
    load_catalog(client)

    response = client.get(
        "/inventory", params={"store_id": "store_a", "enrich": "basic"}
    )

    assert response.status_code == 200
    rows = response.json()
    assert all("item_number" not in r and "name" in r for r in rows)
    assert {r["name"] for r in rows} == {"Organic Bananas", "Red Apples Gala"}


def test_inventory_enrich_detailed_nests_full_item(client):
    """detailed swaps item_number for a nested item object with all fields."""
    load_catalog(client)

    response = client.get(
        "/inventory", params={"store_id": "store_a", "enrich": "detailed"}
    )

    assert response.status_code == 200
    rows = response.json()
    bananas = next(r for r in rows if r["item"]["item_number"] == 1001)
    assert "item_number" not in bananas
    assert bananas["item"] == {
        "item_number": 1001,
        "name": "Organic Bananas",
        "category": "Fruits",
        "is_bio": False,
        "purchase_price": 0.89,
        "suggested_retail_price": 1.49,
    }


def test_enrich_without_items_returns_409(client):
    """Requesting enrichment without items.csv loaded is a 409."""
    load_catalog(client, with_items=False)

    response = client.get(
        "/inventory", params={"store_id": "store_a", "enrich": "basic"}
    )
    assert response.status_code == 409


def test_invalid_enrich_value_returns_422(client):
    """An out-of-enum enrich value is rejected by FastAPI with 422."""
    load_catalog(client)

    response = client.get(
        "/inventory", params={"store_id": "store_a", "enrich": "full"}
    )
    assert response.status_code == 422


# --- orderable items ---------------------------------------------------------


def test_orderable_items_returns_all_by_default(client):
    """No store_id returns every orderable-items row."""
    load_catalog(client)

    response = client.get("/orderable-items")

    assert response.status_code == 200
    assert len(response.json()) == 2  # one row per store in the sample


def test_orderable_items_store_filter(client):
    """store_id narrows the result set."""
    load_catalog(client)

    response = client.get("/orderable-items", params={"store_id": "store_b"})

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["store_id"] == "store_b"


def test_orderable_items_enrich_basic(client):
    """basic enrichment works on the orderable-items endpoint too."""
    load_catalog(client)

    response = client.get("/orderable-items", params={"enrich": "basic"})

    assert response.status_code == 200
    rows = response.json()
    assert all("item_number" not in r and "name" in r for r in rows)


# --- pagination --------------------------------------------------------------


def test_pagination_limit_and_offset(client):
    """limit caps the page; offset skips rows (sample has 2 orderable rows)."""
    load_catalog(client)

    first = client.get("/orderable-items", params={"limit": 1}).json()
    second = client.get("/orderable-items", params={"limit": 1, "offset": 1}).json()

    assert len(first) == 1
    assert len(second) == 1
    assert first[0] != second[0]  # different rows


def test_pagination_rejects_invalid_limit(client):
    """limit must be within [1, MAX_PAGE_LIMIT]; out-of-range is 422."""
    load_catalog(client)

    assert client.get("/orderable-items", params={"limit": 0}).status_code == 422
    assert client.get("/orderable-items", params={"limit": 5000}).status_code == 422
    assert client.get("/orderable-items", params={"offset": -1}).status_code == 422
