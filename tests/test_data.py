"""Tests for the /load ingestion endpoint."""

from __future__ import annotations

from tests.conftest import load_sample


def test_load_happy_path_returns_row_counts(client):
    """Loading required + optional files reports per-dataset row counts."""
    response = load_sample(client, with_items=True)

    assert response.status_code == 200
    assert response.json() == {
        "ingested": {"items": 2, "order_recommendations": 4},
        "skipped": {},
    }


def test_load_only_required_file(client):
    """order_recommendations alone is sufficient."""
    response = load_sample(client)

    assert response.status_code == 200
    assert response.json() == {
        "ingested": {"order_recommendations": 4},
        "skipped": {},
    }


def test_load_skips_malformed_rows_and_reports_count(client):
    """Ragged rows are dropped, good rows kept, and the skip count reported."""
    csv_with_bad_row = (
        "store_id,item_number,ordering_day,delivery_day,recommended_quantity\n"
        "store_a,1001,2024-01-01,2024-01-02,18\n"
        "store_a,1002,2024-01-01,2024-01-02,5,EXTRA_FIELD\n"  # too many fields
        "store_a,1003,2024-01-01,2024-01-02,9\n"
    )
    response = client.post(
        "/load",
        files={
            "order_recommendations": (
                "order_recommendations.csv",
                csv_with_bad_row,
                "text/csv",
            )
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "ingested": {"order_recommendations": 2},
        "skipped": {"order_recommendations": 1},
    }


def test_load_rejects_missing_required_columns(client):
    """A file missing required columns is rejected with 422."""
    bad_csv = "store_id,item_number\nstore_a,1001\n"
    response = client.post(
        "/load",
        files={
            "order_recommendations": (
                "order_recommendations.csv",
                bad_csv,
                "text/csv",
            )
        },
    )

    assert response.status_code == 422
    assert "missing required columns" in response.json()["detail"]


def test_load_canonicalizes_store_id_and_dedups(client):
    """Dirty store_id variants collapse to one key and exact dups are dropped."""
    csv = (
        "store_id,item_number,ordering_day,delivery_day,recommended_quantity\n"
        "STORE_A,1001,2024-01-01,2024-01-02,18\n"   # uppercase
        " store_a ,1002,2024-01-01,2024-01-02,5\n"  # surrounding spaces
        "store_a,1001,2024-01-01,2024-01-02,18\n"   # exact dup of row 1 after cleaning
    )
    load = client.post(
        "/load",
        files={"order_recommendations": ("order_recommendations.csv", csv, "text/csv")},
    )
    # 3 input rows -> 2 after canonicalize + dedup.
    assert load.json()["ingested"] == {"order_recommendations": 2}

    # All rows are now reachable under the canonical 'store_a'.
    rows = client.get(
        "/recommendations", params={"store_id": "store_a", "day": "2024-01-01"}
    ).json()
    assert {r["item_number"] for r in rows} == {1001, 1002}


def test_load_rejects_oversized_upload(client, monkeypatch):
    """A file larger than the upload cap is rejected with 413."""
    import app.ingestion_service as ingestion

    monkeypatch.setattr(ingestion, "MAX_UPLOAD_BYTES", 50)  # tiny cap for the test
    big = "store_id,item_number,ordering_day,delivery_day,recommended_quantity\n" + (
        "store_a,1001,2024-01-01,2024-01-02,5\n" * 50
    )
    response = client.post(
        "/load",
        files={"order_recommendations": ("order_recommendations.csv", big, "text/csv")},
    )
    assert response.status_code == 413


def test_load_normalizes_unparseable_dates_to_null(client):
    """A non-ISO/garbage date becomes null, not the literal string 'nan'."""
    from app.store import store

    csv = (
        "store_id,item_number,ordering_day,delivery_day,recommended_quantity\n"
        "store_a,1001,2024-1-5,2024-01-06,5\n"   # non-zero-padded -> canonicalized
        "store_a,1002,not-a-date,2024-01-06,7\n"  # unparseable -> None
    )
    client.post(
        "/load",
        files={"order_recommendations": ("order_recommendations.csv", csv, "text/csv")},
    )
    days = list(store.order_recommendations["ordering_day"])
    assert "2024-01-05" in days   # zero-padded canonical form
    assert None in days           # unparseable coerced to None, not "nan"
    assert "nan" not in days


def test_load_requires_order_recommendations(client):
    """Omitting the required file is a 422 validation error from FastAPI."""
    response = client.post(
        "/load",
        files={"items": ("items.csv", "x", "text/csv")},
    )

    assert response.status_code == 422
