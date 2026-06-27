"""Tests for the /inventory-summary endpoint."""

from __future__ import annotations

# items 1001/1002/1003 used below; 1003 has no orders.
ITEMS = (
    "item_number,name,category,is_bio,purchase_price,suggested_retail_price\n"
    "1001,A,Cat,False,1,2\n"
    "1002,B,Cat,False,1,2\n"
    "1003,C,Cat,False,1,2\n"
)

# store_a: 1001 trends down (-> low), 1002 spikes up (-> high), 1003 flat (-> normal).
# A store_b row is included to confirm store filtering.
INVENTORY = (
    "store_id,item_number,day,quantity\n"
    "store_a,1001,2024-01-01,10\n"
    "store_a,1001,2024-01-02,20\n"
    "store_a,1001,2024-01-03,2\n"
    "store_a,1002,2024-01-01,5\n"
    "store_a,1002,2024-01-02,5\n"
    "store_a,1002,2024-01-03,20\n"
    "store_a,1003,2024-01-01,8\n"
    "store_a,1003,2024-01-02,8\n"
    "store_a,1003,2024-01-03,8\n"
    "store_b,1001,2024-01-01,100\n"
)

# 1001 has 6 distinct order days plus a duplicate (tests dedup + cap at 5).
ORDERABLE = (
    "store_id,item_number,ordering_day,delivery_day,purchase_price,suggested_retail_price,profit_margin,tags,category\n"
    "store_a,1001,2024-01-01,2024-01-02,1,2,0.5,,Cat\n"
    "store_a,1001,2024-01-02,2024-01-03,1,2,0.5,,Cat\n"
    "store_a,1001,2024-01-03,2024-01-04,1,2,0.5,,Cat\n"
    "store_a,1001,2024-01-04,2024-01-05,1,2,0.5,,Cat\n"
    "store_a,1001,2024-01-05,2024-01-06,1,2,0.5,,Cat\n"
    "store_a,1001,2024-01-06,2024-01-07,1,2,0.5,,Cat\n"
    "store_a,1001,2024-01-06,2024-01-07,1,2,0.5,,Cat\n"
    "store_a,1002,2024-02-10,2024-02-11,1,2,0.5,,Cat\n"
    "store_b,1001,2024-09-09,2024-09-10,1,2,0.5,,Cat\n"
)

RECOMMENDATIONS = (
    "store_id,item_number,ordering_day,delivery_day,recommended_quantity\n"
    "store_a,1001,2024-01-01,2024-01-02,5\n"
)


def _load(client, *, with_orderable: bool = True):
    files = {
        "order_recommendations": ("r.csv", RECOMMENDATIONS, "text/csv"),
        "items": ("i.csv", ITEMS, "text/csv"),
        "inventory": ("inv.csv", INVENTORY, "text/csv"),
    }
    if with_orderable:
        files["orderable_items"] = ("o.csv", ORDERABLE, "text/csv")
    return client.post("/load", files=files)


def test_summary_requires_inventory_loaded(client):
    """409 when no inventory data is loaded."""
    assert client.get("/inventory-summary", params={"store_id": "store_a"}).status_code == 409


def test_summary_shape_and_status(client):
    """One entry per item, sorted, with correct current stock and status."""
    _load(client)

    rows = client.get("/inventory-summary", params={"store_id": "store_a"}).json()

    assert [r["item_number"] for r in rows] == [1001, 1002, 1003]
    by_item = {r["item_number"]: r for r in rows}

    # 1001: latest day quantity is 2, avg ~10.67 -> low.
    assert by_item[1001]["current_stock"] == 2.0
    assert by_item[1001]["stock_status"] == "low"
    # 1002: latest 20, avg 10 -> high.
    assert by_item[1002]["current_stock"] == 20.0
    assert by_item[1002]["stock_status"] == "high"
    # 1003: flat 8 -> normal.
    assert by_item[1003]["stock_status"] == "normal"


def test_summary_last_orders_newest_first_deduped_capped(client):
    """last_orders: distinct dates newest-first (max 5) with stock on each day.

    1001 is ordered on 2024-01-01..06; inventory only has days 01-03, so the
    later order dates have no stock row -> quantity is None.
    """
    _load(client)

    rows = client.get("/inventory-summary", params={"store_id": "store_a"}).json()
    by_item = {r["item_number"]: r for r in rows}

    assert by_item[1001]["last_orders"] == [
        {"date": "2024-01-06 00:00", "current_quantity_in_store": None},
        {"date": "2024-01-05 00:00", "current_quantity_in_store": None},
        {"date": "2024-01-04 00:00", "current_quantity_in_store": None},
        {"date": "2024-01-03 00:00", "current_quantity_in_store": 2.0},
        {"date": "2024-01-02 00:00", "current_quantity_in_store": 20.0},
    ]
    # 1002 ordered on 2024-02-10; no inventory row that day -> None.
    assert by_item[1002]["last_orders"] == [
        {"date": "2024-02-10 00:00", "current_quantity_in_store": None}
    ]
    # 1003 has no orders.
    assert by_item[1003]["last_orders"] == []


def test_summary_unknown_store_is_empty(client):
    """A store with no inventory rows returns an empty list (200)."""
    _load(client)

    response = client.get("/inventory-summary", params={"store_id": "store_x"})
    assert response.status_code == 200
    assert response.json() == []


def test_summary_without_orderable_has_empty_orders(client):
    """If orderable-items isn't loaded, last_orders is empty for every item."""
    _load(client, with_orderable=False)

    rows = client.get("/inventory-summary", params={"store_id": "store_a"}).json()
    assert rows  # inventory still summarized
    assert all(r["last_orders"] == [] for r in rows)


def test_summary_enrich_basic_replaces_item_number_with_name(client):
    """enrich=basic swaps item_number for name, keeping the summary fields."""
    _load(client)

    rows = client.get(
        "/inventory-summary", params={"store_id": "store_a", "enrich": "basic"}
    ).json()

    assert all("item_number" not in r and "name" in r for r in rows)
    # Summary fields are preserved alongside the enriched item.
    assert all({"current_stock", "stock_status", "last_orders"} <= r.keys() for r in rows)
    assert {"A", "B", "C"} == {r["name"] for r in rows}


def test_summary_enrich_detailed_nests_item(client):
    """enrich=detailed swaps item_number for a nested item object."""
    _load(client)

    rows = client.get(
        "/inventory-summary", params={"store_id": "store_a", "enrich": "detailed"}
    ).json()

    first = next(r for r in rows if r["item"]["item_number"] == 1001)
    assert "item_number" not in first
    assert first["item"]["name"] == "A"
    assert "current_stock" in first


def test_summary_handles_bad_ordering_day_without_500(client):
    """An unparseable order date is skipped, not crashed on (was a 500)."""
    bad_orderable = (
        "store_id,item_number,ordering_day,delivery_day,purchase_price,suggested_retail_price,profit_margin,tags,category\n"
        "store_a,1001,not-a-date,2024-01-02,1,2,0.5,,Cat\n"   # unparseable -> dropped
        "store_a,1001,2024-01-02,2024-01-03,1,2,0.5,,Cat\n"   # good
    )
    client.post("/load", files={
        "order_recommendations": ("r.csv", RECOMMENDATIONS, "text/csv"),
        "inventory": ("inv.csv", INVENTORY, "text/csv"),
        "orderable_items": ("o.csv", bad_orderable, "text/csv"),
    })

    response = client.get("/inventory-summary", params={"store_id": "store_a"})
    assert response.status_code == 200
    orders = {r["item_number"]: r["last_orders"] for r in response.json()}
    # Only the parseable order date survives.
    assert [o["date"] for o in orders[1001]] == ["2024-01-02 00:00"]


def test_summary_current_stock_ignores_null_date_rows(client):
    """A row with an unparseable inventory day must not be picked as latest."""
    inv = (
        "store_id,item_number,day,quantity\n"
        "store_a,1001,2024-01-01,10\n"
        "store_a,1001,garbage,999\n"   # bad date -> must be ignored, not 'latest'
    )
    client.post("/load", files={
        "order_recommendations": ("r.csv", RECOMMENDATIONS, "text/csv"),
        "inventory": ("inv.csv", inv, "text/csv"),
    })

    rows = client.get("/inventory-summary", params={"store_id": "store_a"}).json()
    # current stock is the real latest (10), not the garbage-date 999.
    assert rows[0]["current_stock"] == 10.0


def test_summary_enrich_without_items_returns_409(client):
    """Enrichment without items.csv loaded is a 409."""
    # Load inventory + orderable but NOT items.
    files = {
        "order_recommendations": ("r.csv", RECOMMENDATIONS, "text/csv"),
        "inventory": ("inv.csv", INVENTORY, "text/csv"),
        "orderable_items": ("o.csv", ORDERABLE, "text/csv"),
    }
    client.post("/load", files=files)

    response = client.get(
        "/inventory-summary", params={"store_id": "store_a", "enrich": "basic"}
    )
    assert response.status_code == 409
