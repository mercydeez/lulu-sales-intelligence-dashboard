"""
CSV import — real-data ingestion for pilots (the demo→pilot unlock).

A retailer uploads a CSV, maps their columns to our canonical model, we validate
every row, then commit. The parse / mapping / validation core here is PURE (no I/O)
so it unit-tests in isolation and runs identically in preview and commit. Persistence
+ name→id resolution live in async helpers at the bottom.

Sacred rule (repo-wide): VOLUME in units, VALUE in AED, never mixed. Sales rows are
UNITS; only *_aed / cost fields are money. The validators enforce the right type per
field so a unit count can never be silently treated as money.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

# Canonical schema per import type. `key` = canonical field; `kind` drives validation.
# kind: text | int | units | aed | date | id-ref(store|item)
SCHEMAS: Dict[str, Dict] = {
    "stores": {
        "target": "stores",
        "fields": {
            "name":     {"required": True,  "kind": "text",  "hint": "Store name (unique)"},
            "location": {"required": False, "kind": "text",  "hint": "Emirate / area"},
        },
    },
    "items": {
        "target": "items",
        "fields": {
            "name":           {"required": True,  "kind": "text", "hint": "Product / SKU name (unique)"},
            "category":       {"required": False, "kind": "text", "hint": "Category"},
            "unit_price_aed": {"required": False, "kind": "aed",  "hint": "Retail price in AED"},
            # E2-3: cost unlocks margin / GMROI. Recorded as an effective-dated
            # period in item_costs (valid from cost_from, or today) — not a scalar.
            "unit_cost_aed":  {"required": False, "kind": "aed",  "hint": "Cost per unit in AED (unlocks margin)"},
            "cost_from":      {"required": False, "kind": "date", "hint": "Date this cost took effect (YYYY-MM-DD)"},
        },
    },
    "sales": {
        "target": "sales_historical",
        "fields": {
            "date":  {"required": True, "kind": "date",  "hint": "YYYY-MM-DD"},
            "store": {"required": True, "kind": "ref_store", "hint": "Store name (must already exist)"},
            "item":  {"required": True, "kind": "ref_item",  "hint": "Product name (must already exist)"},
            "units": {"required": True, "kind": "units", "hint": "Units sold (whole number)"},
        },
    },
    "suppliers": {
        "target": "suppliers",
        "fields": {
            "name":           {"required": True,  "kind": "text", "hint": "Supplier name (unique)"},
            "contact_email":  {"required": False, "kind": "text", "hint": "Contact email"},
            "contact_phone":  {"required": False, "kind": "text", "hint": "Contact phone"},
            "lead_time_days": {"required": False, "kind": "int",  "hint": "Lead time in days"},
        },
    },
    "inventory": {
        "target": "inventory",
        "fields": {
            "store":             {"required": True,  "kind": "ref_store", "hint": "Store name"},
            "item":              {"required": True,  "kind": "ref_item",  "hint": "Product name"},
            "current_stock":     {"required": True,  "kind": "units", "hint": "On-hand units"},
            "unit_cost":         {"required": False, "kind": "aed",   "hint": "Cost per unit in AED"},
            "reorder_point":     {"required": False, "kind": "units", "hint": "Reorder trigger (units)"},
            "average_daily_sales": {"required": False, "kind": "units_f", "hint": "Avg units sold/day"},
            "last_sale_date":    {"required": False, "kind": "date",  "hint": "YYYY-MM-DD of last sale"},
        },
    },
}

MAX_ROWS = 50_000

# UAE-flavoured sample CSVs so a prospect can try the wizard before their own data
# (pilot-in-a-box). Headers deliberately differ from canonical keys to exercise mapping.
SAMPLES: Dict[str, str] = {
    "stores": (
        "Store Name,Emirate\n"
        "Dubai Marina Store,Dubai\n"
        "Deira City Store,Dubai\n"
        "Abu Dhabi Corniche,Abu Dhabi\n"
        "Sharjah Mega Mall,Sharjah\n"
    ),
    "items": (
        "Product,Category,Retail Price (AED)\n"
        "Fresh Milk 1L,Dairy,6.50\n"
        "Arabic Bread,Bakery,3.00\n"
        "Basmati Rice 5kg,Grains,28.00\n"
        "Mineral Water 1.5L,Beverages,2.00\n"
        "Dates Khalas 500g,Produce,22.00\n"
    ),
    "sales": (
        "Date,Store,Product,Units Sold\n"
        "2026-06-28,Dubai Marina Store,Fresh Milk 1L,42\n"
        "2026-06-28,Dubai Marina Store,Arabic Bread,80\n"
        "2026-06-29,Deira City Store,Basmati Rice 5kg,12\n"
        "2026-06-29,Abu Dhabi Corniche,Dates Khalas 500g,18\n"
        "2026-06-30,Sharjah Mega Mall,Mineral Water 1.5L,150\n"
    ),
    "suppliers": (
        "Supplier,Email,Phone,Lead Time (days)\n"
        "Emirates Fresh Supply Co,sales@emiratesfresh.ae,+97142000000,3\n"
        "Gulf Distribution LLC,orders@gulfdist.ae,+97143000000,7\n"
        "Al Madina Wholesale,info@almadina.ae,+97165000000,5\n"
    ),
    "inventory": (
        "Store,Product,On Hand,Unit Cost,Reorder At,Avg Daily Sales,Last Sale\n"
        "Dubai Marina Store,Fresh Milk 1L,120,4.20,50,40,2026-06-29\n"
        "Dubai Marina Store,Arabic Bread,0,1.90,60,75,2026-06-30\n"
        "Deira City Store,Basmati Rice 5kg,240,18.00,40,12,2026-06-29\n"
        "Abu Dhabi Corniche,Dates Khalas 500g,310,14.50,30,4,2026-04-02\n"
        "Sharjah Mega Mall,Mineral Water 1.5L,900,1.10,200,150,2026-06-30\n"
    ),
}


def sample_csv(import_type: str) -> Optional[str]:
    return SAMPLES.get(import_type)


def sample_xlsx(import_type: str) -> Optional[bytes]:
    """Build the .xlsx sample from the SAME SAMPLES text (E1-3), so the Excel and
    CSV samples can never drift apart. Generated on the fly; nothing on disk."""
    text = SAMPLES.get(import_type)
    if text is None:
        return None

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = import_type[:31]  # Excel caps sheet names at 31 chars
    for row in csv.reader(io.StringIO(text)):
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def import_types() -> List[str]:
    return list(SCHEMAS.keys())


def schema_for(import_type: str) -> Optional[Dict]:
    s = SCHEMAS.get(import_type)
    if not s:
        return None
    return {
        "import_type": import_type,
        "target": s["target"],
        "fields": [
            {"key": k, "required": v["required"], "kind": v["kind"], "hint": v["hint"]}
            for k, v in s["fields"].items()
        ],
    }


# --- messy-header tolerance (E1-3) -----------------------------------------
# Real retailer exports carry non-breaking spaces, stray BOMs, trailing unnamed
# columns and duplicate header names. Both parsers run headers through this so a
# .xlsx and a .csv of the same sheet map identically.

_INVISIBLE = "﻿ ​"  # BOM, non-breaking space, zero-width space


def normalize_headers(raw: List[str]) -> List[str]:
    """Clean + de-duplicate header names, dropping trailing empty columns.

    Duplicate names are suffixed (`name`, `name_2`) rather than silently collapsed —
    the row dict is keyed by header, so two columns called `name` would otherwise
    make the second overwrite the first and lose a column of the customer's data.
    """
    cleaned: List[str] = []
    for h in raw:
        h = "" if h is None else str(h)
        for ch in _INVISIBLE:
            h = h.replace(ch, " ")
        cleaned.append(" ".join(h.split()))  # collapse internal whitespace + trim

    while cleaned and cleaned[-1] == "":       # Excel loves trailing blank columns
        cleaned.pop()

    seen: Dict[str, int] = {}
    out: List[str] = []
    for h in cleaned:
        if h in seen:
            seen[h] += 1
            out.append(f"{h}_{seen[h]}")
        else:
            seen[h] = 1
            out.append(h)
    return out


def _cell_to_text(v) -> str:
    """Render a spreadsheet cell exactly as the CSV path would see it.

    Excel hands back typed values: dates as datetime, whole numbers as floats
    (42.0), and money as floats with binary noise (6.5000000000000002). Getting
    this wrong silently fails validation or shifts values, so it is done once here
    rather than left to _coerce.
    """
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        return f"{v:.6f}".rstrip("0").rstrip(".")  # kill float noise
    return str(v).strip()


def parse_csv(text: str, sample: Optional[int] = None) -> Tuple[List[str], List[Dict[str, str]]]:
    """Parse CSV text → (headers, rows-as-dicts). Tolerates a BOM and quoted fields.
    `sample` caps the number of rows returned (for preview)."""
    if text and text[0] == "﻿":
        text = text[1:]
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return [], []
    headers = normalize_headers(rows[0])
    out: List[Dict[str, str]] = []
    for r in rows[1:]:
        if not any(cell.strip() for cell in r):
            continue  # skip blank lines
        record = {headers[i]: (r[i] if i < len(r) else "") for i in range(len(headers))}
        out.append(record)
        if sample and len(out) >= sample:
            break
    return headers, out


# Magic bytes — never trust the client's declared file type.
_XLSX_MAGIC = b"PK\x03\x04"          # zip container (OOXML)
_XLS_MAGIC = b"\xd0\xcf\x11\xe0"     # OLE2 compound document (legacy BIFF)


def sniff_workbook_kind(data: bytes) -> Optional[str]:
    """'xlsx' | 'xls' | None, from the file's own bytes."""
    if data.startswith(_XLSX_MAGIC):
        return "xlsx"
    if data.startswith(_XLS_MAGIC):
        return "xls"
    return None


def _iter_xlsx_rows(data: bytes):
    """Stream rows from the first worksheet. read_only keeps a crafted 'zip bomb'
    from being materialised in memory all at once."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        ws = wb[wb.sheetnames[0]]
        for row in ws.iter_rows(values_only=True):
            yield list(row)
    finally:
        wb.close()


def _iter_xls_rows(data: bytes):
    """Legacy .xls via xlrd (2.x reads .xls only)."""
    import xlrd

    book = xlrd.open_workbook(file_contents=data)
    sheet = book.sheet_by_index(0)
    for idx in range(sheet.nrows):
        out = []
        for cell in sheet.row(idx):
            if cell.ctype == xlrd.XL_CELL_DATE:
                out.append(datetime(*xlrd.xldate_as_tuple(cell.value, book.datemode)))
            elif cell.ctype == xlrd.XL_CELL_EMPTY:
                out.append(None)
            else:
                out.append(cell.value)
        yield out


def parse_workbook(data: bytes, sample: Optional[int] = None) -> Tuple[List[str], List[Dict[str, str]]]:
    """Parse .xlsx/.xls bytes → the SAME (headers, rows) contract as parse_csv, so
    validate_rows / commit_import never learn there was a spreadsheet (E1-3).

    Raises ValueError on an unrecognised container or a workbook over MAX_ROWS —
    rows are counted while streaming rather than after materialising everything.
    """
    kind = sniff_workbook_kind(data)
    if kind == "xlsx":
        row_iter = _iter_xlsx_rows(data)
    elif kind == "xls":
        row_iter = _iter_xls_rows(data)
    else:
        raise ValueError("Not a recognised Excel file (.xlsx or .xls)")

    headers: List[str] = []
    out: List[Dict[str, str]] = []
    for raw_row in row_iter:
        if not headers:
            headers = normalize_headers([_cell_to_text(c) for c in raw_row])
            if not headers:
                return [], []
            continue

        cells = [_cell_to_text(c) for c in raw_row]
        if not any(c.strip() for c in cells):
            continue  # blank row — Excel exports trail hundreds of these
        out.append({headers[i]: (cells[i] if i < len(cells) else "") for i in range(len(headers))})

        if sample and len(out) >= sample:
            break
        if not sample and len(out) > MAX_ROWS:
            raise ValueError(f"Workbook exceeds the {MAX_ROWS:,}-row limit")

    return headers, out


def _coerce(kind: str, raw: str) -> Tuple[object, Optional[str]]:
    """Validate + coerce a single value by kind. Returns (value, error)."""
    v = (raw or "").strip()
    if kind == "text":
        return (None, "empty") if v == "" else (v, None)
    if v == "":
        return None, "empty"
    if kind in ("int", "units"):
        try:
            n = int(float(v))  # tolerate "12.0"
        except ValueError:
            return None, f"'{raw}' is not a whole number"
        if n < 0 and kind == "units":
            return None, "units cannot be negative"
        return n, None
    if kind == "units_f":
        try:
            f = float(v)
        except ValueError:
            return None, f"'{raw}' is not a number"
        return (None, "cannot be negative") if f < 0 else (round(f, 2), None)
    if kind == "aed":
        try:
            f = float(v.replace(",", "").replace("AED", "").strip())
        except ValueError:
            return None, f"'{raw}' is not a valid AED amount"
        return (None, "AED amount cannot be negative") if f < 0 else (round(f, 2), None)
    if kind == "date":
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(v, fmt).date().isoformat(), None
            except ValueError:
                continue
        return None, f"'{raw}' is not a recognised date (use YYYY-MM-DD)"
    if kind in ("ref_store", "ref_item"):
        return v, None  # resolved to an id at commit time
    return v, None


def default_mapping(import_type: str, headers: List[str]) -> Dict[str, str]:
    """Identity mapping for headers that already carry the canonical field names.

    Used by recurring imports (E2-2), where nobody is at a keyboard to draw the
    columns. EXACT matches only — a header that merely resembles a field is a
    guess, and a guess that silently loads the wrong column into `sales` is worse
    than a schedule that fails and says which field was not mapped.
    """
    schema = SCHEMAS.get(import_type)
    if not schema:
        return {}
    present = set(headers)
    return {field: field for field in schema["fields"] if field in present}


def validate_rows(import_type: str, headers: List[str], rows: List[Dict[str, str]],
                  mapping: Dict[str, str]) -> Dict:
    """Validate mapped rows. `mapping` maps canonical field -> source column.
    Returns {valid: [...cleaned dicts...], errors: [{row, field, message}], summary}."""
    schema = SCHEMAS.get(import_type)
    if not schema:
        return {"valid": [], "errors": [{"row": 0, "field": "", "message": "Unknown import type"}],
                "summary": {"total": 0, "valid": 0, "errors": 1}}

    # Every required canonical field must be mapped to a present column.
    missing = [k for k, f in schema["fields"].items()
               if f["required"] and (mapping.get(k) not in headers)]
    if missing:
        return {"valid": [], "errors": [{"row": 0, "field": m, "message": f"Required field '{m}' is not mapped"} for m in missing],
                "summary": {"total": len(rows), "valid": 0, "errors": len(missing)}}

    valid: List[Dict] = []
    errors: List[Dict] = []
    rejected: List[Dict] = []   # the ORIGINAL rows, so the operator can fix + re-upload
    for i, row in enumerate(rows, start=1):
        cleaned: Dict[str, object] = {}
        row_errors: List[Dict] = []
        for field, spec in schema["fields"].items():
            src = mapping.get(field)
            raw = row.get(src, "") if src else ""
            if not src or src not in headers:
                if spec["required"]:
                    row_errors.append({"row": i, "field": field, "message": "not mapped"})
                continue
            val, err = _coerce(spec["kind"], raw)
            if err == "empty":
                if spec["required"]:
                    row_errors.append({"row": i, "field": field, "message": "is required but empty"})
                else:
                    cleaned[field] = None
            elif err:
                row_errors.append({"row": i, "field": field, "message": err})
            else:
                cleaned[field] = val
        if row_errors:
            errors.extend(row_errors)
            reasons = "; ".join(f"{e['field']}: {e['message']}" for e in row_errors)
            rejected.append({**row, "_row": i, "_reason": reasons})
        else:
            # Carry the source row number so commit-time skips can be reported against
            # the operator's own spreadsheet. Stripped before any INSERT.
            cleaned["__row"] = i
            cleaned["__source"] = row
            valid.append(cleaned)

    return {
        "valid": valid,
        "errors": errors[:200],  # cap returned errors; summary keeps the true count
        # Every rejected row, uncapped — the route decides what to persist/serve.
        "rejected": rejected,
        "summary": {"total": len(rows), "valid": len(valid),
                    "errors": len(rows) - len(valid), "error_fields": len(errors)},
    }


# --- E1-5: data-quality report ----------------------------------------------
#
# Trust: the product admits what it cannot see. The scorecard grades the FILE, not
# the customer, and every finding names the exact rows so it can be fixed. Anomalies
# are WARNINGS — a legitimate promo spike must never silently drop a row.

_MAX_REPORT_ITEMS = 50        # per finding list, in the response
_MIN_GROUP_FOR_ANOMALY = 5    # a 2-row group has no meaningful spread
_ANOMALY_Z = 3.5              # modified z-score threshold (Iglewicz & Hoaglin)


def _grade(pct: float) -> str:
    if pct >= 99: return "A"
    if pct >= 95: return "B"
    if pct >= 90: return "C"
    if pct >= 80: return "D"
    return "F"


def _median(xs: List[float]) -> float:
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def build_quality_report(import_type: str, valid_rows: List[Dict],
                         errors: List[Dict], total_rows: int) -> Dict:
    """Grade an upload. Pure — same inputs, same report, in preview and at commit.

    * missing_days   — gaps INSIDE the file's own date range per store. A file
                       covering one week must not be marked down for the other 51.
    * duplicate_keys — the same (store, item, date) more than once: double-counted
                       revenue if committed.
    * unit_anomalies — robust modified z-score (median/MAD, not mean/stdev, so one
                       huge outlier can't hide the rest). Warnings only.
    """
    report: Dict = {
        "missing_days": [], "missing_days_count": 0,
        "duplicate_keys": [], "duplicate_keys_count": 0,
        "unit_anomalies": [], "unit_anomalies_count": 0,
        "scorecard": {},
    }

    valid_count = len(valid_rows)
    completeness = (valid_count / total_rows * 100.0) if total_rows else 0.0

    uniqueness = continuity = plausibility = 100.0

    if import_type == "sales" and valid_rows:
        # --- duplicates on the natural key -----------------------------------
        seen: Dict[tuple, List[int]] = {}
        for r in valid_rows:
            key = (str(r.get("store", "")).lower(), str(r.get("item", "")).lower(), r.get("date"))
            seen.setdefault(key, []).append(r.get("__row"))
        dupes = {k: v for k, v in seen.items() if len(v) > 1}
        report["duplicate_keys_count"] = len(dupes)
        report["duplicate_keys"] = [
            {"store": k[0], "item": k[1], "date": k[2], "occurrences": len(v), "rows": v[:10]}
            for k, v in list(dupes.items())[:_MAX_REPORT_ITEMS]
        ]
        dup_extra = sum(len(v) - 1 for v in dupes.values())
        uniqueness = max(0.0, (1 - dup_extra / valid_count) * 100.0)

        # --- continuity: gaps within each store's own covered range -----------
        by_store: Dict[str, set] = {}
        for r in valid_rows:
            d = r.get("date")
            if d:
                by_store.setdefault(str(r.get("store", "")), set()).add(date.fromisoformat(d))
        expected = covered = 0
        for store, days in by_store.items():
            lo, hi = min(days), max(days)
            span = (hi - lo).days + 1
            expected += span
            covered += len(days)
            gaps = [lo + timedelta(days=i) for i in range(span) if (lo + timedelta(days=i)) not in days]
            if gaps:
                report["missing_days_count"] += len(gaps)
                if len(report["missing_days"]) < _MAX_REPORT_ITEMS:
                    report["missing_days"].append({
                        "store": store,
                        "from": lo.isoformat(), "to": hi.isoformat(),
                        "missing_count": len(gaps),
                        "missing": [g.isoformat() for g in gaps[:10]],
                    })
        continuity = (covered / expected * 100.0) if expected else 100.0

        # --- unit anomalies (warnings) ---------------------------------------
        groups: Dict[tuple, List[Dict]] = {}
        for r in valid_rows:
            groups.setdefault((str(r.get("store", "")).lower(), str(r.get("item", "")).lower()), []).append(r)
        flagged = 0
        for (store, item), rs in groups.items():
            if len(rs) < _MIN_GROUP_FOR_ANOMALY:
                continue
            units = [float(r.get("units") or 0) for r in rs]
            med = _median(units)
            devs = [abs(u - med) for u in units]
            mad = _median(devs)

            # MAD collapses to 0 whenever more than half the values are identical
            # (7 days of exactly 10 units, then a 9999 spike). Guarding on `mad == 0`
            # would swallow precisely the outlier we exist to find. Iglewicz &
            # Hoaglin's fallback is the mean absolute deviation.
            if mad > 0:
                scale = mad / 0.6745
            else:
                mean_ad = sum(devs) / len(devs)
                if mean_ad == 0:
                    continue  # every value identical — nothing is anomalous
                scale = 1.253314 * mean_ad

            for r, u in zip(rs, units):
                z = (u - med) / scale
                if abs(z) > _ANOMALY_Z:
                    flagged += 1
                    if len(report["unit_anomalies"]) < _MAX_REPORT_ITEMS:
                        report["unit_anomalies"].append({
                            "row": r.get("__row"), "store": store, "item": item,
                            "date": r.get("date"), "units": r.get("units"),
                            "median_units": round(med, 2), "z": round(z, 1),
                        })
        report["unit_anomalies_count"] = flagged
        plausibility = max(0.0, (1 - flagged / valid_count) * 100.0)

    overall = round((completeness + uniqueness + continuity + plausibility) / 4.0, 1)
    report["scorecard"] = {
        "completeness_pct": round(completeness, 1),   # rows that validated
        "uniqueness_pct": round(uniqueness, 1),       # no double-counted keys
        "continuity_pct": round(continuity, 1),       # no gaps inside the covered range
        "plausibility_pct": round(plausibility, 1),   # no unexplained unit spikes
        "overall_pct": overall,
        "grade": _grade(overall),
        "anomalies_are_warnings": True,
    }
    return report


def rejected_rows_csv(headers: List[str], rejected: List[Dict]) -> str:
    """Render rejected rows back as CSV — the operator's own columns, plus why each
    row failed — so the file can be fixed and re-uploaded directly."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([*headers, "_row", "_reason"])
    for r in rejected:
        w.writerow([*(r.get(h, "") for h in headers), r.get("_row", ""), r.get("_reason", "")])
    return buf.getvalue()


# --- persistence (async; tenant-scoped) ------------------------------------
from sqlalchemy import text as _sql  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402


async def _resolve_maps(db: AsyncSession, tenant_id: int) -> Tuple[Dict[str, int], Dict[str, int]]:
    stores = (await db.execute(_sql(
        "SELECT id, lower(name) AS n FROM stores WHERE tenant_id = :t"), {"t": tenant_id})).fetchall()
    items = (await db.execute(_sql(
        "SELECT id, lower(name) AS n FROM items WHERE tenant_id = :t"), {"t": tenant_id})).fetchall()
    return ({r.n: r.id for r in stores}, {r.n: r.id for r in items})


_MAX_REJECTED_STORED = 5_000   # bound import_jobs.notes; the report says what was cut


def _as_date(v) -> Optional[date]:
    """Bind a date-kind value to a DATE column.

    `_coerce` renders dates as ISO strings (the JSON API needs them that way), but
    asyncpg binds DATE parameters strictly and rejects a str with
    "'str' object has no attribute 'toordinal'". Every date that reaches an INSERT
    must come through here — the sales and inventory imports were silently broken
    for exactly this reason.
    """
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def _strip_markers(r: Dict) -> Dict:
    """Drop the bookkeeping keys validate_rows attaches (__row / __source) so they
    never reach an INSERT."""
    return {k: v for k, v in r.items() if not k.startswith("__")}


def _record_skip(bucket: List[Dict], cleaned_row: Dict, reason: str) -> None:
    """Capture the operator's ORIGINAL row (not our cleaned view) so the downloadable
    file has their columns, their values, and the reason we couldn't use it."""
    if len(bucket) >= _MAX_REJECTED_STORED:
        return
    source = cleaned_row.get("__source") or _strip_markers(cleaned_row)
    bucket.append({**source, "_row": cleaned_row.get("__row"), "_reason": reason})


async def _record_undo(db: AsyncSession, tenant_id: int, job_id: Optional[int],
                       table: str, op: str, row_id: int,
                       before_image: Optional[dict] = None) -> None:
    """Append one entry to the import undo ledger (E2-4).

    `job_id is None` means the caller is not building a reversible import, so no
    ledger is written — and the job is marked non-reversible, rather than us
    pretending a rollback would be safe.
    """
    if job_id is None or row_id is None:
        return
    await db.execute(_sql("""
        INSERT INTO import_row_undo (tenant_id, import_job_id, table_name, op, row_id, before_image)
        VALUES (:t, :j, :tbl, :op, :rid, CAST(:img AS JSONB))
    """), {"t": tenant_id, "j": job_id, "tbl": table, "op": op, "rid": row_id,
           "img": json.dumps(before_image, default=str) if before_image is not None else None})


async def commit_import(db: AsyncSession, tenant_id: int, import_type: str,
                        valid_rows: List[Dict], import_job_id: Optional[int] = None) -> Dict:
    """Persist validated rows into the canonical tables, tenant-scoped. Upserts
    stores/items by name; resolves store/item names → ids for sales/inventory
    (unresolved rows are skipped and reported). Caller commits.

    Returns `skipped_rows`: the ORIGINAL source rows that could not be resolved,
    with the reason — so the operator can download, fix and re-upload exactly
    those rows instead of guessing (E1-5).

    When `import_job_id` is supplied, every row this writes is recorded in the
    undo ledger so the import can be reversed exactly (E2-4). Four of the five
    types are pure appends; `inventory` upserts, so its pre-image is captured
    BEFORE the write — otherwise a rollback would delete stock records the import
    only overwrote, and never created.
    """
    imported, skipped, skip_reasons = 0, 0, []
    skipped_rows: List[Dict] = []

    if import_type == "stores":
        for r in valid_rows:
            # `RETURNING id` also tells us whether the row was really inserted:
            # ON CONFLICT DO NOTHING returns nothing on a conflict, and counting a
            # no-op as "imported" would inflate the number we report.
            store_id = (await db.execute(_sql("""
                INSERT INTO stores (name, location, tenant_id, import_job_id)
                VALUES (:name, :loc, :t, :j)
                ON CONFLICT DO NOTHING
                RETURNING id
            """), {"name": r["name"], "loc": r.get("location"), "t": tenant_id,
                   "j": import_job_id})).scalar()
            if store_id is None:
                continue
            await _record_undo(db, tenant_id, import_job_id, "stores", "insert", store_id)
            imported += 1

    elif import_type == "items":
        for r in valid_rows:
            item_id = (await db.execute(_sql("""
                INSERT INTO items (name, category, unit_price_aed, tenant_id, import_job_id)
                VALUES (:name, :cat, COALESCE(:price, 10.00), :t, :j)
                RETURNING id
            """), {"name": r["name"], "cat": r.get("category"),
                   "price": r.get("unit_price_aed"), "t": tenant_id,
                   "j": import_job_id})).scalar()
            # item_costs.item_id is ON DELETE CASCADE, so undoing the item undoes
            # the cost period set_item_cost opens below. No separate ledger entry.
            await _record_undo(db, tenant_id, import_job_id, "items", "insert", item_id)

            # E2-3: a supplied cost opens an effective-dated period in item_costs.
            # set_item_cost closes the straddling period first — a plain INSERT would
            # always collide with the open-ended current period. The trigger mirrors
            # the result onto items.unit_cost_aed. No cost => the item simply has
            # none, and every margin metric keeps saying `needs: cost`.
            cost = r.get("unit_cost_aed")
            if item_id and cost is not None:
                # _coerce renders dates as ISO strings; asyncpg binds a DATE
                # parameter strictly and rejects a str. Hand it a real date.
                vf = _as_date(r.get("cost_from"))
                await db.execute(_sql("""
                    SELECT set_item_cost(:t, :iid, :cost, COALESCE(:vf, CURRENT_DATE), 'import')
                """), {"t": tenant_id, "iid": item_id, "cost": cost, "vf": vf})
            imported += 1

    elif import_type == "suppliers":
        for r in valid_rows:
            supplier_id = (await db.execute(_sql("""
                INSERT INTO suppliers (name, contact_email, contact_phone, lead_time_days,
                                       tenant_id, import_job_id)
                VALUES (:name, :email, :phone, COALESCE(:lead, 7), :t, :j)
                RETURNING id
            """), {"name": r["name"], "email": r.get("contact_email"),
                   "phone": r.get("contact_phone"), "lead": r.get("lead_time_days"),
                   "t": tenant_id, "j": import_job_id})).scalar()
            await _record_undo(db, tenant_id, import_job_id, "suppliers", "insert", supplier_id)
            imported += 1

    elif import_type == "sales":
        store_map, item_map = await _resolve_maps(db, tenant_id)
        for r in valid_rows:
            sid = store_map.get(str(r["store"]).lower())
            iid = item_map.get(str(r["item"]).lower())
            if not sid or not iid:
                skipped += 1
                reason = (f"unresolved {'store' if not sid else 'item'}: "
                          f"{r['store'] if not sid else r['item']}")
                if len(skip_reasons) < 50:
                    skip_reasons.append(reason)
                _record_skip(skipped_rows, r, reason)
                continue
            sale_id = (await db.execute(_sql("""
                INSERT INTO sales_historical (date, store_id, item_id, sales, tenant_id, import_job_id)
                VALUES (:d, :s, :i, :u, :t, :j)
                RETURNING id
            """), {"d": _as_date(r["date"]), "s": sid, "i": iid, "u": r["units"],
                   "t": tenant_id, "j": import_job_id})).scalar()
            await _record_undo(db, tenant_id, import_job_id, "sales_historical", "insert", sale_id)
            imported += 1

    elif import_type == "inventory":
        store_map, item_map = await _resolve_maps(db, tenant_id)
        for r in valid_rows:
            sid = store_map.get(str(r["store"]).lower())
            iid = item_map.get(str(r["item"]).lower())
            if not sid or not iid:
                skipped += 1
                reason = f"unresolved {'store' if not sid else 'item'}"
                if len(skip_reasons) < 50:
                    skip_reasons.append(reason)
                _record_skip(skipped_rows, r, reason)
                continue
            # E2-4: this is an UPSERT, so capture the row as it stands BEFORE the
            # write. Without the pre-image a rollback could only delete, which
            # would destroy stock records the import overwrote but never created.
            before = None
            if import_job_id is not None:
                before = (await db.execute(_sql("""
                    SELECT to_jsonb(inv) FROM inventory inv
                     WHERE store_id = :s AND item_id = :i
                """), {"s": sid, "i": iid})).scalar()

            # CAST(:uc AS NUMERIC) is load-bearing. In `COALESCE(:uc, 0)` the bind
            # parameter has no declared type, so Postgres resolves it from the
            # neighbouring literal — integer — and 7.77 AED was silently stored as
            # 7. Same for average_daily_sales. reorder_point IS an integer column,
            # so its `0`-typed literal is correct as written.
            inv_id = (await db.execute(_sql("""
                INSERT INTO inventory (store_id, item_id, current_stock, unit_cost,
                    reorder_point, average_daily_sales, last_sale_date)
                VALUES (:s, :i, :cs, COALESCE(CAST(:uc AS NUMERIC), 0), COALESCE(:rp, 50),
                        COALESCE(CAST(:ads AS NUMERIC), 0), :lsd)
                ON CONFLICT (store_id, item_id) DO UPDATE SET
                    current_stock = EXCLUDED.current_stock,
                    unit_cost = EXCLUDED.unit_cost,
                    reorder_point = EXCLUDED.reorder_point,
                    average_daily_sales = EXCLUDED.average_daily_sales,
                    last_sale_date = EXCLUDED.last_sale_date
                RETURNING id
            """), {"s": sid, "i": iid, "cs": r["current_stock"],
                   "uc": r.get("unit_cost"), "rp": r.get("reorder_point"),
                   "ads": r.get("average_daily_sales"), "lsd": _as_date(r.get("last_sale_date"))})
            ).scalar()

            await _record_undo(db, tenant_id, import_job_id, "inventory",
                               "update" if before else "insert", inv_id,
                               before_image=before)
            imported += 1

    return {"imported": imported, "skipped": skipped, "skip_reasons": skip_reasons[:50],
            "skipped_rows": skipped_rows}
