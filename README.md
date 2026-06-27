# FreshFlow Software Engineer Challenge

## Context

FreshFlow helps grocery stores decide **how much to order** of every fresh-food item, every day. We combine demand forecasts, current inventory, and supplier order windows to produce a recommended order quantity per item.

The `data/` folder contains CSV files for two stores.

## Data

| File | Description |
|---|---|
| `items.csv` | Item catalog — name, category, prices. Shared across stores. |
| `orderable_items.csv` | Per-store, per-day: which items can be ordered and when they'll be delivered. |
| `inventory.csv` | Per-store, per-day: how many pieces are in stock. |
| `order_recommendations.csv` | Per-store, per-day: pre-computed order recommendations with a recommended quantity. |

All quantities are in **pieces**.

## Task

Build a containerized service that exposes API endpoints to:

1. **Load data** — accept the CSV files and ingest them into the service.
2. **Retrieve recommendations** — return order recommendations for a given store and day.

### Requirements

- Python, any web framework
- Containerized: must run with `docker build` + `docker run`

## Submission

Send us a link to your git repository.

---

# Solution

A containerized **FastAPI** service that ingests the CSV datasets and serves
per-store, per-day order recommendations. FastAPI is used for its built-in
request validation (Pydantic), native multipart file uploads, and an
auto-generated interactive API explorer at `/docs`.

Ingested data is kept **in memory** (pandas DataFrames) for the lifetime of the
process — simple and sufficient for the challenge; it does not survive a restart.

---

> # ⚠️ READ THIS FIRST — you MUST call `POST /load` before anything else
>
> The service starts **empty**. Until you upload the CSVs, **every other
> endpoint returns `409 Conflict`** ("no data loaded").
>
> **Step 1 — load the data (once per process start):**
> ```bash
> curl -X POST http://localhost:8000/load \
>   -F "order_recommendations=@data/order_recommendations.csv" \
>   -F "items=@data/items.csv" \
>   -F "orderable_items=@data/orderable_items.csv" \
>   -F "inventory=@data/inventory.csv"
> ```
> (or in `/docs`: open **POST /load** → *Try it out* → attach the files → *Execute*)
>
> **Step 2 — now the other endpoints work**, e.g.
> `GET /recommendations?store_id=store_a&day=2024-01-01`.
>
> 🔁 Data lives in memory only — **after any restart you must `POST /load` again.**

---

## Run with Docker

```powershell
docker build -t freshflow .
docker run -p 8000:8000 freshflow
```

Then open http://localhost:8000/docs.

## Run locally (without Docker)

```powershell
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Endpoints

### Required by the challenge

| Method | Path | Description |
|---|---|---|
| `POST` | `/load` | Upload the CSV files (multipart). `order_recommendations.csv` is required; `items`, `orderable_items`, `inventory` are optional. Returns rows ingested (and any malformed rows skipped) per file. |
| `GET` | `/recommendations?store_id=&day=` | Recommendations for a store on an ordering day (`day` is the `ordering_day`, ISO `YYYY-MM-DD`). |

`/recommendations` returns `409` if no data has been loaded, `422` for a
malformed `day`, and `200` with an empty list when no rows match.

### Additional routes (add-ons)

These go beyond the brief — each turns the raw CSVs into something a grocery
ops team could actually act on.

| Endpoint | When to use it | What it tells you |
|---|---|---|
| `GET /orderable-items?store_id=&enrich=&limit=&offset=` | Browsing the catalog of what *can* be ordered for a store, and when it'd be delivered. | The order window per item; with `enrich` you read product names/details instead of bare IDs — no second lookup needed. |
| `GET /inventory?store_id=&enrich=&limit=&offset=` | Checking raw stock levels per day for a store. | How much is physically on the shelf over time — the ground truth every ordering decision starts from. |
| `GET /inventory-summary?store_id=` | The daily ops glance: *which items need attention right now?* | Per item: current stock, a **low/normal/high** status (vs the item's own norm), and the last 5 order dates with the stock that triggered each — spot under-/over-stocking at a glance. |
| `GET /recommendations/recompute?store_id=&day=&cover_days=` | Sanity-checking or explaining an order: *why this quantity?* Tune `cover_days` to simulate more/less buffer. | A transparent, reproducible order quantity from a base-stock rule, shown **next to the file's number with the delta** — turns a black-box figure into something you can audit and trust. |
| `GET /health` | Load balancers, container orchestration, uptime checks. | Whether the service is alive (`{"status":"ok"}`). |
| `GET /docs` | Exploring or demoing the API by hand. | A live, try-it-out Swagger UI for every endpoint — zero client code needed. |

### The `enrich` flag

Available on every item-keyed endpoint — `/orderable-items`, `/inventory`,
`/inventory-summary`, and `/recommendations/recompute`. Controls how each row's
`item_number` is presented:

| Value | Effect |
|---|---|
| `no` (default) | Raw rows from the dataset, unchanged. |
| `basic` | `item_number` replaced by the item's `name` (from `items.csv`). |
| `detailed` | `item_number` replaced by a nested `item` object with all `items.csv` fields. |

`basic`/`detailed` require `items.csv` to have been loaded — otherwise `409`.

### Pagination (orderable-items & inventory)

These datasets are large (~25k orderable-item rows), so both endpoints are
paginated:

| Param | Default | Rule |
|---|---|---|
| `limit` | `100` | `1`–`1000`; out of range → `422` |
| `offset` | `0` | `≥ 0`; negative → `422` |

Rows are sliced *before* conversion and enrichment, so only the requested page
is materialized. Page through with increasing `offset`:

```bash
curl "http://localhost:8000/orderable-items?limit=50&offset=0"
curl "http://localhost:8000/orderable-items?limit=50&offset=50"
```

```bash
# Raw inventory
curl "http://localhost:8000/inventory?store_id=store_a"
# Names instead of ids
curl "http://localhost:8000/inventory?store_id=store_a&enrich=basic"
# Full item details, all orderable items
curl "http://localhost:8000/orderable-items?enrich=detailed"
```

### Inventory summary (`/inventory-summary`)

For a store, returns one entry per unique item:

```json
{
  "item_number": 1001,
  "current_stock": 24.0,
  "stock_status": "normal",
  "last_orders": [
    {"date": "2024-12-31 00:00", "current_quantity_in_store": 21.8},
    {"date": "2024-12-30 00:00", "current_quantity_in_store": 34.4},
    {"date": "2024-12-28 00:00", "current_quantity_in_store": 29.3}
  ]
}
```

- **`current_stock`** — quantity on the item's most recent recorded day in `inventory`.
- **`last_orders`** — up to 5 most recent **distinct** order dates from
  `orderable_items.ordering_day`, newest first, each paired with the stock on
  hand that day. The source is date-only, so times render as midnight
  (`YYYY-MM-DD HH:MM`, naive — no timezone conversion). Empty if
  `orderable_items` wasn't loaded.
  - `current_quantity_in_store` is the **inventory level on the order day**
    (the stock that triggered the order) — *not* an amount ordered, which the
    data doesn't record. `null` if there's no inventory row for that exact day.
- The `enrich` flag (`no`/`basic`/`detailed`) works here too, replacing
  `item_number` with the item name or full item object.
- **`stock_status`** — current stock vs. the item's own average daily stock:

  | Status | Condition |
  |---|---|
  | `low` | `current < 0.5 × average` |
  | `high` | `current > 1.5 × average` |
  | `normal` | otherwise |

  Self-calibrating per item, so items with different normal levels are judged
  fairly. Bands (`0.5` / `1.5`) are named constants in
  `app/inventory_summary_service.py`. Requires only `inventory` loaded (`409`
  otherwise).

```bash
curl "http://localhost:8000/inventory-summary?store_id=store_a"
```

### Recompute recommendations (`/recommendations/recompute`)

A transparent **base-stock (order-up-to)** recommender, reverse-engineered from
the provided data (see [DATA_NOTES.md](DATA_NOTES.md)). For a full step-by-step
walkthrough with assumptions and worked examples, see
**[ALGORITHM.md](ALGORITHM.md)**.

```
estimated_daily_demand = mean stock drop over days when stock FELL (history up to `day`;
                         delivery/flat days excluded so sales aren't diluted ~2x)
target_stock           = cover_days × estimated_daily_demand     (cover_days default 5)
recomputed_quantity    = max(0, round(target_stock − current_stock))
```

Where the loaded file has a matching row, the response includes `file_quantity`
and `delta` so you can compare:

```json
{
  "item_number": 1001, "current_stock": 29.4, "estimated_daily_demand": 7.15,
  "target_stock": 35.75, "recomputed_quantity": 6, "insufficient_history": false,
  "file_quantity": 23.0, "delta": -17.0
}
```

`insufficient_history` is `true` when there's too little inventory history to
estimate demand (e.g. a single day) — so a `0` quantity isn't mistaken for
genuinely-zero demand.

Across all ~24k order rows this baseline reproduces the file's quantities to a
**median absolute error of ~5 pieces** at the calibrated `cover_days=5`. It's a
deliberately simple, explainable baseline, not a replica of the production
model. Requires `inventory` (`409` otherwise); `409` also if `day` is invalid
(`422`).

> **Why orders can be 0:** this is order-up-to logic — if current stock already
> meets the target, the order is 0. Lowering `cover_days` lowers the target, so
> more items come out 0; raising it orders more.

```bash
curl "http://localhost:8000/recommendations/recompute?store_id=store_a&day=2024-06-15"
curl "http://localhost:8000/recommendations/recompute?store_id=store_a&day=2024-06-15&cover_days=10"
```

## Data cleaning at ingestion

Beyond validation, `parse_csv` applies cheap, lossless fixes to every uploaded
file (tier-A in [DATA_NOTES.md](DATA_NOTES.md)):

- **Canonicalize `store_id`** (`strip().lower()`) — the sample data has 8
  variants (`STORE_A`, `" store_a"`, `"store_a "`) for 2 real stores. Without
  this, exact-match `store_id` filters silently miss rows.
- **Canonicalize `category`** (`strip().title()`) — merges `FRUITS/Fruits/fruits`.
- **Drop exact duplicate rows** (after the above, so case/space-only dups collapse).

Judgement-call repairs (imputing prices/stock, key-level dedup) are intentionally
left to a separate cleaning stage — see DATA_NOTES.md.

## Input validation

External input is never trusted — every request is checked before it touches
the store. Validation happens at two layers:

**1. Uploaded CSVs (`POST /load`)** — all files flow through one chokepoint,
`parse_csv` in `app/ingestion_service.py`, so the checks are identical for
every dataset:

| Check | Result if it fails |
|---|---|
| File parses as CSV (bytes/encoding) | `422` — unparseable file rejected |
| Required columns present (per dataset) | `422` — names the missing columns |
| Each row has the right number of fields | malformed row **skipped** and counted, reported in the `skipped` map (see [DATA_NOTES.md](DATA_NOTES.md)) |
| Date columns (`day`, `ordering_day`, `delivery_day`) | normalized to ISO strings so later filtering is exact |

**2. Query parameters (GET endpoints)** — declared with types and constraints,
so FastAPI/Pydantic validate them automatically and reject bad input with `422`
*before* the handler runs:

| Parameter | Rule |
|---|---|
| `store_id`, `day` (recommendations) | required — missing → `422` |
| `day` | must be an ISO `YYYY-MM-DD` date → otherwise `422` |
| `enrich` | must be one of `no` / `basic` / `detailed` (enum) → otherwise `422` |

**3. State preconditions** — handlers verify required data is loaded:

| Condition | Result |
|---|---|
| Retrieve/list before any data loaded | `409` |
| `enrich=basic\|detailed` without `items.csv` loaded | `409` |

The interactive docs at `/docs` show each parameter's type and allowed values,
and the validation errors are returned as structured JSON.


## Example usage (curl)

```bash
# Load the provided sample data
curl -X POST http://localhost:8000/load \
  -F "order_recommendations=@data/order_recommendations.csv" \
  -F "items=@data/items.csv" \
  -F "orderable_items=@data/orderable_items.csv" \
  -F "inventory=@data/inventory.csv"

# Retrieve recommendations for store_a on 2024-01-01
curl "http://localhost:8000/recommendations?store_id=store_a&day=2024-01-01"
```

## Tests

```powershell
pip install -r requirements.txt
pytest -q
```

## Project layout

```
app/
  main.py                     # FastAPI app + routers, root & health
  store.py                    # in-memory DataStore (pandas)
  models.py                   # Pydantic response models
  ingestion_service.py        # CSV parse + validation + tier-A cleaning
  enrichment_service.py       # shared item-enrichment (enrich flag)
  inventory_summary_service.py # per-store stock summary logic
  recompute_service.py        # base-stock recommendation engine
  data_routes.py              # POST /load
  recommendations_routes.py   # GET /recommendations (+ /recompute)
  orderable_items_routes.py   # GET /orderable-items
  inventory_routes.py         # GET /inventory
  inventory_summary_routes.py # GET /inventory-summary
tests/                        # pytest + FastAPI TestClient
Dockerfile
requirements.txt
```
