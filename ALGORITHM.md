# Recommendation Algorithm — Detailed Description

How `GET /recommendations/recompute` generates an order quantity. The logic
lives in [`app/recompute_service.py`](app/recompute_service.py). It was
reverse-engineered from the provided `order_recommendations.csv` (see
[DATA_NOTES.md](DATA_NOTES.md) for that analysis).

## The idea in one sentence

It's a classic inventory policy called **order-up-to** (a.k.a. base-stock):

> **Decide a target stock level, then order just enough to top up to it.**

## The three steps

```
1.  estimated_daily_demand = average daily sales, inferred from inventory history
2.  target_stock           = cover_days × estimated_daily_demand
3.  recommended_quantity   = max(0, round(target_stock − current_stock))
```

Everything else is *how we estimate demand* and *why each piece is shaped this way*.

---

## Step 1 — Estimate daily demand (the subtle part)

We only have **inventory snapshots** (stock on hand per day), not a sales log,
so we infer sales from how stock moves day to day:

- Stock went **down** → **consumption** (someone bought it).
- Stock went **up** → a **delivery** (a restock arrived).

**Key decision: average the drops over *only the days stock actually fell*, not
over every day.**

Why? On a delivery day, the restock hides that day's sales. Example — bananas:

| Day | Stock | Change | Interpretation |
|-----|-------|--------|----------------|
| Mon | 20 | — | — |
| Tue | 10 | **−10** | sold 10 ✅ counts |
| Wed | 25 | +15 | delivery — sales hidden, net change is *up* |
| Thu | 20 | **−5** | sold 5 ✅ counts |

- **This method** (consumption days only): `(10 + 5) / 2 = 7.5` per day.
- **Naïve method** (all days): `(10 + 0 + 5) / 3 = 5.0` per day.

The naïve method counts Wednesday as "0 sales" when sales were merely masked by
the delivery. With a 1–2 day delivery lead time, *roughly half* the days are
delivery days — so averaging over all days **halves** the estimate. On the real
data, item 1001's demand read **3.17** (diluted) vs **~7** (true). That low
estimate was the cause of spuriously-zero recommendations.

If **no day** shows a drop (a single data point, or perfectly flat stock), no
consumption can be observed: demand is reported as `0` and the response sets
`insufficient_history: true` — flagging that the `0` means "unknown", not
"genuinely no demand".

## Step 2 — Turn demand into a target

```
target_stock = cover_days × estimated_daily_demand
```

`cover_days` = how many days of demand you want sitting on the shelf. It's the
one tuning knob (query param, **default 5**).

Bananas: `5 days × 7.5/day = 37.5` pieces is the level to stock up to.

**Why 5?** We calibrated it: replay the algorithm against the real
`order_recommendations.csv` and pick the `cover_days` that best reproduces the
file's numbers. `cover_days = 5` gave the smallest median error (~5 pieces), and
5 days is a sensible cover for fresh food.

| cover_days | median \|recompute − file\| |
|---|---|
| 3 | 14 |
| 4 | 10 |
| **5** | **5** ← best |
| 6 | 6 |
| 7 | 10 |

## Step 3 — Order the gap

```
recommended_quantity = max(0, round(target_stock − current_stock))
```

- `current_stock` = quantity on the **most recent** inventory day.
- Order the difference between target and what's already there.
- `max(0, …)` because you can't un-order — already above target ⇒ order nothing.

This is **why some recommendations are 0**: not a failure, but the policy saying
*"you already have enough."*

---

## Worked examples

**A. Normal restock** — demand 7.5, cover 5 → target 37.5; current stock 20:
`round(37.5 − 20)` = **order 18**.

**B. Already well-stocked** — target 37.5; current stock 40:
`max(0, 37.5 − 40)` = `max(0, −2.5)` = **order 0** (more than 5 days on hand).

**C. Lower the knob** — `cover_days = 2` → target 15; current stock 20:
`max(0, 15 − 20)` = **order 0**. Smaller cover ⇒ lower target ⇒ more zeros.
(A low `cover_days` is the usual reason "everything is 0".)

**D. Brand-new item** — one inventory day, stock 12: no drop ever observed ⇒
demand 0, **`insufficient_history: true`**, order 0. The flag distinguishes "I
couldn't estimate this" from a real "you have enough".

---

## Assumptions

1. **Stock decreases = sales; increases = deliveries.** No separate sales/delivery feed exists, so movement is inferred from inventory.
2. **Delivery days hide that day's sales**, so they're excluded from the demand average.
3. **Demand is roughly stable** — a simple historical average is a fair predictor (no seasonality/trend modelling).
4. **One target level per item**, scaled to its own demand (a low-volume herb and high-volume bananas get different targets automatically).
5. **`current_stock` = latest recorded day**; inventory dates are clean ISO (ingestion drops unparseable dates).
6. **Lead time is folded into `cover_days`** rather than modelled separately (the file's lead time is only 1–2 days).

## Limitations

- A **transparent baseline**, not FreshFlow's production model — reproduces the file to a *median* ~5 pieces, but individual items can diverge (item 1001: this says 6, file says 23).
- **Average demand ignores trend/seasonality** — a moving-average / EWMA forecast would do better.
- **Inferring sales from stock is lossy** — if a delivery *and* sales land on the same day, sales are still under-counted.
- **No safety stock / service-level math** — a real base-stock level adds a buffer for demand variability; here `cover_days` is flat.

## Response fields

Every input is returned so the recommendation is auditable:

| Field | Meaning |
|---|---|
| `current_stock` | Latest recorded stock on hand. |
| `estimated_daily_demand` | Mean drop over consumption days. |
| `target_stock` | `cover_days × estimated_daily_demand`. |
| `recomputed_quantity` | The order: `max(0, round(target − current))`. |
| `insufficient_history` | `true` when demand couldn't be estimated (no observed drop). |
| `file_quantity` | The original file's recommended quantity (if present) for comparison. |
| `delta` | `recomputed_quantity − file_quantity`. |
