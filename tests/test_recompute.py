"""Tests for the /recommendations/recompute endpoint (base-stock rule)."""

from __future__ import annotations

# One item, declining stock so demand is well-defined.
# quantities: 30 -> 20 -> 10 (drops of 10/day) -> avg demand = 10.
INVENTORY = (
    "store_id,item_number,day,quantity\n"
    "store_a,1001,2024-01-01,30\n"
    "store_a,1001,2024-01-02,20\n"
    "store_a,1001,2024-01-03,10\n"
)

RECOMMENDATIONS = (
    "store_id,item_number,ordering_day,delivery_day,recommended_quantity\n"
    "store_a,1001,2024-01-03,2024-01-04,42\n"
)


def _load(client):
    return client.post(
        "/load",
        files={
            "order_recommendations": ("r.csv", RECOMMENDATIONS, "text/csv"),
            "inventory": ("inv.csv", INVENTORY, "text/csv"),
        },
    )


def test_recompute_requires_inventory(client):
    """409 when inventory isn't loaded."""
    client.post(
        "/load",
        files={"order_recommendations": ("r.csv", RECOMMENDATIONS, "text/csv")},
    )
    r = client.get(
        "/recommendations/recompute", params={"store_id": "store_a", "day": "2024-01-03"}
    )
    assert r.status_code == 409


def test_recompute_base_stock_math(client):
    """order = max(0, cover_days*demand - current_stock), with file comparison."""
    _load(client)

    r = client.get(
        "/recommendations/recompute",
        params={"store_id": "store_a", "day": "2024-01-03", "cover_days": 5},
    )
    assert r.status_code == 200
    row = r.json()[0]

    # demand = mean drop = 10; current stock on 2024-01-03 = 10.
    assert row["estimated_daily_demand"] == 10.0
    assert row["current_stock"] == 10.0
    assert row["target_stock"] == 50.0          # 5 * 10
    assert row["recomputed_quantity"] == 40     # 50 - 10
    assert row["file_quantity"] == 42.0
    assert row["delta"] == -2.0                 # 40 - 42


def test_recompute_clamps_at_zero(client):
    """When stock already exceeds target, the order is 0 (never negative)."""
    _load(client)

    r = client.get(
        "/recommendations/recompute",
        params={"store_id": "store_a", "day": "2024-01-03", "cover_days": 0.5},
    ).json()
    # target = 0.5*10 = 5, current = 10 -> max(0, -5) = 0
    assert r[0]["recomputed_quantity"] == 0


def test_recompute_uses_history_up_to_day(client):
    """Asking for an earlier day uses only inventory up to that day."""
    _load(client)

    r = client.get(
        "/recommendations/recompute",
        params={"store_id": "store_a", "day": "2024-01-02", "cover_days": 5},
    ).json()
    # Up to 2024-01-02: quantities 30,20 -> current 20, demand 10.
    assert r[0]["current_stock"] == 20.0
    assert r[0]["recomputed_quantity"] == 30    # 50 - 20
    assert r[0]["file_quantity"] is None        # no file row for that day
    assert r[0]["delta"] is None


def test_recompute_invalid_day(client):
    """Bad date -> 422."""
    _load(client)
    r = client.get(
        "/recommendations/recompute",
        params={"store_id": "store_a", "day": "03-01-2024"},
    )
    assert r.status_code == 422


def test_recompute_insufficient_history_flag(client):
    """A single inventory day -> no demand signal -> insufficient_history true."""
    inv = "store_id,item_number,day,quantity\nstore_a,1001,2024-01-01,10\n"
    client.post("/load", files={
        "order_recommendations": ("r.csv", RECOMMENDATIONS, "text/csv"),
        "inventory": ("inv.csv", inv, "text/csv"),
    })

    row = client.get(
        "/recommendations/recompute",
        params={"store_id": "store_a", "day": "2024-01-03"},
    ).json()[0]

    assert row["insufficient_history"] is True
    assert row["estimated_daily_demand"] == 0.0
    assert row["recomputed_quantity"] == 0


def test_recompute_flat_series_is_insufficient(client):
    """A flat series shows no stock decrease, so consumption can't be observed."""
    inv = (
        "store_id,item_number,day,quantity\n"
        "store_a,1001,2024-01-01,10\nstore_a,1001,2024-01-02,10\n"
    )
    client.post("/load", files={
        "order_recommendations": ("r.csv", RECOMMENDATIONS, "text/csv"),
        "inventory": ("inv.csv", inv, "text/csv"),
    })

    row = client.get(
        "/recommendations/recompute",
        params={"store_id": "store_a", "day": "2024-01-03"},
    ).json()[0]
    # No day had a decrease -> demand can't be estimated -> flagged.
    assert row["insufficient_history"] is True
    assert row["estimated_daily_demand"] == 0.0


def test_recompute_demand_excludes_delivery_days(client):
    """Demand averages only days stock fell, not delivery/flat days."""
    inv = (
        "store_id,item_number,day,quantity\n"
        "store_a,1001,2024-01-01,20\n"   # -
        "store_a,1001,2024-01-02,10\n"   # drop 10  (consumption)
        "store_a,1001,2024-01-03,25\n"   # +15 delivery (drop 0, excluded)
        "store_a,1001,2024-01-04,20\n"   # drop 5   (consumption)
    )
    client.post("/load", files={
        "order_recommendations": ("r.csv", RECOMMENDATIONS, "text/csv"),
        "inventory": ("inv.csv", inv, "text/csv"),
    })

    row = client.get(
        "/recommendations/recompute",
        params={"store_id": "store_a", "day": "2024-01-04", "cover_days": 4},
    ).json()[0]
    # consumption days = [10, 5] -> mean 7.5  (NOT (10+0+5)/3 = 5.0)
    assert row["estimated_daily_demand"] == 7.5
    assert row["insufficient_history"] is False
    # target = 4 * 7.5 = 30; current stock (latest day) = 20 -> order 10
    assert row["recomputed_quantity"] == 10


def test_recompute_unknown_store_is_empty(client):
    """No inventory history for the store -> 200 with empty list."""
    _load(client)
    r = client.get(
        "/recommendations/recompute",
        params={"store_id": "store_x", "day": "2024-01-03"},
    )
    assert r.status_code == 200
    assert r.json() == []


def test_recompute_enrich_basic(client):
    """enrich=basic swaps item_number for name, keeping the recompute fields."""
    _load(client)
    # _load has no items.csv; add it so enrichment has data.
    items = (
        "item_number,name,category,is_bio,purchase_price,suggested_retail_price\n"
        "1001,Organic Bananas,Fruits,False,0.89,1.49\n"
    )
    client.post("/load", files={
        "order_recommendations": ("r.csv", RECOMMENDATIONS, "text/csv"),
        "inventory": ("inv.csv", INVENTORY, "text/csv"),
        "items": ("i.csv", items, "text/csv"),
    })

    row = client.get(
        "/recommendations/recompute",
        params={"store_id": "store_a", "day": "2024-01-03", "enrich": "basic"},
    ).json()[0]

    assert "item_number" not in row and row["name"] == "Organic Bananas"
    assert {"recomputed_quantity", "current_stock", "delta"} <= row.keys()


def test_recompute_enrich_without_items_409(client):
    """Enrichment without items.csv loaded is a 409."""
    _load(client)  # no items
    r = client.get(
        "/recommendations/recompute",
        params={"store_id": "store_a", "day": "2024-01-03", "enrich": "detailed"},
    )
    assert r.status_code == 409
