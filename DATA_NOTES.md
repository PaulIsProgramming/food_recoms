# Data Quality Notes

Observations about the provided `data/` CSV files, and how this service handles
them. Kept separate from the main README so it can be discussed on its own.

## Design note: only ONE file is required to load

`/load` accepts all four CSVs, but only **`order_recommendations.csv` is
required** — the other three (`items`, `orderable_items`, `inventory`) are
optional. See `app/data_routes.py`: `File(...)` vs `File(None)`.

Rationale:
- The retrieve endpoint (`GET /recommendations`) reads **only** the
  `order_recommendations` dataset, so that one file is sufficient to make the
  service fully functional. (Covered by `test_load_only_required_file`.)
- The other three are accepted because the task says "accept the CSV files"
  (plural) and to support future features without an API change — e.g.
  enriching the response with item name/category from `items.csv`, or
  inventory-aware logic from `inventory.csv`.

Talking point: this keeps the *required* surface minimal while ingesting the
full dataset when available — separation between "what the current endpoint
needs" and "what the service can hold."

## Finding: malformed (ragged) rows in the sample data

Some rows have a different field count than their header. Example —
`orderable_items.csv` header declares **9** columns:

```
store_id,item_number,ordering_day,delivery_day,purchase_price,suggested_retail_price,profit_margin,tags,category
```

but line 51 has a trailing comma, producing **10** fields:

```
store_a,1099,2024-01-13,2024-01-15,1.41,2.46,0.4514,,Fruits,
```

A strict `pandas.read_csv` aborts the **entire file** on the first such row:

```
Error tokenizing data. C error: Expected 9 fields in line 51, saw 10
```

Because `/load` ingests several files, one bad row in *any* file would otherwise
block the whole load — including `order_recommendations.csv`, which backs the
retrieve endpoint.

## How the service handles it

A single chokepoint — `parse_csv` in `app/ingestion_service.py` — parses **every**
uploaded file, so the handling is uniform across all four datasets:

1. **Ragged rows** (wrong field count): skipped via
   `read_csv(..., engine="python", on_bad_lines=<callable>)`. The callable counts
   each skipped row. Good rows are still ingested.
2. **Skip count is reported, never silent.** The `/load` response includes a
   `skipped` map, e.g.:
   ```json
   { "ingested": { "orderable_items": 12345 }, "skipped": { "orderable_items": 1 } }
   ```
3. **Structural failures remain hard errors (422):** unparseable bytes, or a file
   missing required columns. These indicate the wrong file was sent, not a single
   dirty row.

This favours *load succeeds, nothing dropped silently* over *fail loud on the
first defect* — appropriate when the upstream data is known to be imperfect but
the bad rows are a tiny fraction.

## Other observations (surfaced but NOT handled in code)

These showed up when loading the real data and querying
`store_a` / `2024-01-01`. Left as-is for now — each needs a product decision
before the service should silently alter it. Flagged here for discussion.

- **Negative recommended quantity.** Item `1041` returns
  `recommended_quantity: -1`. Looks like a sentinel/error value rather than a
  real order. Open question: drop it, clamp to 0, or surface as-is?
- **Duplicate rows.** For the same `store_id` + `item_number` + `ordering_day`,
  some items appear more than once (e.g. `1023`, `1025` on `store_a`
  `2024-01-01`). No de-duplication is applied; the retrieve endpoint returns
  every matching row. Open question: is `(store_id, item_number, ordering_day)`
  meant to be unique? If so, which row wins?
- **Volume of skipped rows.** ~240 rows skipped in `orderable_items.csv` — not a
  one-off typo but a systematic export issue worth fixing upstream.

## What I'd do for production

- **Schema enforcement at ingestion** (e.g. Pandera / Pydantic per-row, or a
  warehouse load with a strict schema): typed columns, value ranges
  (quantities ≥ 0, prices ≥ 0), date format, referential checks
  (`item_number` exists in `items`).
- **Quarantine, don't just count:** write rejected rows to a dead-letter
  location with the reason, so they can be inspected and re-fed.
- **Fix at source:** the trailing-comma defect looks like an export bug upstream;
  worth flagging to whoever generates the CSVs.
- **Observability:** emit a metric/alert when the skipped-row ratio crosses a
  threshold, so a sudden data-quality regression is noticed.

---

# Full data-quality audit (all four files)

A systematic pass over every column of all four CSVs (counts below are from the
provided `data/`; ragged rows skipped on read, `store_id` normalized only for
cross-file comparison). Every issue lists three remediation options at different
stages:

- **(A) Tolerate as-is** — handle at read/ingest time, lose as little data as
  possible. Cheapest, no upstream change.
- **(B) Clean after landing** — a curation step that repairs the data once it's
  in the file/table (canonicalize, impute, dedup).
- **(C) Prevent at source** — stop it being produced wrong in the first place.

> ✅ **Now handled at ingestion (tier A).** `parse_csv` skips ragged rows,
> **canonicalizes `store_id` and `category`, drops exact duplicates, and coerces
> dates** (`to_datetime` → canonical zero-padded ISO; unparseable/missing →
> `None`, never the string `"nan"`). Consumers then drop null dates rather than
> mis-sorting or crashing on them, and a per-file **upload size cap** (413)
> guards against memory exhaustion. This fixed the highest-value bugs: the
> `store_id` filter miss (`STORE_A`/`" store_a"`), and unparseable dates that
> previously (a) crashed `/inventory-summary` in `strptime` and (b) were
> mis-picked as the "latest" day's stock (sorting after real dates).
>
> Still **unhandled** (deliberately — they need product decisions): orphan
> item_numbers, missing-value imputation, key-level duplicates, negative recs,
> outliers, fractional units, coverage gaps.

## Summary

| # | Issue | File(s) | Evidence | Severity |
|---|---|---|---|---|
| 1 | Ragged rows (extra field) | orderable_items | 240 / 25,200 rows | med |
| 2 | `store_id` not canonical | all 3 txn files | 8 variants for 2 stores (case + whitespace) | **high** |
| 3 | `category` not canonical | items, orderable_items | `FRUITS/Fruits/fruits`, `VEGETABLES/…` | low |
| 4 | Orphan `item_number` (no catalog entry) | inventory, orderable, recs | `1099`; recs also `9901/9902/9903` | med |
| 5 | Missing values | orderable_items | `purchase_price` & `profit_margin` null in 1,287 rows | med |
| 6 | Unparseable / missing dates | inventory | 803 `day` values → NaT | **high** |
| 7 | Duplicate rows | recs (300), orderable (198), inventory (837 dup keys) | exact + key dups | med |
| 8 | Negative `recommended_quantity` | recommendations | 515 rows, min −5 | med |
| 9 | Extreme outliers | recommendations | max 1,939 vs 99th pct 52 (227 rows above) | med |
| 10 | Fractional "pieces" | inventory | 87% of `quantity` non-integer | **high** (semantic) |
| 11 | `profit_margin` inconsistent | orderable_items | 67% disagree with `1 − cost/price` | low |
| 12 | Coverage gaps | inventory, recs↔inventory | 4,942 missing day-rows; 4.3% of recs have no inventory row | med |

## Issue detail + remediation

### 1. Ragged rows — `orderable_items` (240 rows)
A trailing comma yields 10 fields vs a 9-column header (see top of this file).
- **(A)** Skip + count on read (current behavior). Loses 240 rows (~1%).
- **(B)** Right-trim trailing empty fields during a cleaning pass, then re-parse — recovers the rows instead of dropping them.
- **(C)** Fix the exporter's CSV writer (quote/terminate fields correctly); add a column-count check in the producing job's CI.

### 2. `store_id` not canonical — **all transactional files** (8 variants)
Raw values: `store_a`, `STORE_A`, `" store_a"`, `"store_a "` (and `store_b` ditto) — 2 real stores fragmented into 8 keys.
- **(A)** Normalize on ingest: `store_id.str.strip().str.lower()` in `parse_csv`. One line, fixes the live filter bug, no data lost.
- **(B)** A cleaning job maps every variant to a canonical store code via a lookup table; reject unknown codes to a quarantine.
- **(C)** Enforce an enum/foreign-key on `store_id` at write time (the source system should emit a controlled identifier, never free text).

### 3. `category` not canonical — `items`, `orderable_items`
Case variants: `FRUITS / Fruits / fruits`, `VEGETABLES / Vegetables / vegetables`.
- **(A)** Title-case + strip when reading; group case-insensitively in any aggregation.
- **(B)** Map to a canonical category dimension table during cleaning.
- **(C)** Constrain `category` to a fixed code list at source.

### 4. Orphan `item_number` — not in `items.csv` catalog
`1099` appears in inventory/orderable/recs; recs additionally reference `9901/9902/9903` that exist in **no** catalog. Enrichment (`basic`/`detailed`) returns `null` for these.
- **(A)** Keep the rows but leave enrichment fields `null` (current behavior); log the orphan ids.
- **(B)** Reconcile during cleaning: backfill the catalog, or drop/quarantine transactions for unknown items.
- **(C)** Referential-integrity check at source so a transaction can't reference a non-existent item (FK constraint).

### 5. Missing values — `orderable_items` (1,287 rows)
`purchase_price` and `profit_margin` null together.
- **(A)** Read as `null` and exclude from price-dependent calcs (don't fabricate).
- **(B)** Impute during cleaning — e.g. fill `purchase_price` from `items.csv` or the item's recent average; recompute `profit_margin` from price/cost. *(This is the "compute averages when missing" idea — fine for derived/optional fields, risky for money fields, so flag imputed values.)*
- **(C)** Make the field mandatory at source, or have the producer emit an explicit "price unknown" reason rather than a blank.

### 6. Unparseable / missing dates — `inventory` (803 `day` → NaT)
- **(A)** `to_datetime(errors="coerce")` and drop/segregate NaT rows so they don't corrupt time logic.
- **(B)** Cleaning step repairs recoverable formats (locale variants) and quarantines the rest.
- **(C)** Enforce ISO-8601 `date` typing at source; reject non-dates on write.

### 7. Duplicate rows — recs (300 exact), orderable (198 exact), inventory (837 dup `(store,item,day)`)
Inventory key-dups make "current stock that day" ambiguous; rec dups double-count.
- **(A)** `drop_duplicates()` on read; for inventory key-dups pick a deterministic rule (e.g. last, or mean) and document it.
- **(B)** Dedup in a cleaning pass with an explicit tie-breaker (latest load timestamp wins) and keep a rejected-dupes audit trail.
- **(C)** Unique constraint / idempotent upsert keyed on the natural key at source.

### 8. Negative `recommended_quantity` — 515 rows (min −5)
You can't order a negative amount; likely a sentinel or an un-clamped calculation.
- **(A)** Surface as-is but flag; or clamp to `0` at read for any consumer that needs a real order qty.
- **(B)** Cleaning rule: set negatives to `0` (or null + reason) and record the original.
- **(C)** Clamp in the recommendation generator and assert `qty ≥ 0` before emit.

### 9. Extreme outliers — `recommended_quantity` max 1,939 (99th pct = 52)
Concentrated in a few items (e.g. `1004`) — possibly a different unit or a bug.
- **(A)** Keep but flag values beyond a per-item band (e.g. > mean + k·σ) for review.
- **(B)** Winsorize/cap during cleaning, or split bulk items into their own unit-of-measure.
- **(C)** Range validation per item at source; capture unit-of-measure explicitly.

### 10. Fractional "pieces" — `inventory.quantity` 87% non-integer
The brief says quantities are in **pieces**, but 87% are fractional (`16.4`, …). Either the unit isn't pieces (weight/kg?) or there's a unit mismatch with `recommended_quantity` (which is integer).
- **(A)** Treat `quantity` as a float and don't assume integers anywhere (current behavior).
- **(B)** During cleaning, attach an explicit `unit` and convert to a common basis before comparing with order quantities.
- **(C)** Carry a `unit_of_measure` column from source; never overload one numeric column with two units. **Worth confirming with the data owner** — this changes how inventory vs. recommendation quantities compare.

### 11. `profit_margin` inconsistent — `orderable_items` (67% disagree)
`profit_margin` rarely equals `1 − purchase_price/suggested_retail_price`.
- **(A)** Don't trust the stored column; recompute on demand from price/cost.
- **(B)** Recompute and overwrite during cleaning (single source of truth).
- **(C)** Drop the derived column at source and compute it in the consuming layer, or recompute on every write so it can't drift.

### 12. Coverage gaps — inventory series + recs↔inventory join
4,942 missing day-rows across items; 4.3% of recommendations have no inventory row on their `ordering_day` (this is why `inventory-summary.last_orders[].current_quantity_in_store` is sometimes `null`).
- **(A)** Tolerate gaps; return `null` where stock is unknown (current behavior) rather than guessing.
- **(B)** Reconstruct a continuous daily series in cleaning via forward-fill or interpolation (only where a stable carry-forward is defensible) — this is the right place for "compute averages if stock is missing", clearly marked as estimated.
- **(C)** Guarantee a daily snapshot per active item at source (scheduled job writes one row per store/item/day).

## Recommendation

For **this service**: the cheap, lossless **(A)** fixes are **implemented** at
ingestion (`_clean` in `app/ingestion_service.py`) — canonicalize `store_id` and
`category`, drop exact duplicates, normalize dates, treat `quantity` as float —
because they fix correctness (esp. the `store_id` filter bug) without judgement
calls.

Defer **(B)** imputation/repair to a dedicated cleaning stage with an audit
trail, since fabricating prices/stock is a product decision, not an ingestion
default. Push for **(C)** schema-at-source (typed columns, enums, FK and range
constraints, unit-of-measure) as the durable fix — every issue above is something
a contract at the producing system would have prevented.
