"""Tests for the /recommendations retrieval endpoint."""

from __future__ import annotations

from tests.conftest import load_sample


def test_retrieve_before_load_returns_409(client):
    """Retrieving with no data loaded is a 409 conflict."""
    response = client.get("/recommendations", params={"store_id": "store_a", "day": "2024-01-01"})

    assert response.status_code == 409


def test_retrieve_happy_path(client):
    """Returns exactly the rows matching the store and ordering day."""
    load_sample(client)

    response = client.get(
        "/recommendations", params={"store_id": "store_a", "day": "2024-01-01"}
    )

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    assert {r["item_number"] for r in rows} == {1001, 1002}
    assert all(r["store_id"] == "store_a" for r in rows)
    assert all(r["ordering_day"] == "2024-01-01" for r in rows)


def test_retrieve_unknown_store_returns_empty(client):
    """Unknown store/day yields an empty list with 200."""
    load_sample(client)

    response = client.get(
        "/recommendations", params={"store_id": "store_x", "day": "2024-01-01"}
    )

    assert response.status_code == 200
    assert response.json() == []


def test_retrieve_invalid_day_returns_422(client):
    """A non-ISO day is rejected with 422."""
    load_sample(client)

    response = client.get(
        "/recommendations", params={"store_id": "store_a", "day": "01-01-2024"}
    )

    assert response.status_code == 422
