"""CSV parsing and validation for uploaded FreshFlow datasets.

Turns an uploaded file into a validated pandas DataFrame. Validation
rejects malformed or wrong-shaped files early with an actionable 422 so
bad input never reaches the store.
"""

from __future__ import annotations

import io
import warnings

import pandas as pd
from fastapi import HTTPException, UploadFile, status

# Date columns are normalized to canonical ISO strings so equality and
# lexicographic (== chronological) filtering on the retrieve endpoints is exact.
_DATE_COLUMNS = {"day", "ordering_day", "delivery_day"}

# Cap per-file upload size to avoid memory exhaustion from an unbounded POST.
# The provided datasets are a few MB; 50 MB leaves generous headroom.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def parse_csv(
    upload: UploadFile, required_columns: set[str]
) -> tuple[pd.DataFrame, int]:
    """Parse an uploaded CSV into a validated DataFrame.

    Malformed rows (wrong number of fields — the FreshFlow sample data
    contains some, see DATA_NOTES.md) are skipped rather than failing the
    whole file, and the count is returned so the caller can report it.
    Structural problems (unparseable bytes, missing required columns) are
    still hard failures.

    Args:
        upload: The multipart file from the request.
        required_columns: Columns that must be present; the file is
            rejected if any are missing.

    Returns:
        Tuple of (parsed DataFrame with date columns coerced to ISO
        strings, number of malformed rows skipped).

    Raises:
        HTTPException: 413 if the file exceeds MAX_UPLOAD_BYTES; 422 if the
            file is unparseable or missing required columns. The message names
            the offending file/columns.
    """
    # Read one byte past the limit so we can detect (not just truncate) oversize
    # uploads, then reject before building any DataFrame.
    raw = upload.file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"'{upload.filename}' exceeds the {MAX_UPLOAD_BYTES}-byte upload limit."
            ),
        )

    # Count and skip rows whose field count doesn't match the header instead
    # of aborting. The callable form of on_bad_lines requires the python engine.
    skipped_rows = 0

    def _skip_and_count(_bad_line: list[str]) -> None:
        nonlocal skipped_rows
        skipped_rows += 1
        return None

    try:
        frame = pd.read_csv(
            io.BytesIO(raw),
            engine="python",
            on_bad_lines=_skip_and_count,
        )
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not parse '{upload.filename}' as CSV: {exc}",
        ) from exc

    missing = required_columns - set(frame.columns)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"'{upload.filename}' is missing required columns: "
                f"{', '.join(sorted(missing))}"
            ),
        )

    _normalize_dates(frame)
    frame = _clean(frame)
    return frame, skipped_rows


def _normalize_dates(frame: pd.DataFrame) -> None:
    """Canonicalize known date columns to ISO ``YYYY-MM-DD`` strings, in place.

    Parses each value (handling non-zero-padded or odd formats) and re-emits a
    canonical zero-padded ISO string so lexicographic comparison equals
    chronological order downstream. Unparseable/missing dates become ``None``
    (not the literal string ``"nan"``), so consumers can filter them cleanly
    instead of crashing in ``strptime`` or mis-sorting them after real dates.
    """
    for column in _DATE_COLUMNS & set(frame.columns):
        # Infer the format for clean (consistent) columns; fall back to
        # per-element parsing for dirty ones. Silence the resulting "could not
        # infer format" notice — coercing the odd bad value to NaT is intended.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            parsed = pd.to_datetime(frame[column], errors="coerce")
        iso = parsed.dt.strftime("%Y-%m-%d")
        # strftime yields NaN for NaT; make those explicit None.
        frame[column] = iso.where(parsed.notna(), None)


def _clean(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply cheap, lossless data-quality fixes (see DATA_NOTES.md, tier A).

    - Canonicalize ``store_id`` (strip + lowercase) so the 8 dirty variants in
      the sample data (``STORE_A``, ``" store_a"``, ...) collapse to one key.
      Without this, exact-match filters silently miss rows.
    - Canonicalize ``category`` (strip + title-case) to merge ``FRUITS/fruits``.
    - Drop exact duplicate rows (done after the above so case/space-only
      variants are deduplicated too).

    Returns the cleaned frame. Judgement-call repairs (imputation, key-level
    dedup, NaT-date handling) are intentionally NOT done here — see the cleaning
    stage discussion in DATA_NOTES.md.
    """
    if "store_id" in frame.columns:
        frame["store_id"] = frame["store_id"].str.strip().str.lower()
    if "category" in frame.columns:
        frame["category"] = frame["category"].str.strip().str.title()
    return frame.drop_duplicates().reset_index(drop=True)
